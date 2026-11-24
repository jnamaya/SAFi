from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, Optional

_TTL_SECONDS = 60.0
_cache: dict = {}
_lock = threading.Lock()


def org_key_map(org_id) -> Dict[str, str]:
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
    keys = {p: k for p, k in keys.items() if (k or "").strip()}
    with _lock:
        _cache[org_id] = (now, keys)
    return keys


def active_org_key(provider: str) -> Optional[str]:
    try:
        from .provider_governance import active_org
        return org_key_map(active_org()).get(provider)
    except Exception:
        return None


def org_key_providers(org_id) -> FrozenSet[str]:
    return frozenset(org_key_map(org_id))


def invalidate_org_keys_cache(org_id=None) -> None:
    with _lock:
        if org_id is None:
            _cache.clear()
        else:
            _cache.pop(str(org_id), None)
