import asyncio
import logging
import secrets

from flask import Blueprint, jsonify, redirect, request, session

from ..core import mcp_runtime
from ..core.rbac import require_role, get_current_role
from ..core.tool_connectors import expand_connectors
from ..role_config import ROLE_CONFIG
from ..persistence import database as db

log = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp_api', __name__, url_prefix='/api/mcp')


def _usage(user_id, org_id):
    policies, agents = {}, {}

    try:
        for policy in db.list_policies(user_id, org_id) or []:
            rules = policy.get('will_rules')
            allowed = rules.get('allowed_tools') if isinstance(rules, dict) else None
            if not isinstance(allowed, list):
                continue
            for tool in expand_connectors([t for t in allowed if isinstance(t, str)]):
                policies.setdefault(tool, []).append(policy.get('name') or policy.get('id'))
    except Exception as e:
        log.warning("policy tool usage lookup failed: %s", e)

    try:
        for agent in db.list_agents(
            user_id, org_id, get_current_role(), ROLE_CONFIG["visibility_roles"]
        ) or []:
            tools = agent.get('tools')
            if not isinstance(tools, list):
                continue
            for tool in expand_connectors([t for t in tools if isinstance(t, str)]):
                agents.setdefault(tool, []).append(agent.get('name') or agent.get('key'))
    except Exception as e:
        log.warning("agent tool usage lookup failed: %s", e)

    return policies, agents


@mcp_bp.route('/servers', methods=['GET'])
@require_role('admin')
def list_servers():
    from ..core.services.mcp_manager import is_guest, server_allows_org

    user = session.get('user') or {}
    org_id = user.get('org_id')
    guest = is_guest(user.get('id') or '', user.get('email') or '')
    policy_use, agent_use = _usage(user.get('id'), org_id)

    summary = mcp_runtime.summary()
    discovered = mcp_runtime.tools()
    servers = []
    for key, entry in summary["servers"].items():
        if guest or not server_allows_org(key, org_id):
            continue
        tools = []
        for name in entry.get("tools") or []:
            tools.append({
                "name": name,
                "description": (discovered.get(name) or {}).get("description", ""),
                "policies": sorted(set(policy_use.get(name, []))),
                "agents": sorted(set(agent_use.get(name, []))),
            })
        record = {
            "key": key,
            "label": entry.get("label") or key,
            "origin": mcp_runtime.origin_of(key) or "file",
            "connected": not entry.get("error"),
            "error": entry.get("error"),
            "auth": entry.get("auth") or "",
            "tools": tools,
            "enabled_count": sum(1 for t in tools if t["policies"]),
        }
        if record["auth"] == "oauth":
            from ..core.services import mcp_oauth
            row = db.get_oauth_token(user.get('id'), mcp_oauth.provider_key(key))
            record["user_connected"] = bool(row and row.get("access_token"))
            record["connected"] = record["user_connected"]
        servers.append(record)
    servers.sort(key=lambda s: s["label"].lower())
    return jsonify({
        "ok": True,
        "servers": servers,
        "tool_count": sum(len(s["tools"]) for s in servers),
    })


_PENDING_KEY = "mcp_oauth_pending"


def _oauth_server_or_error(server_key):
    from ..core.services.mcp_manager import file_servers, is_guest, server_allows_org

    user = session.get('user') or {}
    if not user.get('id'):
        return None, ("Sign in first.", 401)
    if is_guest(user.get('id') or '', user.get('email') or ''):
        return None, ("Demo accounts cannot connect tool servers.", 403)

    definition = file_servers().get(server_key)
    if not definition or (definition.get("auth") or "").lower() != "oauth":
        return None, ("No OAuth-protected server by that name.", 404)
    orgs = [str(o) for o in (definition.get("orgs") or []) if o]
    if orgs and str(user.get('org_id')) not in orgs:
        return None, ("This server is not available to your organization.", 403)

    from ..core.services.mcp_manager import member_can_connect
    if not member_can_connect(user.get('id'), user.get('org_id'),
                              user.get('role'), server_key):
        return None, ("None of your agents use this server's tools yet, so there "
                      "is nothing to connect. Ask an editor to enable its tools "
                      "in a policy first.", 403)
    return definition, None


def _redirect_uri(server_key):
    from ..config import Config
    return f"{Config.WEB_BASE_URL.rstrip('/')}/api/mcp/auth/{server_key}/callback"


@mcp_bp.route('/auth/<server_key>/login', methods=['GET'])
def oauth_login(server_key):
    from ..core.services import mcp_oauth

    definition, err = _oauth_server_or_error(server_key)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]

    try:
        discovery = mcp_oauth.discover(definition["url"])
        client = mcp_oauth.ensure_client(
            server_key, definition, discovery, _redirect_uri(server_key))
    except mcp_oauth.OAuthConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    verifier, challenge = mcp_oauth.make_pkce()
    state = secrets.token_urlsafe(32)
    session[_PENDING_KEY] = {"server": server_key, "state": state, "verifier": verifier}
    url = mcp_oauth.build_authorization_url(
        discovery, client["client_id"], _redirect_uri(server_key), state, challenge,
        scopes=definition.get("scopes"),
    )
    return redirect(url)


@mcp_bp.route('/auth/<server_key>/callback', methods=['GET'])
def oauth_callback(server_key):
    from ..core.services import mcp_oauth
    from ..core.services.mcp_manager import discover_after_connect

    definition, err = _oauth_server_or_error(server_key)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]

    pending = session.pop(_PENDING_KEY, None) or {}
    state = (request.args.get('state') or '').strip()
    code = (request.args.get('code') or '').strip()
    if (not code or not state or pending.get("server") != server_key
            or not secrets.compare_digest(state, pending.get("state") or "")):
        return jsonify({"ok": False, "error": "Authorization response did not match the request."}), 400

    user = session.get('user') or {}
    try:
        discovery = mcp_oauth.discover(definition["url"])
        client = mcp_oauth.ensure_client_readonly(server_key, definition, discovery)
        body = mcp_oauth.exchange_code(
            discovery, client, code, _redirect_uri(server_key), pending["verifier"])
    except mcp_oauth.OAuthConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    mcp_oauth.store_tokens(user['id'], server_key, body, org_id=user.get('org_id'))

    import threading

    def _discover():
        try:
            found = asyncio.run(discover_after_connect(server_key, body["access_token"]))
            log.info("MCP server '%s': %d tool(s) discovered after sign-in.",
                     server_key, len(found))
        except Exception as e:
            log.warning("post-sign-in discovery failed for %s: %s", server_key, e)

    worker = threading.Thread(target=_discover, daemon=True)
    worker.start()
    worker.join(timeout=20)
    if worker.is_alive():
        log.warning("post-sign-in discovery for %s is still running; not waiting.", server_key)

    return redirect('/')


@mcp_bp.route('/auth/<server_key>/disconnect', methods=['POST'])
def oauth_disconnect(server_key):
    from ..core.services import mcp_oauth
    from ..core.services.mcp_manager import file_servers
    from ..persistence import database as db

    user = session.get('user') or {}
    if not user.get('id'):
        return jsonify({"ok": False, "error": "Sign in first."}), 401
    mcp_oauth.revoke_at_server(user['id'], server_key,
                               file_servers().get(server_key) or {})
    db.delete_oauth_token(user['id'], mcp_oauth.provider_key(server_key),
                          org_id=user.get('org_id'))
    return jsonify({"ok": True})
