from __future__ import annotations
import json
import os
import re
import time
import threading
from datetime import datetime, timezone

from flask import request, session, g

from ..persistence import database as db
from ..role_config import ROLE_CONFIG

_MFA_ENROLLMENT_PATHS = re.compile(
    r"^/api/(me$|me/mfa($|/)|logout$|app-config$)")

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
    return _cached(_org_cfg_cache, org_id or "__none__",
                   lambda _k: db.get_org_identity_config(org_id))


def _reject(sid, row, reason):
    if row and not row.get("revoked_at"):
        db.revoke_session(sid, f"system:{reason}", reason=reason)
    session.clear()
    g.user = None


def resolve_session():
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
            "username": user.get("username"),
            "name": user.get("name"),
            "active_profile": user.get("active_profile"),
            "role": user.get("role") or ROLE_CONFIG["default_role"],
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

    if "user" in session:
        if datetime.now(timezone.utc) >= LEGACY_COOKIE_GRACE_UNTIL:
            session.clear()
            return
        g.user = session.get("user")


def strip_session_shim(response):
    try:
        if session.get("sid") and session.modified:
            for k in ("user", "user_id", "user_email"):
                session.pop(k, None)
    except Exception:
        pass
    return response
