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

from flask import Blueprint, jsonify

from ..core import mcp_runtime
from ..core.rbac import require_role

log = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp_api', __name__, url_prefix='/api/mcp')


@mcp_bp.route('/servers', methods=['GET'])
@require_role('admin')
def list_servers():
    """What is installed, what it is offering, and what is wrong with it.

    Admin-only because it names the deployment's infrastructure and its
    connection errors, which is operational detail a member has no use for.
    """
    summary = mcp_runtime.summary()
    servers = []
    for key, entry in summary["servers"].items():
        tools = entry.get("tools") or []
        servers.append({
            "key": key,
            "label": entry.get("label") or key,
            "origin": mcp_runtime.origin_of(key) or "file",
            "connected": not entry.get("error"),
            "error": entry.get("error"),
            "tools": [
                {
                    "name": name,
                    "description": (mcp_runtime.tools().get(name) or {}).get("description", ""),
                }
                for name in tools
            ],
        })
    servers.sort(key=lambda s: s["label"].lower())
    return jsonify({
        "ok": True,
        "servers": servers,
        "tool_count": summary["tool_count"],
    })
