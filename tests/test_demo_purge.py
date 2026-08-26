"""The demo purge: what it destroys, what it must keep, and what it counts.

WHY. Demo accounts are deleted after 24 hours. For most of the product's life
the only evidence anyone had ever used the demo was the rows the purge happened
to MISS — orphaned `auth_events` and `sessions` still naming a `demo_%` user
whose row was gone. Counting those distinct ids is how we learned the demo had
served 153 accounts in 40 days while `organizations` only ever showed the ~10
alive at that moment (GOVERNANCE_BACKLOG 82).

Evidence by accident is evidence that vanishes when someone fixes the accident,
and it already has once: `auth_events` and `sessions` both begin at exactly
2026-07-16, when those tables were added, so demo usage before that is gone.

So this file pins three things together, because any one alone is a trap:
  1. the purge destroys demo CONTENT, chat_audit_trail included;
  2. it keeps authentication evidence, with org_id nulled rather than dangling;
  3. the signup count survives the purge that deletes everything it counted.

Run:  python tests/test_demo_purge.py
"""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLASK_ENV", "development")

from safi_app.persistence import database as db  # noqa: E402


class DemoPurge(unittest.TestCase):

    def setUp(self):
        db.init_db()
        db.init_demo_usage_schema()
        self.conn = db.get_db_connection()
        self.cur = self.conn.cursor(dictionary=True)
        self.demo_id = "demo_%s" % uuid.uuid4()
        self.org_id = db.create_organization("SAFi Demo (%s)" % self.demo_id[-4:])
        db.upsert_user({
            "sub": self.demo_id, "id": self.demo_id,
            "email": "%s@demo.local" % self.demo_id, "name": "Guest",
            "picture": "", "role": "admin", "org_id": self.org_id,
        })
        # Backdate past the 24h threshold so the purge considers it expired.
        self.cur.execute(
            "UPDATE users SET created_at = NOW() - INTERVAL 48 HOUR WHERE id=%s",
            (self.demo_id,))
        self.conn.commit()

    def tearDown(self):
        for sql, args in (
            ("DELETE FROM chat_audit_trail WHERE org_id=%s", (self.org_id,)),
            ("DELETE FROM auth_events WHERE user_id=%s", (self.demo_id,)),
            ("DELETE FROM sessions WHERE user_id=%s", (self.demo_id,)),
            ("DELETE FROM conversations WHERE user_id=%s", (self.demo_id,)),
            ("DELETE FROM users WHERE id=%s", (self.demo_id,)),
            ("DELETE FROM organizations WHERE id=%s", (self.org_id,)),
        ):
            try:
                self.cur.execute(sql, args)
            except Exception:
                pass
        self.conn.commit()
        self.cur.close()
        self.conn.close()

    def _refresh(self):
        """End this connection's read snapshot.

        MySQL defaults to REPEATABLE READ, so once setUp has read anything this
        connection keeps that snapshot for its whole transaction and cannot see
        writes committed by cleanup_old_demo_users() on its own connection. The
        first run of this file failed twice for exactly that reason and looked
        like the purge doing nothing.
        """
        self.conn.commit()

    def _seed_conversation_with_trail(self):
        convo_id = str(uuid.uuid4())
        self.cur.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s,%s,%s)",
            (convo_id, self.demo_id, "demo chat"))
        self.cur.execute(
            "INSERT INTO chat_audit_trail (message_pk, message_id, conversation_id, "
            "action, actor, state, event_at, prev_hash, entry_hash, org_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (999999, str(uuid.uuid4()), convo_id, "delete", self.demo_id,
             "{}", "2026-08-25T00:00:00Z", None, "deadbeef", self.org_id))
        self.conn.commit()
        return convo_id

    def _seed_auth_evidence(self):
        self.cur.execute(
            "INSERT INTO auth_events (ts, user_id, org_id, session_id, event, detail, actor) "
            "VALUES (NOW(), %s, %s, %s, %s, %s, %s)",
            (self.demo_id, self.org_id, "sess-x", "login", "{}", "user:%s" % self.demo_id))
        self.conn.commit()

    def test_chat_audit_trail_goes_with_the_sandbox(self):
        """Nelson 2026-08-25: same ruling as governance_records. Safe because
        the trail's hash chain is scoped per message_pk, so a demo message's
        chain is independent of every other org's."""
        self._seed_conversation_with_trail()
        self.cur.execute(
            "SELECT COUNT(*) n FROM chat_audit_trail WHERE org_id=%s", (self.org_id,))
        self.assertEqual(self.cur.fetchone()["n"], 1, "seed failed")

        db.cleanup_old_demo_users()
        self._refresh()

        self.cur.execute(
            "SELECT COUNT(*) n FROM chat_audit_trail WHERE org_id=%s", (self.org_id,))
        self.assertEqual(self.cur.fetchone()["n"], 0,
                         "demo chat_audit_trail rows must not survive the purge")

    def test_trail_rows_with_no_org_id_still_go(self):
        """The reason the purge deletes the trail BY CONVERSATION as well as by
        org. org_id is nullable and was added later, so early rows carry NULL
        and the org-scoped delete cannot see them. Without the conversation
        pass they would survive forever, and a mutation test proved the org
        pass alone hides that: seeding a row WITH org_id made the trail test
        pass even with the conversation delete removed.
        """
        convo_id = str(uuid.uuid4())
        self.cur.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s,%s,%s)",
            (convo_id, self.demo_id, "demo chat"))
        self.cur.execute(
            "INSERT INTO chat_audit_trail (message_pk, message_id, conversation_id, "
            "action, actor, state, event_at, prev_hash, entry_hash, org_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)",
            (999998, str(uuid.uuid4()), convo_id, "delete", self.demo_id,
             "{}", "2026-08-25T00:00:00Z", None, "cafebabe"))
        self.conn.commit()

        db.cleanup_old_demo_users()
        self._refresh()

        self.cur.execute(
            "SELECT COUNT(*) n FROM chat_audit_trail WHERE conversation_id=%s", (convo_id,))
        self.assertEqual(self.cur.fetchone()["n"], 0,
                         "a demo trail row with a NULL org_id must still be purged")

    def test_authentication_evidence_survives_with_org_id_nulled(self):
        """auth_events records logins and MFA outcomes: security evidence about
        a person, not demo content. It outlives the sandbox, and must not be
        left pointing at an org that no longer exists."""
        self._seed_auth_evidence()
        db.cleanup_old_demo_users()
        self._refresh()

        self.cur.execute(
            "SELECT COUNT(*) n FROM auth_events WHERE user_id=%s", (self.demo_id,))
        self.assertEqual(self.cur.fetchone()["n"], 1,
                         "authentication evidence must survive the purge")
        self.cur.execute(
            "SELECT COUNT(*) n FROM auth_events WHERE org_id=%s", (self.org_id,))
        self.assertEqual(self.cur.fetchone()["n"], 0,
                         "org_id must be nulled, not left dangling")

    def test_the_purge_leaves_no_dangling_org_reference(self):
        """The failure this whole item is about: rows naming an org that no
        longer resolves. Swept across EVERY table carrying an org_id, so a new
        table added later fails here rather than silently accumulating."""
        self._seed_conversation_with_trail()
        self._seed_auth_evidence()
        db.cleanup_old_demo_users()
        self._refresh()

        self.cur.execute("SELECT DATABASE() d")
        dbn = self.cur.fetchone()["d"]
        self.cur.execute(
            "SELECT TABLE_NAME t FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND COLUMN_NAME='org_id'", (dbn,))
        offenders = []
        for row in self.cur.fetchall():
            t = row["t"]
            if t == "organizations":
                continue
            self.cur.execute(
                "SELECT COUNT(*) n FROM `%s` WHERE org_id=%%s" % t, (self.org_id,))
            n = self.cur.fetchone()["n"]
            if n:
                offenders.append("%s(%d)" % (t, n))
        self.assertEqual(offenders, [],
                         "rows still name the deleted demo org: %s" % ", ".join(offenders))

    def test_the_signup_count_outlives_everything_it_counted(self):
        """The point of the counter. Record a signup, purge away the account,
        the org and all its content, and the number must still be there."""
        # _refresh() BEFORE the query, never between execute and fetchone: the
        # commit discards a pending result set.
        self._refresh()
        self.cur.execute("SELECT accounts FROM demo_usage_daily WHERE day=CURDATE()")
        row = self.cur.fetchone()
        before = row["accounts"] if row else 0

        db.record_demo_signup()
        self._refresh()
        self.cur.execute("SELECT accounts FROM demo_usage_daily WHERE day=CURDATE()")
        self.assertEqual(self.cur.fetchone()["accounts"], before + 1)

        self._seed_conversation_with_trail()
        db.cleanup_old_demo_users()
        self._refresh()

        self.cur.execute("SELECT COUNT(*) n FROM users WHERE id=%s", (self.demo_id,))
        self.assertEqual(self.cur.fetchone()["n"], 0, "the account should be gone")
        self.cur.execute("SELECT accounts FROM demo_usage_daily WHERE day=CURDATE()")
        self.assertEqual(self.cur.fetchone()["accounts"], before + 1,
                         "the count must survive the purge that deleted what it counted")

    def test_backfill_is_idempotent(self):
        """It reconstructs history from orphaned audit rows on first run only.
        Running it again must never double-count a day."""
        self.cur.execute("SELECT day, accounts FROM demo_usage_daily ORDER BY day")
        before = {r["day"]: r["accounts"] for r in self.cur.fetchall()}
        db.init_demo_usage_schema()
        db.init_demo_usage_schema()
        self._refresh()
        self.cur.execute("SELECT day, accounts FROM demo_usage_daily ORDER BY day")
        after = {r["day"]: r["accounts"] for r in self.cur.fetchall()}
        self.assertEqual(before, after, "re-running the backfill changed the counts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
