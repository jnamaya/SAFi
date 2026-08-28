"""
Read-only view of the tool servers this deployment has installed (backlog 48d).

THIS BLUEPRINT INSTALLS NOTHING, AND THAT IS THE DESIGN
------------------------------------------------------
An earlier version let an admin browse the official registry and install a
hosted server from the browser. It was removed. Two reasons, one practical and
one structural:

  * Practical: the public registry is mostly servers that do not answer an
    anonymous connection. Measured 2026-08-14, four of ten. A catalogue whose
    buttons mostly fail is worse than no catalogue.
  * Structural: installation belongs on the host. An operator running the CLI
    already has shell there, so installing a server adds no privilege; an admin
    in a browser is a different person with different rights, and letting them
    install meant a per-org install table, an approval workflow, and a tenancy
    problem, all of which existed only to make a browser safe for a job that was
    never the browser's.

The pipeline now has one shape:

    CLI installs on the host
      -> SAFi connects and asks the server what tools it has
      -> those tools appear here, VISIBLE AND INACTIVE
      -> a policy enables specific tools and blocks others
      -> an agent is assigned the approved set
      -> the Will authorizes every call by exact name

Nothing an admin can do on this screen grants anything to anyone. It is an
inventory.
"""
import asyncio
import logging
import secrets

from flask import Blueprint, jsonify, redirect, request, session

from ..core import mcp_runtime
from ..core.rbac import require_role
from ..core.tool_connectors import expand_connectors
from ..persistence import database as db

log = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp_api', __name__, url_prefix='/api/mcp')


def _usage(user_id, org_id):
    """Which policies enable each tool, and which agents are assigned it.

    The screen previously printed "Inactive" as fixed text, which made it a
    claim the page never checked: it stayed on the screen after a policy
    enabled the tool, which is the one moment the reader is looking for
    confirmation. Status has to be read from the same place enforcement reads
    it, so this expands exactly what Synderesis expands.

    Names are resolved through expand_connectors because a policy may list a
    connector or an individual function, and both authorize the function.
    """
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
        for agent in db.list_agents(user_id, org_id, 'admin') or []:
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
    """What is installed, what it is offering, and what is wrong with it.

    Admin-only because it names the deployment's infrastructure and its
    connection errors, which is operational detail a member has no use for.
    """
    from ..core.services.mcp_manager import is_guest, server_allows_org

    user = session.get('user') or {}
    org_id = user.get('org_id')
    # A guest is made ADMIN of a throwaway organization by the public demo
    # login, so @require_role('admin') admits one. Every other MCP path refuses
    # guests outright; this one must too.
    guest = is_guest(user.get('id') or '', user.get('email') or '')
    policy_use, agent_use = _usage(user.get('id'), org_id)

    summary = mcp_runtime.summary()
    discovered = mcp_runtime.tools()
    servers = []
    for key, entry in summary["servers"].items():
        # The same org gate every other path applies. Without it this screen
        # reported the label, the tool names and descriptions, and any
        # connection error of EVERY installed server to an admin of any
        # organization on the deployment. 'admin' is the top of the ladder in
        # rbac.py and is scoped to one organization, so there is no role for
        # which the unfiltered view is the right answer.
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
            # Per-user servers: "connected" is a property of the person looking,
            # not of the process, so report the viewer's own state.
            from ..core.services import mcp_oauth
            row = db.get_oauth_token(user.get('id'), mcp_oauth.provider_key(key))
            record["user_connected"] = bool(row and row.get("access_token"))
            record["connected"] = record["user_connected"]
        servers.append(record)
    servers.sort(key=lambda s: s["label"].lower())
    return jsonify({
        "ok": True,
        "servers": servers,
        # Counted from what was returned, not from the deployment-wide summary,
        # which would leak the same fact one integer at a time.
        "tool_count": sum(len(s["tools"]) for s in servers),
    })


# ── Per-user authorization for OAuth-protected servers (backlog 48i) ──────────
#
# The flow is OAuth 2.1 authorization code with PKCE, and the token asked for is
# audience-bound to the MCP server (RFC 8707), never to anything upstream of it.
# SAFi ends up holding a token that opens exactly one tool server on behalf of
# exactly one member; the server does its own upstream exchange if it needs one.
#
# These routes are member-facing, not admin-only: per-user tokens only work if
# the person using the agent can connect their own account. Guests are refused,
# and a server restricted to named organizations refuses members of others —
# both checked in the login AND the callback, because a code obtained seconds
# before a restriction landed must not redeem into a stored token.

_PENDING_KEY = "mcp_oauth_pending"


def _oauth_server_or_error(server_key):
    """The definition of an OAuth server the caller may use, or (None, reason)."""
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

    # Members may connect only when some agent they can reach is granted the
    # server's tools: connecting is the means to an agent's end, and a token no
    # agent will read should never be invited. Admins bypass, because the first
    # connection is what discovers the catalog in the first place.
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
    # Server-side session, keyed by state: the callback proves it is answering
    # THIS browser's request or it gets nothing.
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

    # First sign-in doubles as discovery: an OAuth server shows its tools to a
    # token, not to the boot process, so this token captures the catalog for
    # everyone. Best effort, and in a bounded thread: a server that answers the
    # token exchange but then wedges the MCP transport must not be able to hold
    # this response hostage — the SDK's reconnect loop can outlive any inner
    # timeout, so the bound is on the thread, not inside it. If discovery never
    # finishes, the sign-in still succeeded and the next one retries.
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
    # Revoke at the server BEFORE deleting the row: the stored token is the
    # proof of possession its revocation endpoint requires. Best effort; the
    # row dies either way, so disconnect never blocks on a dead gateway.
    mcp_oauth.revoke_at_server(user['id'], server_key,
                               file_servers().get(server_key) or {})
    db.delete_oauth_token(user['id'], mcp_oauth.provider_key(server_key),
                          org_id=user.get('org_id'))
    return jsonify({"ok": True})
