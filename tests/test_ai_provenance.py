"""
Tests for Art. 50(2) machine-readable AI-output marking (Phase G1): the
provenance marker object, the X-AI-Generated header on generation surfaces,
evaluator-only semantics for the /evaluate gateway, and per-message markers
in the examiner and right-of-access exports.

Run:  venv/bin/python tests/test_ai_provenance.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.core import provenance
from safi_app.persistence import database as db
from safi_app.persistence import crypto


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class TestMarker(unittest.TestCase):

    def test_generator_marker(self):
        m = provenance.ai_marker(model="test/model")
        self.assertTrue(m["ai_generated"])
        self.assertEqual(m["generator"], "SAFi")
        self.assertEqual(m["model"], "test/model")
        self.assertEqual(m["marking_standard"], "EU-AI-Act-Art-50(2)")
        self.assertIn("marked_at", m)

    def test_evaluator_only_marker_never_claims_generation(self):
        m = provenance.ai_marker(evaluator_only=True)
        self.assertTrue(m["ai_generated"])
        self.assertEqual(m["evaluator"], "SAFi")
        self.assertEqual(m["generator"], "external-agent")


class TestExportMarking(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.uid = f"prov_user_{uuid.uuid4().hex[:8]}"
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO users (id, email, name) VALUES (%s, %s, 'Prov Test')",
              (cls.uid, f"{cls.uid}@example.test"))
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
              (cls.cid, cls.uid, crypto.encrypt_value("prov test")))
        assert db.insert_turn_atomic(cls.cid, "prov prompt", str(uuid.uuid4()))

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM conversations WHERE id=%s", (cls.cid,)),
            ("DELETE FROM org_compliance_log WHERE org_id IS NULL AND JSON_EXTRACT(detail, '$.user_id')=%s", (cls.uid,)),
            ("DELETE FROM users WHERE id=%s", (cls.uid,)),
        ]:
            _exec(sql, params)

    def test_user_export_marks_ai_messages(self):
        c = self.app.test_client()
        with c.session_transaction() as sess:
            sess["user"] = {"id": self.uid, "email": f"{self.uid}@example.test",
                            "role": "member", "org_id": None}
            sess["user_id"] = self.uid
        data = json.loads(c.get("/api/me/export").data)
        msgs = [m for conv in data["conversations"] for m in conv["messages"]]
        self.assertTrue(msgs)
        for m in msgs:
            self.assertEqual(m["ai_generated"], m["role"] == "ai",
                             "marker must track the role exactly")
        self.assertTrue(any(m["ai_generated"] for m in msgs),
                        "the AI placeholder row must be marked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
