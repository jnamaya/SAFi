"""
Registry browsing and GUI installation of MCP tool servers (backlog 48).

Every route here is admin-only through the existing `require_role` decorator, so
this feature adds no new permission and does not touch rbac.py.

The shape of the flow, and the reason it is shaped that way:

    search  ->  install (pending)  ->  another admin approves  ->  connected

Installing is deliberately not the same act as approving, and neither is the
same act as granting. A connected server is still unusable until the
organization allows the connector and a policy lists it. Making installation
easy is safe precisely because it is only the first of four steps, and the other
three predate this feature.
"""
import logging

from flask import Blueprint, jsonify, request, session

from ..config import Config
from ..core.rbac import require_role
from ..core.services import mcp_install, mcp_manager, mcp_registry
from ..core import mcp_runtime
from ..persistence import mcp_store

log = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp_api', __name__, url_prefix='/api/mcp')


def _actor():
    user = session.get('user') or {}
    return user.get('id'), user.get('org_id')


def _reload_runtime():
    """Apply the current approved set to this worker immediately.

    The other workers pick it up from the generation counter (mcp_store), so an
    install is live everywhere within one request each, without a restart and
    without inventing any IPC.
    """
    try:
        mcp_runtime.sync_db_servers(
            mcp_install.desired_runtime_servers(),
            reserved_tool_names=mcp_manager.builtin_tool_names(),
        )
        mcp_manager.refresh_discovered_connectors()
    except Exception as e:
        log.error("MCP runtime reload failed: %s", e)


@mcp_bp.route('/registry/search', methods=['GET'])
@require_role('admin')
def registry_search():
    """Browse the official registry. Read-only, cached, no install side effects."""
    if not mcp_install.gui_install_enabled(Config):
        return jsonify({"ok": False, "error": "Browser installation is disabled on this deployment."}), 403
    try:
        result = mcp_registry.search(
            query=(request.args.get('q') or '').strip(),
            limit=int(request.args.get('limit') or 30),
            cursor=(request.args.get('cursor') or '').strip(),
            config=Config,
        )
    except mcp_registry.RegistryError as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    # Annotate each entry with THIS deployment's answer, so the UI never has to
    # re-derive the rule and get a different one.
    for entry in result["servers"]:
        ok, reason, _ = mcp_install.validate_installable(entry, Config)
        entry["installable"] = ok
        entry["not_installable_reason"] = reason
    return jsonify({"ok": True, **result})


@mcp_bp.route('/servers', methods=['GET'])
@require_role('admin')
def list_servers():
    user_id, org_id = _actor()
    servers = mcp_store.list_servers(org_id)
    for row in servers:
        live = mcp_runtime.summary()["servers"].get(row["connector_key"])
        row["connected"] = bool(live and not live.get("error"))
        row["tools"] = (live or {}).get("tools", [])
        row["connection_error"] = (live or {}).get("error")
        row["self_installed"] = str(row.get("installed_by")) == str(user_id)
    return jsonify({
        "ok": True,
        "servers": servers,
        "install_mode": mcp_install.install_mode(Config),
        "sole_reviewer": mcp_install.can_review_own_install(org_id, user_id),
    })


@mcp_bp.route('/servers', methods=['POST'])
@require_role('admin')
def install_server():
    """Install a registry entry. Lands as pending; approval is a separate call."""
    user_id, org_id = _actor()
    if not org_id:
        return jsonify({"ok": False, "error": "No organization context."}), 400

    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({"ok": False, "error": "A server name is required."}), 400

    try:
        entry = mcp_registry.get_server(name, config=Config)
    except mcp_registry.RegistryError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    if entry is None:
        return jsonify({"ok": False, "error": "No registry entry with that exact name."}), 404

    ok, reason, remote = mcp_install.validate_installable(entry, Config)
    if not ok:
        return jsonify({"ok": False, "error": reason}), 400

    record = mcp_store.install(org_id, user_id, {
        "connector_key": mcp_install.available_key(entry["name"]),
        "registry_name": entry["name"],
        "registry_version": entry["version"],
        "title": entry["title"],
        "description": entry["description"],
        "transport": remote["transport"],
        "url": remote["url"],
    })
    return jsonify({"ok": True, "server": record}), 201


@mcp_bp.route('/servers/<server_id>/review', methods=['POST'])
@require_role('admin')
def review_server(server_id):
    """Approve or reject a pending install.

    Separation of duties, same rule as knowledge base documents: the person who
    installed it may not approve it, unless they are the org's only eligible
    reviewer, in which case the sign-off is recorded as non-independent rather
    than quietly counted as a real second pair of eyes.
    """
    user_id, org_id = _actor()
    body = request.get_json(silent=True) or {}
    decision = (body.get('decision') or '').strip().lower()
    if decision not in ('approve', 'reject'):
        return jsonify({"ok": False, "error": "decision must be 'approve' or 'reject'."}), 400

    row = mcp_store.get_server(server_id)
    if not row or row['org_id'] != org_id:
        return jsonify({"ok": False, "error": "Not found."}), 404

    independent = True
    if str(row.get('installed_by')) == str(user_id):
        if not mcp_install.can_review_own_install(org_id, user_id):
            return jsonify({
                "ok": False,
                "error": "You installed this server, so another admin has to review it.",
            }), 403
        independent = False

    status = mcp_store.STATUS_ACTIVE if decision == 'approve' else mcp_store.STATUS_REJECTED
    updated = mcp_store.set_status(
        server_id, status, user_id, org_id,
        note=(body.get('note') or '').strip(), independent=independent,
    )
    if updated is None:
        return jsonify({"ok": False, "error": "Not found."}), 404

    warnings = []
    if status == mcp_store.STATUS_ACTIVE:
        _reload_runtime()
        live = mcp_runtime.summary()["servers"].get(row['connector_key'])
        if live and live.get('error'):
            warnings.append(f"Approved, but the server did not connect: {live['error']}")
        else:
            findings = mcp_install.scan_tool_descriptions(
                mcp_runtime.tools(), row['connector_key']
            )
            if findings:
                # Reported, not auto-blocked: the text is advisory to a human,
                # and a false positive must not strand a legitimate tool. The
                # Conscience still audits whatever the draft became.
                warnings.append(
                    "This server's tool descriptions matched prompt-injection "
                    "signatures: " + "; ".join(findings[:5])
                )
                log.warning(
                    "MCP server '%s' tool descriptions matched signatures: %s",
                    row['connector_key'], findings,
                )

    return jsonify({
        "ok": True,
        "server": updated,
        "independent_review": independent,
        "warnings": warnings,
    })


@mcp_bp.route('/servers/<server_id>', methods=['DELETE'])
@require_role('admin')
def remove_server(server_id):
    user_id, org_id = _actor()
    row = mcp_store.get_server(server_id)
    if not row or row['org_id'] != org_id:
        return jsonify({"ok": False, "error": "Not found."}), 404
    if not mcp_store.delete(server_id, org_id, user_id):
        return jsonify({"ok": False, "error": "Not found."}), 404
    _reload_runtime()
    return jsonify({"ok": True})
