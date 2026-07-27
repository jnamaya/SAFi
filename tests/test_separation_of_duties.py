"""
DB integration tests for the two authorization guards added 2026-07-27:

- Separation of duties: a reviewer cannot dispose of a turn from their own
  conversation (SelfReviewError). FINRA 3110/3120 supervisory review means
  someone OTHER than the principal signs off, and self-approval is the first
  thing an examiner tests.
- Last-admin protection: neither a demotion nor a removal may leave an
  organization with zero admins (LastAdminError), because such an org loses
  policy authoring, member management and the provider allow-list with no
  in-product way back.

Both guards live in the persistence layer rather than the routes, so these
tests exercise them where every caller inherits them.

Run:  venv/bin/python tests/test_separation_of_duties.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
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


class SelfReviewTest(unittest.TestCase):
    """The author of a turn must not be able to sign it off."""

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.author = f"sod-author-{uuid.uuid4()}"
        cls.other = f"sod-other-{uuid.uuid4()}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'SoD Test Org')", (cls.org_id,))
        for uid in (cls.author, cls.other):
            _exec("INSERT INTO users (id, email, name, org_id, role) "
                  "VALUES (%s, %s, 'SoD Test', %s, 'admin')",
                  (uid, f"{uid}@example.test", cls.org_id))
        db.set_org_review_config(cls.org_id, {"enabled": True, "random_sample_pct": 0},
                                 "test-setup")

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM review_queue WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM chat_audit_trail WHERE org_id=%s OR conversation_id IN "
             "(SELECT id FROM conversations WHERE user_id IN (%s,%s))",
             (cls.org_id, cls.author, cls.other)),
            ("DELETE FROM conversations WHERE user_id IN (%s,%s)", (cls.author, cls.other)),
            ("DELETE FROM users WHERE id IN (%s,%s)", (cls.author, cls.other)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)
        provider_governance.activate_org(None)

    def _queued_turn(self, owner):
        """A conversation owned by `owner` with one turn flagged into the queue."""
        provider_governance.activate_org(self.org_id)
        cid, mid = str(uuid.uuid4()), str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'sod test')",
              (cid, owner))
        self.assertTrue(db.insert_turn_atomic(cid, "test prompt", mid))
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], 3,
                                "note", "test_agent", ["honesty"],
                                drift=0.1, policy_id="pol-1", policy_version=1,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision="approve", will_stage="spirit")
        row = _fetchone("SELECT * FROM review_queue WHERE message_id=%s", (mid,))
        self.assertIsNotNone(row, "low-alignment turn should be enqueued")
        return row, cid

    def test_author_cannot_approve_own_turn(self):
        row, _ = self._queued_turn(self.author)
        with self.assertRaises(db.SelfReviewError):
            db.apply_review_action(self.org_id, row["id"], "approve", None,
                                   self.author, "author@example.test")
        after = _fetchone("SELECT status, reviewed_by FROM review_queue WHERE id=%s", (row["id"],))
        self.assertEqual(after["status"], "pending", "refused review must not change state")
        self.assertIsNone(after["reviewed_by"])

    def test_author_cannot_override_own_turn(self):
        row, _ = self._queued_turn(self.author)
        with self.assertRaises(db.SelfReviewError):
            db.apply_review_action(self.org_id, row["id"], "override", "a stated reason",
                                   self.author, "author@example.test")
        after = _fetchone("SELECT status FROM review_queue WHERE id=%s", (row["id"],))
        self.assertEqual(after["status"], "pending")

    def test_another_reviewer_can_dispose(self):
        """The guard must block only the author — not supervisory review itself."""
        row, _ = self._queued_turn(self.author)
        out = db.apply_review_action(self.org_id, row["id"], "approve", None,
                                     self.other, "other@example.test")
        self.assertEqual(out["status"], "approved")
        self.assertEqual(out["reviewed_by"], self.other)

    def test_purged_conversation_does_not_block_review(self):
        """An aged turn whose conversation is gone has no owner to compare
        against; review must still be possible or the queue would jam."""
        row, cid = self._queued_turn(self.author)
        _exec("DELETE FROM conversations WHERE id=%s", (cid,))
        out = db.apply_review_action(self.org_id, row["id"], "approve", None,
                                     self.author, "author@example.test")
        self.assertEqual(out["status"], "approved")


class LastAdminTest(unittest.TestCase):
    """An org must never be left with zero admins."""

    def setUp(self):
        self.org_id = str(uuid.uuid4())
        self.admin = f"la-admin-{uuid.uuid4()}"
        self.second = f"la-second-{uuid.uuid4()}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'LastAdmin Test Org')",
              (self.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'Sole Admin', %s, 'admin')",
              (self.admin, f"{self.admin}@example.test", self.org_id))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'Member', %s, 'member')",
              (self.second, f"{self.second}@example.test", self.org_id))

    def tearDown(self):
        for sql, params in [
            ("DELETE FROM auth_events WHERE org_id=%s", (self.org_id,)),
            ("DELETE FROM users WHERE id IN (%s,%s)", (self.admin, self.second)),
            ("DELETE FROM organizations WHERE id=%s", (self.org_id,)),
        ]:
            try:
                _exec(sql, params)
            except Exception:
                pass

    def _role(self, uid):
        return _fetchone("SELECT role, org_id FROM users WHERE id=%s", (uid,))

    def test_cannot_demote_sole_admin(self):
        with self.assertRaises(db.LastAdminError):
            db.update_member_role(self.admin, self.org_id, 'member', actor="test")
        self.assertEqual(self._role(self.admin)["role"], 'admin',
                         "refused demotion must leave the role untouched")

    def test_cannot_remove_sole_admin(self):
        """Removal strips admin as effectively as demotion, so it is guarded too."""
        with self.assertRaises(db.LastAdminError):
            db.remove_member_from_org(self.admin, self.org_id, actor="test")
        row = self._role(self.admin)
        self.assertEqual(row["role"], 'admin')
        self.assertEqual(str(row["org_id"]), self.org_id, "member must still be in the org")

    def test_demotion_allowed_once_a_second_admin_exists(self):
        db.update_member_role(self.second, self.org_id, 'admin', actor="test")
        db.update_member_role(self.admin, self.org_id, 'member', actor="test")
        self.assertEqual(self._role(self.admin)["role"], 'member')
        self.assertEqual(self._role(self.second)["role"], 'admin')

    def test_demoting_a_non_admin_is_unaffected(self):
        """The guard keys on losing the LAST admin, not on any role change."""
        db.update_member_role(self.second, self.org_id, 'auditor', actor="test")
        self.assertEqual(self._role(self.second)["role"], 'auditor')

    def test_admin_to_admin_is_not_blocked(self):
        db.update_member_role(self.admin, self.org_id, 'admin', actor="test")
        self.assertEqual(self._role(self.admin)["role"], 'admin')


if __name__ == "__main__":
    unittest.main(verbosity=2)
