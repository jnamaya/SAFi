"""
Tests for the examiner-production export API (records_api.py), via the Flask
test client with a forged admin session.

Run:  venv/bin/python tests/test_examiner_export.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db


class TestExaminerExport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"exptest_{uuid.uuid4().hex[:8]}"
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, 'Export Test Org')", (cls.org_id,))
        cur.execute("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'Exp Test', %s, 'admin')",
                    (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        conn.commit()
        cur.close()
        conn.close()
        cls.cid = db.create_conversation(cls.uid)["id"]
        cls.mid = str(uuid.uuid4())
        db.insert_turn_atomic(cls.cid, "EXPTEST what is 17a-4?", cls.mid)
        db.update_message_content(cls.mid, "EXPTEST it is the recordkeeping rule.", audit_status="complete")

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.uid)
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM organizations WHERE id=%s", (cls.org_id,))
        cur.execute("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,))
        cur.execute("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,))
        conn.commit()
        cur.close()
        conn.close()

    def client(self, role="admin", org_id=None):
        c = self.app.test_client()
        with c.session_transaction() as sess:
            sess["user"] = {"id": self.uid, "email": f"{self.uid}@example.test",
                            "role": role, "org_id": org_id or self.org_id}
        return c

    def test_export_returns_decrypted_records_and_trail_metadata(self):
        c = self.client()
        res = c.get(f"/api/organizations/{self.org_id}/records/export?from=2026-01-01&to=2027-01-01")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        doc = json.loads(res.data)
        self.assertEqual(doc["counts"]["conversations"], 1)
        conv = doc["conversations"][0]
        contents = [m["content"] for m in conv["messages"]]
        self.assertIn("EXPTEST what is 17a-4?", contents)          # decrypted plaintext
        self.assertIn("EXPTEST it is the recordkeeping rule.", contents)
        self.assertGreater(len(conv["trail"]), 0)
        for entry in conv["trail"]:
            self.assertNotIn("state", entry)                        # snapshots omitted
            self.assertIn("entry_hash", entry)

    def test_export_logs_chain_of_custody(self):
        c = self.client()
        c.get(f"/api/organizations/{self.org_id}/records/export?from=2026-01-01&to=2027-01-01")
        events = [e for e in db.list_compliance_log(self.org_id, 20) if e["event_type"] == "examiner_export"]
        self.assertTrue(events)
        self.assertEqual(events[0]["detail"]["range"]["from"], "2026-01-01 00:00:00")

    def test_requires_valid_range(self):
        c = self.client()
        self.assertEqual(c.get(f"/api/organizations/{self.org_id}/records/export").status_code, 400)
        self.assertEqual(c.get(f"/api/organizations/{self.org_id}/records/export?from=2027-01-01&to=2026-01-01").status_code, 400)

    def test_rbac_and_org_scoping(self):
        member = self.client(role="member")
        self.assertEqual(member.get(f"/api/organizations/{self.org_id}/records/export?from=2026-01-01&to=2027-01-01").status_code, 403)
        other = self.client(org_id=str(uuid.uuid4()))
        self.assertEqual(other.get(f"/api/organizations/{self.org_id}/records/export?from=2026-01-01&to=2027-01-01").status_code, 403)

    def test_retention_endpoint_round_trip(self):
        c = self.client()
        res = c.put(f"/api/organizations/{self.org_id}/retention",
                    json={"retention_years": 6, "legal_hold": {"active": True, "reason": "exam"}})
        self.assertEqual(res.status_code, 200)
        cfg = json.loads(res.data)
        self.assertEqual(cfg["retention_years"], 6)
        self.assertTrue(cfg["legal_hold"]["active"])
        res = c.get(f"/api/organizations/{self.org_id}/compliance-log")
        events = json.loads(res.data)["events"]
        self.assertIn("legal_hold_set", [e["event_type"] for e in events])
        # invalid value rejected
        res = c.put(f"/api/organizations/{self.org_id}/retention", json={"retention_years": 0})
        self.assertEqual(res.status_code, 400)
        # cleanup: clear hold
        c.put(f"/api/organizations/{self.org_id}/retention", json={"legal_hold": {"active": False}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
