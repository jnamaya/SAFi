"""Internal-key validation for public-facing endpoints.

Keys live only in server env (SAFI_INTERNAL_KEYS, comma-separated) and are
injected server-side by the Apache proxies on runsafi.com and
safi.selfalignmentframework.com — a browser must never hold one.

Enforcement is staged via SAFI_ENFORCE_INTERNAL_KEY:
  unset/0 → warn mode: a missing/invalid key is logged, request still served
            (deployment migration window, so proxies can go live first).
  1       → enforce mode: missing/invalid key → 401.
"""
import hmac
import time

from flask import current_app, request

from safi_app.config import Config

# Per-minute throttle for the public endpoint, keyed on (ip, key-present).
# Lightweight in-process sliding window — same pattern as the MFA attempt
# limiter in api/auth.py. Deliberately dependency-free (no Flask-Limiter).
_PER_MINUTE_LIMIT = 10
_PER_MINUTE_WINDOW = 60.0
_rate_buckets: dict = {}


def configured_keys():
    keys = getattr(Config, "SAFI_INTERNAL_KEYS", None) or []
    return [k for k in keys if k]


def key_ok(key: str) -> bool:
    for k in configured_keys():
        if hmac.compare_digest(key, k):
            return True
    return False


def internal_key_state():
    """Returns (ok, enforce). In warn mode ok is forced True but failures are logged."""
    key = request.headers.get("X-Internal-Key", "")
    ok = key_ok(key)
    enforce = bool(getattr(Config, "SAFI_ENFORCE_INTERNAL_KEY", False))
    if not ok:
        if enforce:
            return False, True
        current_app.logger.warning(
            "internal-key: request to a keyed endpoint without a valid "
            "X-Internal-Key (warn mode, serving anyway). Set "
            "SAFI_ENFORCE_INTERNAL_KEY=1 to enforce once all proxies inject it.")
    return True, True


def require_internal_key():
    """True if the request may proceed; False if it must be rejected 401."""
    ok, enforce = internal_key_state()
    return ok


def per_minute_allowed(bucket_key: str) -> bool:
    """Sliding-window limiter; returns False when the caller is over the cap."""
    now = time.time()
    stamps = [t for t in _rate_buckets.get(bucket_key, [])
              if now - t < _PER_MINUTE_WINDOW]
    if len(stamps) >= _PER_MINUTE_LIMIT:
        _rate_buckets[bucket_key] = stamps
        return False
    stamps.append(now)
    _rate_buckets[bucket_key] = stamps
    return True


def clear_rate_state():
    """Test hook."""
    _rate_buckets.clear()
