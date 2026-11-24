from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

CONNECTOR_TOOLS: Dict[str, Tuple[str, ...]] = {
    "agentic_coding": (
        "read", "grep", "glob", "list",
        "bash", "write", "edit", "patch", "delete",
        "webfetch", "websearch", "task", "todowrite", "skill", "lsp", "question",
    ),
    "coding_harness": (
        "read", "grep", "glob", "list",
        "bash", "write", "edit", "patch", "delete",
        "webfetch", "websearch", "task", "todowrite", "skill", "lsp", "question",
    ),
    "software_engineer_tools": (
        "read", "grep", "glob", "list",
        "bash", "write", "edit", "patch", "delete",
        "webfetch", "websearch", "task", "todowrite", "skill", "lsp", "question",
    ),
    "sysadmin_tools": (
        "read", "grep", "glob", "list",
        "bash", "write", "edit", "delete",
        "webfetch", "websearch", "todowrite", "question",
        "m365_admin", "azure_admin", "cloud_status",
    ),
    "security_engineer_tools": (
        "read", "grep", "glob", "list",
        "bash", "write", "edit", "patch", "delete",
        "webfetch", "websearch", "task", "todowrite", "question",
    ),
    "find_places": ("find_places",),
    "get_analyst_recommendations": ("get_analyst_recommendations",),
    "get_company_news": ("get_company_news",),
    "get_earnings_history": ("get_earnings_history",),
    "get_stock_price": ("get_stock_price",),
    "web_search": ("web_search", "web_news"),
}

_DISCOVERED: Dict[str, Tuple[str, ...]] = {}


def register_discovered_connector(name: str, functions: Iterable[str]) -> bool:
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
    _DISCOVERED.clear()


def discovered_connectors() -> Dict[str, Tuple[str, ...]]:
    return dict(_DISCOVERED)


def expand_connectors(names: Iterable[str]) -> List[str]:
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
