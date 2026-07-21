"""
DB integration tests for governance_records (native Audit Hub, N1): the
encrypted per-turn capture written inside update_audit_results' transaction.

Covers: atomic write with plaintext filter dimensions, encryption at rest,
ON DUPLICATE refresh, write-failure isolation (turn commit unaffected),
no-record when the caller passes none, and FK cascade on conversation purge.

Run:  venv/bin/python tests/test_governance_records.py
"""
import json
import sys
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.persistence import crypto
from safi_app.core.services import provider_governance


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


def _record(mid, **overrides):
    base = {
        "timestamp": "2026-07-21T00:00:00+00:00",
        "t": 7,
        "userPrompt": "what is our fiduciary duty?",
        "intellectDraft": "draft text",
        "intellectReflection": "reflection",
        "finalOutput": "final text",
        "willDecision": "approve",
        "willReason": "clean_pass",
        "conscienceLedger": [{"value": "honesty", "score": 1}],
        "spiritScore": 9,
        "spiritNote": "aligned",
        "drift": 0.1,
        "p_t_vector": [1.0],
        "mu_t_vector": [0.9],
        "memorySummary": "",
        "recentTurns": "",
        "spiritFeedback": "",
        "retrievedContext": "ctx",
        "userId": f"gov-user-{mid[:8]}",
        "agentName": "test_agent",
        "intellectModel": "test/model-1",
    }
    base.update(overrides)
    return base


class GovernanceRecordsDbTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.user_id = f"gov-test-user-{uuid.uuid4()}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Gov Records Test Org')", (cls.org_id,))
        _exec("INSERT INTO users (id, email, name) VALUES (%s, %s, 'Gov Records Test')",
              (cls.user_id, f"{cls.user_id}@example.test"))

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM chat_audit_trail WHERE org_id=%s OR conversation_id IN "
             "(SELECT id FROM conversations WHERE user_id=%s)", (cls.org_id, cls.user_id)),
            ("DELETE FROM conversations WHERE user_id=%s", (cls.user_id,)),
            ("DELETE FROM users WHERE id=%s", (cls.user_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)
        provider_governance.activate_org(None)

    def _make_turn(self):
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'gov records test')",
              (cid, self.user_id))
        self.assertTrue(db.insert_turn_atomic(cid, "test prompt", mid))
        return cid, mid

    def _commit_turn(self, mid, record=None, score=9, drift=0.1,
                     will_decision="approve", will_stage=None):
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], score,
                                "test note", "test_agent", ["honesty"],
                                drift=drift, policy_id="pol-1", policy_version=2,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision=will_decision, will_stage=will_stage,
                                governance_record=record)

    def _gov_row(self, mid):
        return _fetchone("SELECT * FROM governance_records WHERE message_id=%s", (mid,))

    def test_01_record_written_atomically_with_dimensions(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=_record(mid), score=8, drift=0.2)
        row = self._gov_row(mid)
        self.assertIsNotNone(row, "governance record should commit with the turn")
        ch = _fetchone("SELECT id FROM chat_history WHERE message_id=%s", (mid,))
        self.assertEqual(row["message_pk"], ch["id"])
        self.assertEqual(row["conversation_id"], cid)
        self.assertEqual(row["org_id"], self.org_id)
        self.assertEqual(row["user_id"], f"gov-user-{mid[:8]}")
        self.assertEqual(row["profile_key"], "test_agent")
        self.assertEqual(row["policy_id"], "pol-1")
        self.assertEqual(row["policy_version"], 2)
        self.assertEqual(row["will_decision"], "approve")
        self.assertIsNone(row["will_stage"])
        self.assertEqual(row["spirit_score"], 8)
        self.assertAlmostEqual(row["drift"], 0.2)
        self.assertEqual(row["intellect_model"], "test/model-1")

    def test_02_record_encrypted_at_rest_and_decrypts(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=_record(mid))
        row = self._gov_row(mid)
        if crypto.is_enabled():
            self.assertTrue(crypto.is_token(row["record_enc"]),
                            "record_enc must be Fernet ciphertext at rest")
            self.assertNotIn("fiduciary", row["record_enc"])
        decoded = json.loads(crypto.decrypt_value(row["record_enc"]))
        self.assertEqual(decoded["userPrompt"], "what is our fiduciary duty?")
        self.assertEqual(decoded["conscienceLedger"], [{"value": "honesty", "score": 1}])
        self.assertEqual(decoded["willReason"], "clean_pass")

    def test_03_no_record_when_none_passed(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=None)
        self.assertIsNone(self._gov_row(mid))
        ch = _fetchone("SELECT audit_status FROM chat_history WHERE message_id=%s", (mid,))
        self.assertEqual(ch["audit_status"], "complete")

    def test_04_duplicate_commit_refreshes_single_row(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=_record(mid), score=9)
        self._commit_turn(mid, record=_record(mid, spiritScore=4), score=4,
                          will_decision="redirected", will_stage="hard_gate")
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM governance_records WHERE message_id=%s", (mid,))
        self.assertEqual(cur.fetchone()[0], 1)
        cur.close()
        conn.close()
        row = self._gov_row(mid)
        self.assertEqual(row["spirit_score"], 4)
        self.assertEqual(row["will_decision"], "redirected")
        self.assertEqual(row["will_stage"], "hard_gate")

    def test_05_record_failure_never_blocks_turn_commit(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        with patch.object(db, "_insert_governance_record", side_effect=RuntimeError("boom")):
            self._commit_turn(mid, record=_record(mid))
        self.assertIsNone(self._gov_row(mid))
        ch = _fetchone("SELECT audit_status, will_decision FROM chat_history WHERE message_id=%s", (mid,))
        self.assertEqual(ch["audit_status"], "complete")
        self.assertEqual(ch["will_decision"], "approve")

    def test_06_purging_conversation_cascades_record(self):
        provider_governance.activate_org(self.org_id)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=_record(mid))
        self.assertIsNotNone(self._gov_row(mid))
        _exec("DELETE FROM conversations WHERE id=%s", (cid,))
        self.assertIsNone(self._gov_row(mid),
                          "governance record must cascade with its chain")

    def test_07_personal_turn_without_org_still_recorded(self):
        provider_governance.activate_org(None)
        cid, mid = self._make_turn()
        self._commit_turn(mid, record=_record(mid))
        row = self._gov_row(mid)
        self.assertIsNotNone(row, "no-org turns still get an encrypted record")
        self.assertIsNone(row["org_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
