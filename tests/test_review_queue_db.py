"""
DB integration tests for the review queue (Phase E1): set_org_review_config
evidence logging, and the transactional sampling hook inside
update_audit_results (enqueue, will-provenance columns, trail org stamp,
no-enqueue when disabled or ungoverned).

Run:  venv/bin/python tests/test_review_queue_db.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import provider_governance

ACTOR = "reviewer-admin@example.test"


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _fetchone(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


class ReviewQueueDbTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.user_id = f"review-test-user-{uuid.uuid4()}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Review Test Org')", (cls.org_id,))
        _exec("INSERT INTO users (id, email, name) VALUES (%s, %s, 'Review Test')",
              (cls.user_id, f"{cls.user_id}@example.test"))

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE rq FROM review_queue rq WHERE rq.org_id=%s", (cls.org_id,)),
            ("DELETE FROM chat_audit_trail WHERE org_id=%s OR conversation_id IN "
             "(SELECT id FROM conversations WHERE user_id=%s)", (cls.org_id, cls.user_id)),
            ("DELETE FROM conversations WHERE user_id=%s", (cls.user_id,)),
            ("DELETE FROM users WHERE id=%s", (cls.user_id,)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)
        provider_governance.activate_org(None)

    def _make_turn(self):
        """Insert a conversation + turn (user row / AI placeholder) and return
        (conversation_id, message_id)."""
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'review test')",
              (cid, self.user_id))
        self.assertTrue(db.insert_turn_atomic(cid, "test prompt", mid))
        return cid, mid

    def _queue_row(self, mid):
        return _fetchone("SELECT * FROM review_queue WHERE message_id=%s", (mid,))

    def _commit_turn(self, mid, score=9, drift=0.1, will_decision="approve", will_stage=None):
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], score,
                                "test note", "test_agent", ["honesty"],
                                drift=drift, policy_id="pol-1", policy_version=1,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision=will_decision, will_stage=will_stage)

    def test_01_config_set_is_evidence_logged(self):
        cfg = db.set_org_review_config(self.org_id, {"enabled": True, "random_sample_pct": 0}, ACTOR)
        self.assertTrue(cfg["enabled"])
        ev = db.list_compliance_log(self.org_id, 5)[0]
        self.assertEqual(ev["event_type"], "review_config_changed")
        self.assertEqual(ev["actor"], ACTOR)
        self.assertFalse(ev["detail"]["old"]["enabled"])
        self.assertTrue(ev["detail"]["new"]["enabled"])

    def test_02_noop_config_change_logs_nothing(self):
        before = len(db.list_compliance_log(self.org_id, 50))
        db.set_org_review_config(self.org_id, {"enabled": True}, ACTOR)  # already true
        self.assertEqual(len(db.list_compliance_log(self.org_id, 50)), before)

    def test_03_low_alignment_turn_enqueues_with_provenance(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, score=3, will_decision="approve", will_stage="spirit")
        row = self._queue_row(mid)
        self.assertIsNotNone(row, "low-alignment turn should be enqueued")
        self.assertEqual(row["org_id"], self.org_id)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(json.loads(row["triggers"]), ["low_alignment"])
        detail = json.loads(row["trigger_detail"])
        self.assertEqual(detail["spirit_score"], 3)
        self.assertEqual(detail["will_decision"], "approve")
        # will provenance landed on chat_history
        ch = _fetchone("SELECT will_decision, will_stage FROM chat_history WHERE message_id=%s", (mid,))
        self.assertEqual(ch["will_decision"], "approve")
        self.assertEqual(ch["will_stage"], "spirit")
        # trail 'update' entry carries the org stamp and the chain verifies
        tr = _fetchone("SELECT org_id, message_pk FROM chat_audit_trail "
                       "WHERE message_id=%s AND action='update' ORDER BY id DESC LIMIT 1", (mid,))
        self.assertEqual(tr["org_id"], self.org_id)
        self.assertTrue(db.verify_message_audit_trail(tr["message_pk"])["valid"])

    def test_04_clean_turn_not_enqueued(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, score=9, drift=0.05)
        self.assertIsNone(self._queue_row(mid))

    def test_05_hard_gate_redirect_enqueues(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, score=None, drift=None,
                          will_decision="redirected", will_stage="hard_gate")
        row = self._queue_row(mid)
        self.assertIsNotNone(row)
        self.assertIn("hard_gate_block", json.loads(row["triggers"]))

    def test_06_ungoverned_turn_never_enqueued(self):
        provider_governance.activate_org(None)
        cid, mid = self._make_turn()
        self._commit_turn(mid, score=1, will_stage="spirit")
        self.assertIsNone(self._queue_row(mid))

    def test_07_disabled_org_never_enqueued(self):
        db.set_org_review_config(self.org_id, {"enabled": False}, ACTOR)
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, score=1, will_stage="spirit")
        self.assertIsNone(self._queue_row(mid))
        db.set_org_review_config(self.org_id, {"enabled": True}, ACTOR)

    def test_08_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            db.set_org_review_config(self.org_id, {"random_sample_pct": 200}, ACTOR)
        with self.assertRaises(ValueError):
            db.set_org_review_config(str(uuid.uuid4()), {"enabled": True}, ACTOR)  # unknown org


if __name__ == "__main__":
    unittest.main(verbosity=2)
