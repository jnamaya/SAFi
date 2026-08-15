"""
Connector name -> function names.

WHY THIS EXISTS
---------------
The Agent Wizard is connector-level: a user ticks "github", not four checkboxes for
github_search_repos / github_get_repo / github_list_issues / github_read_file. So an
agent's `tools_json` holds CONNECTOR names.

Two components then read that list, and they used to disagree about what a name means:

  * mcp_manager.get_tools_for_agent() treats it as connector names and EXPANDS them
    into the per-function schemas the model is offered.
  * WillGate.evaluate_tool_intent() treats it as function names and matches EXACTLY.

The consequence was not a degraded feature, it was a dead one. An agent granted
"github" was offered four functions and the Will could authorize none of them, because
"github_get_repo" is not in ["web_search", "github"]. Same for sharepoint (7 functions)
and google_drive (3). Every multi-function connector was unusable, deterministically,
and the only connectors that worked were the ones whose single function happened to be
named identically to the connector. (All three multi-function connectors named in
this history retired 2026-08-15: github in favour of GitHub's official MCP server,
google_drive absorbed by the Workspace gateway, sharepoint by the Graph gateway.
The mechanism this history motivated governs their successors.)

So synderesis._stamp_tool_authorization() now expands through this table before
stamping profile["allowed_tools"], and the Will keeps exact matching.

DO NOT give the Will prefix matching instead. The Will must not interpret names: a
"starts with github_" rule would silently authorize github_delete_repo the day someone
adds it. Expansion belongs at compile time, where it is inspectable in the profile.

KEEPING THIS HONEST
-------------------
This table is a second place where those names live, which is exactly how the two
layers diverged in the first place. tests/test_tool_connector_expansion.py calls the
real mcp_manager builder for every key below and asserts the emitted names match, so
adding a function to a connector without updating this table fails the suite rather
than silently un-authorizing the new tool.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

# Derived from mcp_manager.get_tools_for_agent() and pinned by the test named above.
# Single-function connectors are listed too, so callers never need to special-case them.
CONNECTOR_TOOLS: Dict[str, Tuple[str, ...]] = {
    "find_places": ("find_places",),
    "get_analyst_recommendations": ("get_analyst_recommendations",),
    "get_company_news": ("get_company_news",),
    "get_earnings_history": ("get_earnings_history",),
    "get_stock_price": ("get_stock_price",),
    "web_search": ("web_search", "web_news"),
}

# Connectors discovered from operator-installed MCP servers (core/mcp_runtime.py),
# registered once at boot. Kept SEPARATE from the table above on purpose:
#
#   * the built-in table stays literal, reviewed and diffable, and the test named
#     in the docstring keeps pinning it against what mcp_manager emits. A table
#     that discovery rewrote in place could not be pinned by anything.
#   * built-ins win. A third-party server cannot redefine `github`, which would
#     silently repoint an existing agent's authorized tools at someone else's code.
#
# Registration is boot-time only, from a file on disk no request path can reach.
_DISCOVERED: Dict[str, Tuple[str, ...]] = {}


def register_discovered_connector(name: str, functions: Iterable[str]) -> bool:
    """Register an MCP server as a connector bundle. Returns False if refused.

    Refusal is not an error to recover from; it means the deployment's server
    file collides with the shipped floor, and the operator has to rename their
    server. Logging is the caller's job (mcp_manager reports the whole result).
    """
    if not name or not isinstance(name, str):
        return False
    if name in CONNECTOR_TOOLS:
        return False
    fns = tuple(f for f in functions if isinstance(f, str) and f)
    if not fns:
        return False
    _DISCOVERED[name] = fns
    return True


def clear_discovered_connectors() -> None:
    """Drop every discovered registration. For tests and for a re-discovery."""
    _DISCOVERED.clear()


def discovered_connectors() -> Dict[str, Tuple[str, ...]]:
    return dict(_DISCOVERED)


def expand_connectors(names: Iterable[str]) -> List[str]:
    """
    Expand connector names into the function names the model can actually call.

    Order-preserving and de-duplicated, so a profile's allowed_tools reads in the
    order the agent was configured rather than in hash order.

    A name that is not a known connector passes through unchanged. That is what lets
    a policy narrow WITHIN a connector by naming functions directly: granting
    "github" at the agent level and listing only "github_read_file" in the policy
    intersects to read-only GitHub. It is also why a misconfigured or nonexistent
    tool name is harmless here; nothing can be called that does not exist, and the
    Will still authorizes only what this produces.

    Built-ins are consulted before discovered MCP connectors, and an unknown name
    still passes through unchanged. That last part is what makes an install whose
    MCP discovery failed fail CLOSED: the connector name expands to itself, none
    of the server's real function names reach `allowed_tools`, and the Will blocks
    every call the model attempts.
    """
    expanded: List[str] = []
    seen = set()
    for name in names:
        if not isinstance(name, str):
            continue
        for fn in CONNECTOR_TOOLS.get(name) or _DISCOVERED.get(name, (name,)):
            if fn not in seen:
                seen.add(fn)
                expanded.append(fn)
    return expanded
