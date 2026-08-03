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
named identically to the connector.

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
    "github": (
        "github_search_repos",
        "github_get_repo",
        "github_list_issues",
        "github_read_file",
    ),
    "google_drive": (
        "google_list_files",
        "google_read_file",
        "google_upload_file",
    ),
    "sharepoint": (
        "sharepoint_search",
        "sharepoint_read",
        "sharepoint_upload",
        "sharepoint_search_sites",
        "sharepoint_search_site_files",
        "sharepoint_list_folders",
        "sharepoint_get_tree",
    ),
    "web_search": ("web_search", "web_news"),
}


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
    """
    expanded: List[str] = []
    seen = set()
    for name in names:
        if not isinstance(name, str):
            continue
        for fn in CONNECTOR_TOOLS.get(name, (name,)):
            if fn not in seen:
                seen.add(fn)
                expanded.append(fn)
    return expanded
