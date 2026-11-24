import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLASK_ENV", "development")

from safi_app.persistence import database as db


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
        self.conn.commit()
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
        self.assertIn("legal_hold_active(org_id)", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
