"""
Server-side session resolution — enterprise identity Phase 1
(docs/internal/DESIGN_ENTERPRISE_IDENTITY.md §3.2).

Contract:
- The cookie carries only {'sid'}; everything else is looked up per request.
- Session liveness (revoked / absolute expiry) is NEVER cached — revocation
  must take effect on the next request.
- Role/org/profile are re-read from users (60s in-process cache), so role
  changes and removals apply within a minute without waiting for re-login.
- Endpoints keep reading session['user'] / session['user_id'] unchanged: the
  resolver hydrates those keys IN MEMORY each request and sets
  session.modified = False so they are never serialized into the cookie.
  strip_session_shim (after_request) removes them again whenever an endpoint
  legitimately writes to the session (OAuth nonce/state etc.), so a fat
  cookie can never reappear. SESSION_REFRESH_EACH_REQUEST must be False or
  permanent sessions would re-serialize the shim on every response.
- Legacy fat cookies ('user' present, no 'sid') are honored until
  LEGACY_COOKIE_GRACE_UNTIL, then treated as anonymous → re-login
  (design §3.6 grace window, avoids a hard global logout at deploy).
"""
from __future__ import annotations
import json
import os
import re
import time
import threading
from datetime import datetime, timezone

from flask import request, session, g

from ..persistence import database as db

# The only endpoints a session flagged mfa_pending_enrollment may reach:
# identity introspection, TOTP enrollment itself, and logout.
_MFA_ENROLLMENT_PATHS = re.compile(
    r"^/api/(me$|me/mfa($|/)|logout$|app-config$)")

# Deploy date + 7 days; override via env if the window needs extending.
LEGACY_COOKIE_GRACE_UNTIL = datetime.fromisoformat(
    os.environ.get("SAFI_LEGACY_COOKIE_GRACE_UNTIL", "2026-07-23T00:00:00+00:00")
)

_CACHE_TTL = 60.0
_user_cache: dict = {}
_org_cfg_cache: dict = {}
_cache_lock = threading.Lock()


def invalidate_user_cache(user_id) -> None:
    with _cache_lock:
        _user_cache.pop(user_id, None)


def _cached(cache: dict, key, loader):
    now = time.monotonic()
    with _cache_lock:
        hit = cache.get(key)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]
    value = loader(key)
    with _cache_lock:
        cache[key] = (value, now)
    return value


def _fresh_user(user_id):
    return _cached(_user_cache, user_id, db.get_user_details)


def _org_identity_cfg(org_id):
    # None org still resolves (platform defaults); cache under a sentinel key.
    return _cached(_org_cfg_cache, org_id or "__none__",
                   lambda _k: db.get_org_identity_config(org_id))


def _reject(sid, row, reason):
    """Revoke (if there is something to revoke), journal, drop the cookie."""
    if row and not row.get("revoked_at"):
        db.revoke_session(sid, f"system:{reason}", reason=reason)
    session.clear()
    g.user = None


def resolve_session():
    """before_request hook. Populates g.user (+ in-memory session shim) for
    valid server-side sessions; leaves the request anonymous otherwise —
    endpoint auth guards keep returning their own 401s."""
    if not request.path.startswith("/api"):
        return

    g.user = None
    g.sid = None
    sid = session.get("sid")

    if sid:
        row = db.get_session(sid)
        if row is None or row.get("revoked_at"):
            session.clear()
            return
        if row.get("is_expired"):
            _reject(sid, row, "absolute_timeout")
            return
        cfg = _org_identity_cfg(row.get("org_id"))
        idle = row.get("idle_seconds")
        if idle is not None and idle > cfg["idle_timeout_minutes"] * 60:
            _reject(sid, row, "idle_timeout")
            return
        user = _fresh_user(row["user_id"])
        if not user:
            _reject(sid, row, "user_deleted")
            return
        if idle is not None and idle > 60:
            db.touch_session(sid)

        # Org-mandated MFA, not yet enrolled: the session exists only so the
        # user can enroll. Everything outside the allow-list stays anonymous
        # (endpoints return their own 401s) — one choke point, fail closed.
        ctx = row.get("auth_context")
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except ValueError:
                ctx = None
        if isinstance(ctx, dict) and ctx.get("mfa_pending_enrollment"):
            if not _MFA_ENROLLMENT_PATHS.match(request.path):
                return
            g.mfa_pending_enrollment = True

        shim = {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "active_profile": user.get("active_profile"),
            "role": user.get("role", "member"),
            "org_id": user.get("org_id"),
        }
        if str(user["id"]).startswith("demo_"):
            shim["is_demo"] = True
        g.user = shim
        g.sid = sid
        session["user"] = shim
        session["user_id"] = user["id"]
        session["user_email"] = user.get("email")
        session.modified = False
        return

    if "user" in session:  # legacy fat cookie (pre-Phase-1)
        if datetime.now(timezone.utc) >= LEGACY_COOKIE_GRACE_UNTIL:
            session.clear()  # grace over: anonymous → endpoints 401 → re-login
            return
        g.user = session.get("user")


def strip_session_shim(response):
    """after_request hook: if an endpoint wrote to the session (modified=True),
    remove the hydrated shim keys before Flask serializes the cookie — the
    cookie must only ever persist 'sid' (+ transient OAuth state)."""
    try:
        if session.get("sid") and session.modified:
            for k in ("user", "user_id", "user_email"):
                session.pop(k, None)
    except Exception:
        pass
    return response
