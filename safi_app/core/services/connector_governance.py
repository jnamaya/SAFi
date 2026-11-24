from __future__ import annotations

import threading
import time
from typing import FrozenSet, List, Optional

CONNECTOR_METADATA: dict = {}

_CACHE_TTL_SECONDS = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ConnectorNotAllowedError(RuntimeError):

    def __init__(self, connector: str, context: str = ""):
        self.connector = connector
        super().__init__(
            f"Data source '{connector}' is blocked by this organization's connector policy"
            + (f" ({context})" if context else "")
        )


def get_org_allowlist(org_id) -> Optional[FrozenSet[str]]:
    if not org_id:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(org_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]
    from ...persistence import database as db
    raw = db.get_org_connector_config(org_id).get("allowlist")
    allow = None if raw is None else frozenset(c for c in raw if c in CONNECTOR_METADATA)
    with _cache_lock:
        _cache[org_id] = (allow, now)
    return allow


def invalidate_org(org_id) -> None:
    with _cache_lock:
        _cache.pop(org_id, None)


def connector_allowed(connector: str, org_id) -> bool:
    allow = get_org_allowlist(org_id)
    return allow is None or connector in allow


def assert_connector_allowed(connector: str, org_id, context: str = "") -> None:
    if connector not in CONNECTOR_METADATA:
        raise ConnectorNotAllowedError(connector, "unknown data source")
    if not connector_allowed(connector, org_id):
        raise ConnectorNotAllowedError(connector, context)


def list_connectors_for_org(org_id) -> List[dict]:
    allow = get_org_allowlist(org_id)
    return [
        {"key": k, **meta, "allowed": (allow is None or k in allow)}
        for k, meta in CONNECTOR_METADATA.items()
    ]


def usable_connector_keys(user_id, org_id=None, user_role="member") -> FrozenSet[str]:
    from ...persistence import database as db
    from ...profile_resolver import AGENTS
    from ...role_config import ROLE_CONFIG
    from ..faculties.synderesis import authorized_tools
    from ..tool_connectors import expand_connectors, CONNECTOR_TOOLS, discovered_connectors

    wanted = {k: set(expand_connectors(list(meta["tools"])))
              for k, meta in CONNECTOR_METADATA.items()}
    tool_catalog = {**CONNECTOR_TOOLS, **discovered_connectors()}

    policy_cache: dict = {}

    def _policy_tools(policy_id):
        if policy_id in (None, "", "standalone"):
            return None
        if policy_id not in policy_cache:
            allowed = None
            try:
                pol = db.get_policy(policy_id)
                wr = (pol or {}).get("will_rules")
                if isinstance(wr, dict):
                    allowed = wr.get("allowed_tools")
            except Exception:
                allowed = None
            policy_cache[policy_id] = allowed
        return policy_cache[policy_id]

    candidates = [(p.get("tools"), p.get("policy_id")) for p in AGENTS.values()]
    try:
        import json as _json
        for a in db.list_agents(user_id, org_id, user_role, ROLE_CONFIG["visibility_roles"]):
            raw = a.get("tools_json")
            tools = raw if isinstance(raw, list) else (_json.loads(raw or "[]") or [])
            candidates.append((tools, a.get("policy_id")))
    except Exception:
        pass

    usable = set()
    for advertised, policy_id in candidates:
        if len(usable) == len(wanted):
            break
        granted = set(authorized_tools(advertised, _policy_tools(policy_id), tool_catalog))
        for key, fns in wanted.items():
            if key not in usable and granted & fns:
                usable.add(key)
    return frozenset(usable)


def connectors_for_member(user_id, org_id=None, user_role="member") -> List[dict]:
    usable = usable_connector_keys(user_id, org_id, user_role)
    return [{**c, "usable": c["key"] in usable} for c in list_connectors_for_org(org_id)]
