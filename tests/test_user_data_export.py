"""
Tests for the right-of-access export (Phase H — GDPR Art. 15 / HIPAA
§164.524): self-scoped decrypted export via GET /api/me/export, strict user
isolation, credential material never included, custody logging (org log for
org members, global otherwise), and 401 for anonymous callers.

Requires local MySQL. Run:  venv/bin/python tests/test_user_data_export.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import crypto


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class TestUserDataExport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"rae_user_{uuid.uuid4().hex[:8]}"
        cls.other = f"rae_other_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'RAE Test Org')", (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role, password_hash) "
              "VALUES (%s, %s, 'RAE Test', %s, 'member', 'hash-should-never-leak')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        _exec("INSERT INTO users (id, email, name) VALUES (%s, %s, 'RAE Other')",
              (cls.other, f"{cls.other}@example.test"))
        # One conversation each; titles/content encrypted like production writes
        cls.cid = str(uuid.uuid4())
        cls.other_cid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
              (cls.cid, cls.uid, crypto.encrypt_value("my private RAE title")))
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
              (cls.other_cid, cls.other, crypto.encrypt_value("someone elses title")))
        assert db.insert_turn_atomic(cls.cid, "RAE prompt text", str(uuid.uuid4()))
        assert db.insert_turn_atomic(cls.other_cid, "other user prompt", str(uuid.uuid4()))
        db.upsert_user_profile_memory(cls.uid, json.dumps({"about_me": "rae profile fact"}))

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM chat_audit_trail WHERE conversation_id IN (%s, %s)", (cls.cid, cls.other_cid)),
            ("DELETE FROM conversations WHERE id IN (%s, %s)", (cls.cid, cls.other_cid)),
            ("DELETE FROM user_profiles WHERE user_id=%s", (cls.uid,)),
            ("DELETE FROM users WHERE id IN (%s, %s)", (cls.uid, cls.other)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM org_compliance_log WHERE org_id IS NULL AND JSON_EXTRACT(detail, '$.user_id')=%s", (cls.other,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)

    def client(self, uid, org_id=None):
        c = self.app.test_client()
        with c.session_transaction() as sess:
            sess["user"] = {"id": uid, "email": f"{uid}@example.test",
                            "role": "member", "org_id": org_id}
            sess["user_id"] = uid
        return c

    def test_01_anonymous_401(self):
        res = self.app.test_client().get("/api/me/export")
        self.assertEqual(res.status_code, 401)

    def test_02_export_is_self_scoped_and_decrypted(self):
        res = self.client(self.uid, self.org_id).get("/api/me/export")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        data = json.loads(res.data)
        self.assertEqual(data["user_id"], self.uid)
        titles = [c["title"] for c in data["conversations"]]
        self.assertIn("my private RAE title", titles, "title must be decrypted")
        self.assertNotIn("someone elses title", titles, "must never include another user's data")
        contents = [m["content"] for c in data["conversations"] for m in c["messages"]]
        self.assertIn("RAE prompt text", contents)
        self.assertNotIn("other user prompt", contents)
        self.assertIn("rae profile fact", data["profile_memory"] or "")

    def test_03_credentials_never_leak(self):
        res = self.client(self.uid, self.org_id).get("/api/me/export")
        raw = res.get_data(as_text=True)
        self.assertNotIn("password_hash", raw)
        self.assertNotIn("hash-should-never-leak", raw)
        self.assertNotIn("totp_secret", raw)

    def test_04_custody_logged_to_org(self):
        self.client(self.uid, self.org_id).get("/api/me/export")
        ev = db.list_compliance_log(self.org_id, 5)[0]
        self.assertEqual(ev["event_type"], "user_data_export")
        self.assertEqual(ev["detail"]["user_id"], self.uid)
        self.assertGreaterEqual(ev["detail"]["counts"]["messages"], 1)
        self.assertNotIn("conversations_content", json.dumps(ev["detail"]))

    def test_05_no_org_user_logs_globally(self):
        res = self.client(self.other, None).get("/api/me/export")
        self.assertEqual(res.status_code, 200)
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT event_type, detail FROM org_compliance_log "
                    "WHERE org_id IS NULL ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        hits = [r for r in rows
                if r["event_type"] == "user_data_export"
                and json.loads(r["detail"] if isinstance(r["detail"], str) else json.dumps(r["detail"]))["user_id"] == self.other]
        self.assertTrue(hits, "no-org export must still leave custody evidence")


if __name__ == "__main__":
    unittest.main(verbosity=2)
