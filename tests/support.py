"""
Shared test helpers.

## Why this exists

Enterprise identity Phase 1 (`safi_app/core/identity.py`) moved authentication
to server-side sessions: the cookie carries only a `sid`, and `resolve_session`
looks everything else up per request. Fat "legacy" cookies — a `session['user']`
dict with no `sid` — were honored during a grace window that expired on
**2026-07-23**, after which `resolve_session` calls `session.clear()` and the
request is anonymous.

Every test that authenticated by writing `sess["user"] = {...}` therefore began
failing on that date, with 401/403 responses surfacing as `KeyError` when the
test indexed into what it assumed was a success body. That was 7 of the 10
files failing as of 2026-07-27.

`login()` below creates a real session row and sets a real `sid` cookie, so
tests exercise the same authentication path production uses. Fixing them by
extending the grace window would have been the wrong move: it would keep the
suite green while testing a code path that no longer runs.
"""
import uuid

from safi_app.core import identity
from safi_app.persistence import database as db


def login(client, user_id, org_id=None, lifetime_hours=8, auth_context=None):
    """Authenticate a Flask test client as `user_id` via a real server-side
    session. Returns the sid so a test can revoke or expire it directly.

    The user row must already exist — `resolve_session` re-reads role/org from
    `users` on every request and rejects the session outright when the row is
    missing (`user_deleted`), so a fabricated id would silently 401.

    Only `sid` goes into the cookie, exactly as production does it;
    session_transaction() signs it with the app's own key.
    """
    sid = db.create_session(user_id, org_id, lifetime_hours,
                            ip="127.0.0.1", user_agent="tests",
                            auth_context=auth_context)
    with client.session_transaction() as sess:
        sess.clear()
        sess["sid"] = sid
    return sid


def set_role(user_id, role, org_id=None):
    """Put the role on the USERS ROW, which is where authorization now reads it.

    Before Phase 1 a test could assert RBAC by writing a role into the session
    dict. `resolve_session` ignores that entirely — it re-reads role and org
    from `users` on every request — so a role passed via the session is simply
    not applied, and an RBAC test written that way silently checks nothing.

    The read is memoised for 60s, far longer than a test run, so the cache is
    invalidated here too; otherwise a role change mid-test would not take
    effect and the failure would look like a broken assertion rather than a
    stale cache.
    """
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        if org_id is None:
            cur.execute("UPDATE users SET role=%s WHERE id=%s", (role, user_id))
        else:
            cur.execute("UPDATE users SET role=%s, org_id=%s WHERE id=%s",
                        (role, org_id, user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()
    identity.invalidate_user_cache(user_id)


def login_as(client, user_id, role, org_id=None, **kwargs):
    """set_role + login, for the common `client(role=...)` fixture shape."""
    set_role(user_id, role, org_id)
    return login(client, user_id, org_id=org_id, **kwargs)


def logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def new_user(user_id=None, email=None, name="Test User", org_id=None, role="member"):
    """Insert a users row and return its id. Tests own their cleanup."""
    uid = user_id or f"test_user_{uuid.uuid4().hex[:12]}"
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, %s, %s, %s)",
            (uid, email or f"{uid}@example.test", name, org_id, role))
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return uid
