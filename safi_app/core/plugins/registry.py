from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple

Handler = Callable[..., Awaitable[Tuple[str, Optional[Dict[str, Any]]]]]

_PLUGINS: List[Tuple[FrozenSet[str], Handler]] = []


def register_plugin(agent_names, handler: Handler) -> None:
    _PLUGINS.append((frozenset(n.lower().strip() for n in agent_names), handler))


def plugins_for(active_profile_name: str) -> List[Handler]:
    key = (active_profile_name or "").lower().strip()
    return [h for names, h in _PLUGINS if key in names or "*" in names]
