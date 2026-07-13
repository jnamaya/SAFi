"""
DB integration tests for scripts/retention_purge.py.

Seeds a synthetic org with backdated conversations/messages/trail entries via
raw SQL and runs the purge phases against it. Uses --force semantics (a tiny
org always trips the blast-radius guard by percentage).

Run:  venv/bin/python tests/test_retention_purge.py
"""
import argparse
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from safi_app.persistence import database as db
import retention_purge as rp

ACTOR = "admin@example.test"
OLD = "2018-01-15 10:00:00"      # far outside any retention period
RECENT_TRAIL = None               # entries created now


def args(**kw):
    base = dict(dry_run=False, org=None, batch_size=50, max_batches=None,
                force=True, purge_unattributed=False, older_than_years=0)
    base.update(kw)
    return argparse.Namespace(**base)


class TestRetentionPurge(unittest.TestCase):

    def setUp(self):
        self.org_id = str(uuid.uuid4())
        self.uid = f"purgetest_{uuid.uuid4().hex[:8]}"
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, 'Purge Test Org')", (self.org_id,))
        cur.execute("INSERT INTO users (id, email, name, org_id) VALUES (%s, %s, 'Purge Test', %s)",
                    (self.uid, f"{self.uid}@example.test", self.org_id))
        conn.commit()
        cur.close()
        conn.close()
        db.set_org_retention_config(self.org_id, {"retention_years": 5}, ACTOR)
        self.conn = rp.get_conn()

    def tearDown(self):
        self.conn.close()
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (self.uid,))
        cur.execute("DELETE FROM organizations WHERE id=%s", (self.org_id,))
        cur.execute("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org_id,))
        cur.execute("DELETE FROM chat_audit_trail WHERE org_id=%s", (self.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    # --- seeding helpers -------------------------------------------------

    def raw(self, sql, params=()):
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.with_rows else []
        conn.commit()
        cur.close()
        conn.close()
        return rows

    def seed_conversation(self, message_ts=OLD, conv_created=OLD, n_messages=2,
                          backdate_trail=True):
        """A conversation with messages+trail, backdated as requested."""
        cid = db.create_conversation(self.uid)["id"]
        for i in range(n_messages):
            mid = str(uuid.uuid4())
            db.insert_turn_atomic(cid, f"prompt {i}", mid)
            db.update_message_content(mid, f"answer {i}", audit_status="complete")
        self.raw("UPDATE conversations SET created_at=%s WHERE id=%s", (conv_created, cid))
        if message_ts:
            self.raw("UPDATE chat_history SET timestamp=%s WHERE conversation_id=%s", (message_ts, cid))
        if backdate_trail:
            self.raw("UPDATE chat_audit_trail SET created_at=%s WHERE conversation_id=%s", (OLD, cid))
        return cid

    def org_row(self):
        return {"id": self.org_id, "name": "Purge Test Org", "settings": None}

    def counts(self, cid):
        conv = self.raw("SELECT COUNT(*) c FROM conversations WHERE id=%s", (cid,))[0]["c"]
        msgs = self.raw("SELECT COUNT(*) c FROM chat_history WHERE conversation_id=%s", (cid,))[0]["c"]
        trail = self.raw("SELECT COUNT(*) c FROM chat_audit_trail WHERE conversation_id=%s", (cid,))[0]["c"]
        return conv, msgs, trail

    def last_event(self, event_type):
        rows = [e for e in db.list_compliance_log(self.org_id, 50) if e["event_type"] == event_type]
        return rows[0] if rows else None

    # --- tests ------------------------------------------------------------

    def test_old_conversation_purged_with_trail_and_evidence(self):
        cid = self.seed_conversation()
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid), (0, 0, 0))
        ev = self.last_event("purge_completed")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["detail"]["counts"]["conversations"], 1)
        self.assertEqual(ev["detail"]["counts"]["chat_history"], 4)  # 2 turns = 4 rows
        self.assertGreater(ev["detail"]["counts"]["chat_audit_trail_chains"], 0)
        self.assertIsNotNone(self.last_event("purge_started"))

    def test_recent_chain_in_old_conversation_survives(self):
        cid = self.seed_conversation()
        # A message deleted RECENTLY: its trail chain (created now, not backdated)
        # is inside its own retention window and must survive the purge.
        mid = str(uuid.uuid4())
        db.insert_turn_atomic(cid, "late prompt", mid)
        self.raw("UPDATE chat_history SET timestamp=%s WHERE conversation_id=%s", (OLD, cid))
        rp.purge_org(self.conn, self.org_row(), args())
        conv, msgs, trail = self.counts(cid)
        self.assertEqual((conv, msgs), (0, 0))
        self.assertGreater(trail, 0, "recent trail chain must survive")
        ev = self.last_event("purge_completed")
        self.assertGreater(ev["detail"]["skipped"]["trail_chains_in_window"], 0)

    def test_active_conversation_kept(self):
        cid = self.seed_conversation(message_ts=None, conv_created=OLD, backdate_trail=False)
        rp.purge_org(self.conn, self.org_row(), args())
        conv, msgs, _ = self.counts(cid)
        self.assertEqual(conv, 1)
        self.assertEqual(msgs, 4)

    def test_empty_old_conversation_purged(self):
        cid = db.create_conversation(self.uid)["id"]
        self.raw("UPDATE conversations SET created_at=%s WHERE id=%s", (OLD, cid))
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid)[0], 0)

    def test_legal_hold_blocks_everything(self):
        cid = self.seed_conversation()
        db.set_org_retention_config(self.org_id, {"legal_hold": {"active": True, "reason": "exam"}}, ACTOR)
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid)[0], 1)
        self.assertIsNone(self.last_event("purge_started"))

    def test_keep_forever_org_untouched(self):
        db.set_org_retention_config(self.org_id, {"retention_years": None}, ACTOR)
        cid = self.seed_conversation()
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid)[0], 1)

    def test_dry_run_writes_nothing(self):
        cid = self.seed_conversation()
        before = len(db.list_compliance_log(self.org_id, 50))
        rp.purge_org(self.conn, self.org_row(), args(dry_run=True))
        self.assertEqual(self.counts(cid)[0], 1)
        self.assertEqual(len(db.list_compliance_log(self.org_id, 50)), before)

    def test_blast_radius_guard_refuses_without_force(self):
        self.seed_conversation()
        with self.assertRaises(SystemExit) as ctx:
            rp.purge_org(self.conn, self.org_row(), args(force=False))
        self.assertEqual(ctx.exception.code, 2)

    def test_idempotent_rerun(self):
        cid = self.seed_conversation()
        rp.purge_org(self.conn, self.org_row(), args())
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid), (0, 0, 0))
        # second run logs zero-count completion
        evs = [e for e in db.list_compliance_log(self.org_id, 50) if e["event_type"] == "purge_completed"]
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["detail"]["counts"]["conversations"], 0)

    def test_saved_content_purged_by_age(self):
        cid = self.seed_conversation(message_ts=None, backdate_trail=False)  # keep conversation alive
        mid = self.raw("SELECT message_id FROM chat_history WHERE conversation_id=%s AND role='ai' LIMIT 1", (cid,))[0]["message_id"]
        saved = db.save_content(self.uid, mid)
        self.raw("UPDATE saved_content SET created_at=%s WHERE id=%s", (OLD, saved["id"]))
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.raw("SELECT COUNT(*) c FROM saved_content WHERE id=%s", (saved["id"],))[0]["c"], 0)
        self.assertEqual(self.counts(cid)[0], 1, "live conversation must survive")

    def test_invalid_config_skipped_and_logged(self):
        self.raw("UPDATE organizations SET settings=%s WHERE id=%s",
                 ('{"retention_years": "five"}', self.org_id))
        cid = self.seed_conversation()
        rp.purge_org(self.conn, self.org_row(), args())
        self.assertEqual(self.counts(cid)[0], 1)
        self.assertIsNotNone(self.last_event("purge_failed"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
