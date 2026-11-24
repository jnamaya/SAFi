import uuid

from safi_app.core import identity
from safi_app.persistence import database as db


def login(client, user_id, org_id=None, lifetime_hours=8, auth_context=None):
    sid = db.create_session(user_id, org_id, lifetime_hours,
                            ip="127.0.0.1", user_agent="tests",
                            auth_context=auth_context)
    with client.session_transaction() as sess:
        sess.clear()
        sess["sid"] = sid
    return sid


def set_role(user_id, role, org_id=None):
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
    set_role(user_id, role, org_id)
    return login(client, user_id, org_id=org_id, **kwargs)


def logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def new_user(user_id=None, email=None, name="Test User", org_id=None, role="member"):
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
