from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, Optional

_TTL_SECONDS = 60.0
_cache_entry = None
_lock = threading.Lock()


def deployment_key_map() -> Dict[str, str]:
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
    keys = {p: k for p, k in keys.items() if (k or "").strip()}
    with _lock:
        _cache_entry = (now, keys)
    return keys


def deployment_key(provider: str) -> Optional[str]:
    try:
        return deployment_key_map().get(provider)
    except Exception:
        return None


def deployment_key_providers() -> FrozenSet[str]:
    try:
        return frozenset(deployment_key_map())
    except Exception:
        return frozenset()


def resolve_provider_key(provider: str, env_key: Optional[str] = None) -> Optional[str]:
    from .org_keys import active_org_key
    try:
        return active_org_key(provider) or deployment_key(provider) or env_key
    except Exception:
        return env_key


def invalidate_deployment_keys_cache() -> None:
    global _cache_entry
    with _lock:
        _cache_entry = None
