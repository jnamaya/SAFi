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

Note the two namespaces. OAuth *account* keys are google / microsoft / github —
what oauth_tokens.provider stores and what the login routes are named for. Tool
*connector* names are google_drive / sharepoint / github (tool_connectors.py).
One account serves several connectors: microsoft unlocks sharepoint. This module
governs the account, and carries the tool mapping so the admin UI can say what
allowing it actually unlocks.
"""
from __future__ import annotations

import threading
import time
from typing import FrozenSet, List, Optional

# key -> what an admin needs to know to make the decision. "tools" is the
# tool-connector namespace (tool_connectors.CONNECTOR_TOOLS), not this one.
CONNECTOR_METADATA = {
    "google": {
        "label": "Google Drive",
        "tools": ("google_drive",),
        "grants": "Read the member's Drive files and folders on their behalf.",
        "scopes": "drive.readonly, drive.file",
    },
    "microsoft": {
        "label": "Microsoft OneDrive / SharePoint",
        "tools": ("sharepoint",),
        "grants": "Read the member's OneDrive and the SharePoint sites they can already reach.",
        "scopes": "Files.Read.All, Sites.Read.All (delegated)",
    },
    "github": {
        "label": "GitHub",
        "tools": ("github",),
        "grants": "Read repositories and file contents the member can already access.",
        "scopes": "repo (read)",
    },
}

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
