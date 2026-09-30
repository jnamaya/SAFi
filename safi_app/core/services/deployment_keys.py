"""
Deployment-wide provider API keys: the layer *underneath* .env.

The layering, most specific first:

    org key (org_provider_keys)  >  deployment key (here)  >  .env key

.env stays the shipped default so a fresh install needs no database row. This
table is what makes that default manageable from the UI on an appliance: an
appliance has no organization, so the org-scoped key endpoints were
unreachable and the only way to add a cloud provider was to edit .env over
SSH. With a deployment key stored here, the Model Catalog's provider list
(which is built from *configured* providers) gains the provider, and calls
dispatch against it.

Mirrors org_keys.py deliberately: same 60s per-worker cache, same failure posture
(on a DB error the last known map is kept, so a readable stored key does not
silently fall back to .env), keys never logged.

An org key still wins, and resolve_provider_key() is the single place that
precedence is expressed, so the faculty path and the background-task path cannot
disagree about which key a call is billed to.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, Optional

_TTL_SECONDS = 60.0
# A singleton, not per-org like org_keys: one (fetched_at, keys) entry rather
# than a dict keyed by org.
_cache_entry = None  # (fetched_at_monotonic, {provider: plaintext_key})
_lock = threading.Lock()


def deployment_key_map() -> Dict[str, str]:
    """The deployment's decrypted provider->key map, cached for 60s. Empty when
    nothing is stored, or when the DB is unreachable on a cold start."""
    global _cache_entry
    now = time.monotonic()
    with _lock:
        hit = _cache_entry
    if hit and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        from ...persistence import database as db
        keys = db.get_deployment_provider_keys_decrypted()
    except Exception as e:
        logging.warning(f"Deployment provider keys unavailable: {e}")
        keys = hit[1] if hit else {}
    with _lock:
        _cache_entry = (now, keys)
    return keys


def deployment_key(provider: str) -> Optional[str]:
    """The deployment's own key for this provider, or None to fall through to the
    .env default. Never raises."""
    try:
        return deployment_key_map().get(provider)
    except Exception:
        return None


def deployment_key_providers() -> FrozenSet[str]:
    """Providers the deployment holds its own key for — extends the effective
    configured-provider set in the model catalog."""
    try:
        return frozenset(deployment_key_map())
    except Exception:
        return frozenset()


def resolve_provider_key(provider: str, env_key: Optional[str] = None) -> Optional[str]:
    """The key a call should use for this provider: active org key, else
    deployment key, else .env key.

    `env_key` is passed in rather than read from Config so this module stays
    importable during Config class construction.
    """
    from .org_keys import active_org_key
    try:
        return active_org_key(provider) or deployment_key(provider) or env_key
    except Exception:
        return env_key


def invalidate_deployment_keys_cache() -> None:
    """Same-worker freshness after a set/remove; other gunicorn workers converge
    within the TTL."""
    global _cache_entry
    with _lock:
        _cache_entry = None
