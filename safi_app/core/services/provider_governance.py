"""
Per-organization LLM provider allow-list — the shared keystone control for
HIPAA (BAA-covered provider chains) and EU data residency.

Contract:
- The allow-list lives in organizations.settings.provider_allowlist as a list
  of provider keys from model_routing.PROVIDER_METADATA. Absent/None means
  unrestricted. Writes go through db.set_org_provider_allowlist, which
  evidence-logs the change to org_compliance_log in the same transaction.
- Org context is established once per request/turn with activate_org(org_id);
  it is carried in a ContextVar so it survives awaits, and SAFi._submit_bg
  copies the context into background executor threads.
- Every LLM dispatch point calls assert_provider_allowed(provider). FAIL
  CLOSED: a disallowed provider raises ProviderNotAllowedError — there is
  never a silent fallback to another provider, because silent fallback to the
  default (Groq) is exactly the breach scenario this control exists to prevent.
- No active org context (unset/None) = unrestricted; the request-time model
  validation in the chat endpoints is the second net for that case.
"""
from __future__ import annotations
import time
import threading
from contextvars import ContextVar
from typing import FrozenSet, List, Optional

from .model_routing import PROVIDER_METADATA, detect_provider

_ACTIVE_ALLOWLIST: ContextVar[Optional[FrozenSet[str]]] = ContextVar(
    "safi_provider_allowlist", default=None
)
# The governing org itself, carried alongside the allow-list so downstream
# persistence (trail org attribution, review-queue sampling) can resolve the
# turn's org without threading it through every call signature.
_ACTIVE_ORG: ContextVar[Optional[str]] = ContextVar("safi_active_org", default=None)

_CACHE_TTL_SECONDS = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ProviderNotAllowedError(RuntimeError):
    """Raised when a dispatch would send content to a provider the governing
    organization has not allowed. Deliberately terminal — never caught to
    reroute."""

    def __init__(self, provider: str, context: str = ""):
        self.provider = provider
        super().__init__(
            f"LLM provider '{provider}' is blocked by this organization's provider policy"
            + (f" ({context})" if context else "")
        )


def get_org_allowlist(org_id) -> Optional[FrozenSet[str]]:
    """Resolve an org's provider allow-list (60s cache). None = unrestricted.
    Unknown provider keys are dropped on read; a stored-but-empty list blocks
    every provider (fail closed) — the write path refuses to store one."""
    if not org_id:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(org_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]
    from ...persistence import database as db  # lazy: avoids import cycle at module load
    raw = db.get_org_provider_config(org_id).get("allowlist")
    allow = None if raw is None else frozenset(p for p in raw if p in PROVIDER_METADATA)
    with _cache_lock:
        _cache[org_id] = (allow, now)
    return allow


def invalidate_org(org_id) -> None:
    """Bust the cached allow-list after a write."""
    with _cache_lock:
        _cache.pop(org_id, None)


def activate_org(org_id) -> None:
    """Establish org provider governance for the current execution context."""
    _ACTIVE_ORG.set(str(org_id) if org_id else None)
    _ACTIVE_ALLOWLIST.set(get_org_allowlist(org_id))


def active_allowlist() -> Optional[FrozenSet[str]]:
    return _ACTIVE_ALLOWLIST.get()


def active_org() -> Optional[str]:
    """The org governing the current execution context. None = ungoverned."""
    return _ACTIVE_ORG.get()


def assert_provider_allowed(provider_name: str, context: str = "") -> None:
    allow = _ACTIVE_ALLOWLIST.get()
    if allow is not None and provider_name not in allow:
        raise ProviderNotAllowedError(provider_name, context)


def model_allowed(model_id: str, allowlist: Optional[FrozenSet[str]]) -> bool:
    return allowlist is None or detect_provider(model_id) in allowlist


def list_models_for_org(org_id) -> List[dict]:
    """Config.AVAILABLE_MODELS enriched with provider metadata and filtered by
    the org's allow-list. Single source of truth for every model picker."""
    from ...config import Config
    allow = get_org_allowlist(org_id)
    out = []
    for m in Config.AVAILABLE_MODELS:
        prov = detect_provider(m["id"])
        if allow is not None and prov not in allow:
            continue
        meta = PROVIDER_METADATA.get(prov, {})
        out.append({
            **m,
            "provider": prov,
            "provider_label": meta.get("label", prov),
            "baa_capable": bool(meta.get("baa_capable")),
            "eu_hostable": bool(meta.get("eu_hostable")),
        })
    return out
