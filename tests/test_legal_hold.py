"""Legal hold: destruction stops, including destruction the user asked for.

WHY. `DATA_ERASURE_AND_RETENTION.md` §4 and `HIPAA_READINESS.md` both state
that a hold "suspends all destruction". Until 2026-08-26 that was true of one
purge phase and of nothing else (GOVERNANCE_BACKLOG 2):

  * `legal_hold_active` appeared twice in scripts/retention_purge.py, the
    definition and a single call in Phase A, so a hold placed mid-run did not
    stop Phase B, B2 or C;
  * `delete_conversation` / `delete_all_conversations` never checked at all, so
    a member could clear their own conversations during an active hold. That is
    the spoliation a hold exists to prevent, and the published claim said it
    could not happen.

These tests exist because the failure is silent: a delete under hold looked
exactly like a successful delete, and the purge phases reported normal counts.

Run:  python tests/test_legal_hold.py
"""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLASK_ENV", "development")

from safi_app.persistence import database as db  # noqa: E402


class LegalHoldBlocksUserDeletion(unittest.TestCase):

    def setUp(self):
        db.init_db()
        self.conn = db.get_db_connection()
        self.cur = self.conn.cursor(dictionary=True)
        self.user_id = "hold_%s" % uuid.uuid4()
        self.org_id = db.create_organization("Hold Test %s" % self.user_id[-4:])
        db.upsert_user({
            "sub": self.user_id, "id": self.user_id,
            "email": "%s@hold.test" % self.user_id, "name": "Holder",
            "picture": "", "role": "admin", "org_id": self.org_id,
        })
        self.convo_id = str(uuid.uuid4())
        self.cur.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s,%s,%s)",
            (self.convo_id, self.user_id, "held chat"))
        self.conn.commit()

    def tearDown(self):
        for sql, args in (
            ("DELETE FROM conversations WHERE user_id=%s", (self.user_id,)),
            ("DELETE FROM users WHERE id=%s", (self.user_id,)),
            ("DELETE FROM organizations WHERE id=%s", (self.org_id,)),
        ):
            try:
                self.cur.execute(sql, args)
            except Exception:
                pass
        self.conn.commit()
        self.cur.close()
        self.conn.close()

    def _set_hold(self, active):
        db.set_org_retention_config(
            self.org_id,
            {"legal_hold": {"active": active, "reason": "unit test" if active else ""}},
            actor="test",
        )
        self.conn.commit()

    def _convo_exists(self):
        self.conn.commit()          # end this connection's read snapshot
        self.cur.execute("SELECT COUNT(*) n FROM conversations WHERE id=%s", (self.convo_id,))
        return self.cur.fetchone()["n"] == 1

    def test_a_single_delete_is_refused_under_hold(self):
        self._set_hold(True)
        with self.assertRaises(db.LegalHoldActive):
            db.delete_conversation(self.convo_id, user_id=self.user_id)
        self.assertTrue(self._convo_exists(), "the conversation was destroyed under a hold")

    def test_clear_all_is_refused_under_hold(self):
        self._set_hold(True)
        with self.assertRaises(db.LegalHoldActive):
            db.delete_all_conversations(self.user_id)
        self.assertTrue(self._convo_exists(), "clear-all destroyed content under a hold")

    def test_deletion_works_again_once_the_hold_is_lifted(self):
        """The guard must not become a permanent block. A hold that cannot be
        lifted is its own kind of defect."""
        self._set_hold(True)
        with self.assertRaises(db.LegalHoldActive):
            db.delete_conversation(self.convo_id, user_id=self.user_id)
        self._set_hold(False)
        db.delete_conversation(self.convo_id, user_id=self.user_id)
        self.assertFalse(self._convo_exists(), "delete should succeed once the hold is lifted")

    def test_no_hold_means_no_interference(self):
        self.assertFalse(db.get_org_retention_config(self.org_id)["legal_hold"]["active"])
        db.delete_conversation(self.convo_id, user_id=self.user_id)
        self.assertFalse(self._convo_exists())


class EveryPurgePhaseRechecksTheHold(unittest.TestCase):
    """Source-level, deliberately.

    Driving four purge phases to a mid-run hold needs a populated multi-org
    database and a scheduler; the regression this guards against is simply
    someone adding a delete loop that forgets to ask. Reading the source
    catches that, and catches it in the file where the mistake would be made.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent
                   / "scripts" / "retention_purge.py").read_text(encoding="utf-8")

    def test_the_shared_guard_exists(self):
        self.assertIn("def hold_stopped(", self.src,
                      "the phases should share one guard, not each roll their own")

    def test_every_deleting_phase_asks(self):
        for fn, phase in (("def purge_trail_chains", "Phase B"),
                          ("def purge_governance_orphans", "Phase B2"),
                          ("def purge_aged_table", "Phase C")):
            start = self.src.index(fn)
            end = self.src.index("\ndef ", start + 1)
            body = self.src[start:end]
            with self.subTest(phase=phase):
                self.assertIn("hold_stopped(", body,
                              f"{phase} deletes in a loop without re-checking the hold")

    def test_phase_a_still_checks(self):
        """It always did. This fails if a refactor drops it."""
        self.assertIn("legal_hold_active(org_id)", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
