"""
Pre-turn plugin registry — the seam the License & Governance Agreement §III
promises ("total freedom to add, edit, or remove custom tools, knowledge bases,
and plugins"), which was not true while the orchestrator imported its plugins
by name.

A plugin is a pair: the agent names it serves, and an async handler with the
exact contract the shipped plugins already implement:

    async def handler(user_prompt: str, active_profile_name: str, log)
        -> tuple[str, dict | None]

returning the (possibly untouched) prompt and a data payload — the generic keys
the Intellect consumes: `rag_query_override`, `preformatted_context_string`,
`plugin_error`. The orchestrator iterates registrations; it no longer knows any
plugin's name.

Two properties worth stating because they are the governance story:

REGISTRATION IS OPERATOR-INSTALLED CODE. register_plugin() is called from a
module import at startup, not from any request path — a user cannot reach it.
Installing a plugin is equivalent in trust to installing the package itself.

PLUGIN OUTPUT IS NOT GATED BY PHASE ZERO. The payload enters the Intellect's
context exactly as the shipped plugins' output always has — as grounding, not
as a scanned prompt. A custom plugin is therefore the organization's own §III
risk, precisely like a custom tool (see GOVERNANCE_BACKLOG 32z/37). The audit
half still holds: whatever the plugin fed the draft, the Conscience scores the
result and the Will decides on the ledger.

This file is covered by the Core Loop integrity manifest: it is the MECHANISM.
The registrations an organization adds are its own content and are not.
"""
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple

Handler = Callable[..., Awaitable[Tuple[str, Optional[Dict[str, Any]]]]]

_PLUGINS: List[Tuple[FrozenSet[str], Handler]] = []


def register_plugin(agent_names, handler: Handler) -> None:
    """Register `handler` for the given agent names (the values the
    orchestrator carries as active_profile_name — register both the display
    and sanitized forms, as the shipped plugins match both). "*" serves every
    agent."""
    _PLUGINS.append((frozenset(n.lower().strip() for n in agent_names), handler))


def plugins_for(active_profile_name: str) -> List[Handler]:
    """Handlers registered for this agent, in registration order."""
    key = (active_profile_name or "").lower().strip()
    return [h for names, h in _PLUGINS if key in names or "*" in names]
