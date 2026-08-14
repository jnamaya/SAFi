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
import logging

from flask import Blueprint, jsonify, session

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
    user = session.get('user') or {}
    policy_use, agent_use = _usage(user.get('id'), user.get('org_id'))

    summary = mcp_runtime.summary()
    discovered = mcp_runtime.tools()
    servers = []
    for key, entry in summary["servers"].items():
        tools = []
        for name in entry.get("tools") or []:
            tools.append({
                "name": name,
                "description": (discovered.get(name) or {}).get("description", ""),
                "policies": sorted(set(policy_use.get(name, []))),
                "agents": sorted(set(agent_use.get(name, []))),
            })
        servers.append({
            "key": key,
            "label": entry.get("label") or key,
            "origin": mcp_runtime.origin_of(key) or "file",
            "connected": not entry.get("error"),
            "error": entry.get("error"),
            "tools": tools,
            "enabled_count": sum(1 for t in tools if t["policies"]),
        })
    servers.sort(key=lambda s: s["label"].lower())
    return jsonify({
        "ok": True,
        "servers": servers,
        "tool_count": summary["tool_count"],
    })
