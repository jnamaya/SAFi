"""
Per-organization data-source connector allow-list — the admin control over
which external accounts members may link to their SAFi identity.

WHY THIS EXISTS
---------------
Before this, /api/auth/{provider}/login checked that you were logged in and
nothing else. Any member of any org could link Google Drive, SharePoint or
GitHub to a governed agent, no admin involvement, no record that it happened.
The tool layer could stop an agent *calling* google_drive
(_stamp_tool_authorization), but nothing stopped the credential existing.

WHY THE CREDENTIAL STAYS PER-USER
---------------------------------
This governs the catalogue, not the credential model. Connections remain
delegated per-user OAuth (tokens in oauth_tokens keyed by user_id, provider)
rather than an org-wide service principal, because delegated access inherits the
source system's own ACLs, keeps reads attributable to a real human in that
system's audit log, and dies when the user is offboarded. See GOVERNANCE_BACKLOG
item 20 for the full reasoning — this is deliberate, not unfinished.

CONTRACT (mirrors provider_governance, deliberately)
----------------------------------------------------
- The allow-list lives in organizations.settings.connector_allowlist as a list
  of keys from CONNECTOR_METADATA. Absent/None means unrestricted, which is what
  every existing org has, so this ships without changing anyone's behaviour.
- Writes go through db.set_org_connector_allowlist, which evidence-logs to
  org_compliance_log in the same transaction.
- Both the login route and the callback assert_connector_allowed(). FAIL
  CLOSED. Guarding only the login route would leave the callback reachable
  directly with a code obtained moments before the connector was disallowed.
- No org context (user has no org) = unrestricted. A single-user local install
  has no admin to set a policy, and failing closed there would break the
  Quick Start for no security gain.

Note the two namespaces. OAuth *account* keys (what oauth_tokens.provider
stores, what the login routes were named for) are distinct from tool
*connector* names (tool_connectors.py): one account could serve several
connectors. This module governs the account and carries the tool mapping so
the admin UI can say what allowing it actually unlocks.

THE CATALOG IS NOW EMPTY, DELIBERATELY. The last delegated connector
(microsoft/sharepoint) retired 2026-08-15, absorbed by the Graph gateway;
github and google_drive went the same day (GOVERNANCE_BACKLOG 48k). Their
successors are OAuth MCP servers, governed per server by the `orgs` field in
the operator's file and per member by the agent-grant gate in mcp_manager.
This module and its routes are the machinery an empty catalog leaves idle;
deleting the machinery itself is a separate, pending decision, because it is
also the shape any future delegated account would reuse.
"""
from __future__ import annotations

import threading
import time
from typing import FrozenSet, List, Optional

# key -> what an admin needs to know to make the decision. "tools" is the
# tool-connector namespace (tool_connectors.CONNECTOR_TOOLS), not this one.
CONNECTOR_METADATA: dict = {}

_CACHE_TTL_SECONDS = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ConnectorNotAllowedError(RuntimeError):
    """Raised when a member tries to link a data source their organization has
    not allowed. Terminal — never caught to substitute a different connector."""

    def __init__(self, connector: str, context: str = ""):
        self.connector = connector
        super().__init__(
            f"Data source '{connector}' is blocked by this organization's connector policy"
            + (f" ({context})" if context else "")
        )


def get_org_allowlist(org_id) -> Optional[FrozenSet[str]]:
    """Resolve an org's connector allow-list (60s cache). None = unrestricted.

    Unknown keys are dropped on read, so removing a connector from
    CONNECTOR_METADATA cannot resurrect it via a stale stored list. A
    stored-but-empty list blocks everything (fail closed); the write path
    refuses to store one, the same way the provider allow-list does."""
    if not org_id:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(org_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]
    from ...persistence import database as db  # lazy: avoids an import cycle at module load
    raw = db.get_org_connector_config(org_id).get("allowlist")
    allow = None if raw is None else frozenset(c for c in raw if c in CONNECTOR_METADATA)
    with _cache_lock:
        _cache[org_id] = (allow, now)
    return allow


def invalidate_org(org_id) -> None:
    """Bust the cached allow-list after a write."""
    with _cache_lock:
        _cache.pop(org_id, None)


def connector_allowed(connector: str, org_id) -> bool:
    allow = get_org_allowlist(org_id)
    return allow is None or connector in allow


def assert_connector_allowed(connector: str, org_id, context: str = "") -> None:
    """Fail closed. Called from both the login route and the callback: a code
    obtained before the connector was disallowed must not still redeem."""
    if connector not in CONNECTOR_METADATA:
        raise ConnectorNotAllowedError(connector, "unknown data source")
    if not connector_allowed(connector, org_id):
        raise ConnectorNotAllowedError(connector, context)


def list_connectors_for_org(org_id) -> List[dict]:
    """The full catalogue with an `allowed` flag — single source of truth for
    both the member's Settings tab and the admin control. The member's tab
    renders only the allowed ones; the admin needs the blocked ones too, to be
    able to turn them back on."""
    allow = get_org_allowlist(org_id)
    return [
        {"key": k, **meta, "allowed": (allow is None or k in allow)}
        for k, meta in CONNECTOR_METADATA.items()
    ]


def usable_connector_keys(user_id, org_id=None, user_role="member") -> FrozenSet[str]:
    """Connectors that at least one agent this member can reach is actually
    authorized to call.

    Being org-allowed is not enough to be worth offering. Without this check a
    member could grant SAFi read access to their whole Drive and get nothing:
    the token would sit encrypted in oauth_tokens while
    WillGate.evaluate_tool_intent refused every google_drive call, because
    allowed_tools is agent-tools ∩ policy-tools and google_drive was in neither.
    A live credential nothing consumes is blast radius with no benefit, and an
    awkward question from anyone reviewing why those tokens exist.

    Reuses synderesis.authorized_tools so this answers with the same
    intersection the Will enforces. Deliberately does NOT call get_profile:
    that is the full governance compiler (charter, values, worldview layering)
    and this runs on every /api/auth/status. Only the tool authorization is
    needed, and it comes from the same function either way.
    """
    from ...persistence import database as db
    from ..faculties.synderesis import AGENTS, authorized_tools
    from ..tool_connectors import expand_connectors

    # connector key -> the function names it would put on the table
    wanted = {k: set(expand_connectors(list(meta["tools"])))
              for k, meta in CONNECTOR_METADATA.items()}

    policy_cache: dict = {}

    def _policy_tools(policy_id):
        """will_rules.allowed_tools for a policy, fetched once per call. Agents
        in an org usually share a handful of policies."""
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
                allowed = None  # unreadable policy narrows nothing; the
                                # advertised list is still the ceiling
            policy_cache[policy_id] = allowed
        return policy_cache[policy_id]

    # (advertised tools, policy_id) for every agent this member can reach.
    candidates = [(p.get("tools"), p.get("policy_id")) for p in AGENTS.values()]
    try:
        import json as _json
        for a in db.list_agents(user_id, org_id, user_role):
            raw = a.get("tools_json")
            tools = raw if isinstance(raw, list) else (_json.loads(raw or "[]") or [])
            candidates.append((tools, a.get("policy_id")))
    except Exception:
        pass  # a DB hiccup must not strip a member's existing connectors from
              # the tab; the built-ins above still answer

    usable = set()
    for advertised, policy_id in candidates:
        if len(usable) == len(wanted):
            break
        granted = set(authorized_tools(advertised, _policy_tools(policy_id)))
        for key, fns in wanted.items():
            if key not in usable and granted & fns:
                usable.add(key)
    return frozenset(usable)


def connectors_for_member(user_id, org_id=None, user_role="member") -> List[dict]:
    """The catalogue as one member sees it: org policy plus whether anything
    they can actually run would use it."""
    usable = usable_connector_keys(user_id, org_id, user_role)
    return [{**c, "usable": c["key"] in usable} for c in list_connectors_for_org(org_id)]
