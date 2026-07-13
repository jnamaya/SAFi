"""
DB tests for retention config + legal hold evidence (org_compliance_log).

Run:  venv/bin/python tests/test_retention_config.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

ACTOR = "admin@example.test"


class TestRetentionConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, 'Retention Test Org')", (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM organizations WHERE id=%s", (cls.org_id,))
        cur.execute("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    def events(self):
        return db.list_compliance_log(self.org_id, 50)

    def test_default_is_keep_forever(self):
        cfg = db.get_org_retention_config(self.org_id)
        self.assertIsNone(cfg["retention_years"])
        self.assertFalse(cfg["legal_hold"]["active"])
        self.assertTrue(cfg["valid"])

    def test_set_and_clear_retention_logs_evidence(self):
        cfg = db.set_org_retention_config(self.org_id, {"retention_years": 6}, ACTOR)
        self.assertEqual(cfg["retention_years"], 6)
        ev = self.events()
        self.assertEqual(ev[0]["event_type"], "retention_config_changed")
        self.assertEqual(ev[0]["detail"]["changed"]["retention_years"]["new"], 6)
        self.assertEqual(ev[0]["actor"], ACTOR)

        cfg = db.set_org_retention_config(self.org_id, {"retention_years": None}, ACTOR)
        self.assertIsNone(cfg["retention_years"])
        ev = self.events()
        self.assertEqual(ev[0]["detail"]["changed"]["retention_years"], {"old": 6, "new": None})

    def test_noop_change_writes_no_event(self):
        before = len(self.events())
        db.set_org_retention_config(self.org_id, {"retention_years": None}, ACTOR)
        self.assertEqual(len(self.events()), before)

    def test_validation_rejects_bad_values(self):
        for bad in (0, -1, 100, "7", 3.5, True):
            with self.assertRaises(ValueError, msg=f"accepted {bad!r}"):
                db.set_org_retention_config(self.org_id, {"retention_years": bad}, ACTOR)

    def test_legal_hold_requires_reason_and_logs(self):
        with self.assertRaises(ValueError):
            db.set_org_retention_config(self.org_id, {"legal_hold": {"active": True, "reason": " "}}, ACTOR)
        cfg = db.set_org_retention_config(
            self.org_id, {"legal_hold": {"active": True, "reason": "SEC exam #123"}}, ACTOR)
        self.assertTrue(cfg["legal_hold"]["active"])
        self.assertEqual(cfg["legal_hold"]["set_by"], ACTOR)
        self.assertEqual(self.events()[0]["event_type"], "legal_hold_set")

        cfg = db.set_org_retention_config(self.org_id, {"legal_hold": {"active": False}}, ACTOR)
        self.assertFalse(cfg["legal_hold"]["active"])
        ev = self.events()
        self.assertEqual(ev[0]["event_type"], "legal_hold_cleared")
        self.assertEqual(ev[0]["detail"]["previous_reason"], "SEC exam #123")

    def test_invalid_stored_config_flagged_on_read(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                    ('{"retention_years": "seven"}', self.org_id))
        conn.commit()
        cur.close()
        conn.close()
        cfg = db.get_org_retention_config(self.org_id)
        self.assertFalse(cfg["valid"])
        # restore
        db.set_org_retention_config(self.org_id, {"retention_years": None}, ACTOR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
