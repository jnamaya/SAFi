"""
Per-org provider API keys (backlog 64): bring-your-own-key, layered over .env.

The .env keys stay the deployment default. An org may store its own key per
provider (Fernet-encrypted in org_provider_keys); at dispatch time the active
org's key, when present, replaces the deployment key for that one call.
Resolution rides the same active-org ContextVar as the provider allow-list
and usage attribution, so it covers faculty calls and background tasks alike
without threading a key through any call signature.

Failure posture: on a DB error the last known map for the org is kept, so a
readable stored key does not silently fall back to the deployment key (that
would break the billing separation the feature exists for). An org with no
stored key simply uses the deployment default — that is the .env-plus-GUI
layering, not an error. Keys are never logged.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, Optional

_TTL_SECONDS = 60.0
_cache: dict = {}  # org_id -> (fetched_at_monotonic, {provider: plaintext_key})
_lock = threading.Lock()


def org_key_map(org_id) -> Dict[str, str]:
    """The org's decrypted provider->key map, cached for 60s. Empty when the
    org has stored nothing (or there is no org context)."""
    if not org_id:
        return {}
    org_id = str(org_id)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(org_id)
    if hit and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        from ...persistence import database as db
        keys = db.get_org_provider_keys_decrypted(org_id)
    except Exception as e:
        logging.warning(f"Org provider keys unavailable for {org_id}: {e}")
        keys = hit[1] if hit else {}
    with _lock:
        _cache[org_id] = (now, keys)
    return keys


def active_org_key(provider: str) -> Optional[str]:
    """The active org's own key for this provider, or None = use the
    deployment default. Never raises."""
    try:
        from .provider_governance import active_org
        return org_key_map(active_org()).get(provider)
    except Exception:
        return None


def org_key_providers(org_id) -> FrozenSet[str]:
    """Providers this org holds its own key for — extends the effective
    configured-provider set in the model catalog."""
    return frozenset(org_key_map(org_id))


def invalidate_org_keys_cache(org_id=None) -> None:
    """Same-worker freshness after a set/remove; other gunicorn workers
    converge within the TTL."""
    with _lock:
        if org_id is None:
            _cache.clear()
        else:
            _cache.pop(str(org_id), None)
