"""
DB-backed test for scripts/backfill_encryption.py.

Seeds legacy plaintext rows via raw SQL, runs the backfill twice, and asserts:
encrypted exactly once (idempotent), audit-trail marker entries appended once
and contain no plaintext, hash chain still valid, and reads return plaintext.

Requires local MySQL. Skips if SAFI_ENCRYPTION_KEY is not set.

Run:  venv/bin/python tests/test_encryption_backfill.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.persistence import crypto

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import backfill_encryption as bf

SECRET = "BACKFILLTEST plaintext secret"


@unittest.skipUnless(crypto.is_enabled(), "SAFI_ENCRYPTION_KEY not set — encryption disabled")
class TestBackfill(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.uid = f"bftest_{uuid.uuid4().hex[:8]}"
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, email, name) VALUES (%s, %s, %s)",
                    (cls.uid, f"{cls.uid}@example.test", "BF Test"))
        conn.commit()
        cur.close()
        conn.close()
        cls.cid = db.create_conversation(cls.uid)["id"]
        # Seed a legacy plaintext AI row + oauth token via raw SQL
        conn = db.get_db_connection()
        cur = conn.cursor()
        cls.msg_id = str(uuid.uuid4())
        cur.execute("INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) "
                    "VALUES (%s, 'ai', %s, %s, 'complete')", (cls.cid, SECRET, cls.msg_id))
        cls.row_pk = cur.lastrowid
        cur.execute("INSERT INTO oauth_tokens (user_id, provider, access_token) VALUES (%s, 'github', %s)",
                    (cls.uid, "gho_bf_plaintext"))
        conn.commit()
        cur.close()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.uid)
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,))
        conn.commit()
        cur.close()
        conn.close()

    def raw_one(self, sql, params):
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    def trail_count(self):
        row = self.raw_one("SELECT COUNT(*) AS c FROM chat_audit_trail WHERE message_pk=%s "
                           "AND actor='system:encryption-backfill'", (self.row_pk,))
        return row["c"]

    def test_backfill_idempotent(self):
        # First run encrypts
        bf.backfill_table("chat_history", ("id",),
                          ("content", "spirit_note", "conscience_ledger", "reasoning_log"),
                          True, batch_size=500)
        bf.backfill_table("oauth_tokens", ("user_id", "provider"),
                          ("access_token", "refresh_token"), False, batch_size=500)

        row = self.raw_one("SELECT content FROM chat_history WHERE id=%s", (self.row_pk,))
        self.assertTrue(crypto.is_token(row["content"]))
        self.assertEqual(crypto.decrypt_value(row["content"]), SECRET)
        tok = self.raw_one("SELECT access_token FROM oauth_tokens WHERE user_id=%s AND provider='github'",
                           (self.uid,))
        self.assertTrue(crypto.is_token(tok["access_token"]))
        self.assertEqual(self.trail_count(), 1)

        # Marker entry contains no plaintext
        marker = self.raw_one("SELECT state FROM chat_audit_trail WHERE message_pk=%s "
                              "AND actor='system:encryption-backfill'", (self.row_pk,))
        self.assertNotIn(SECRET, marker["state"])
        self.assertIn("fernet-encrypt", marker["state"])

        # Second run is a no-op
        first_ct = row["content"]
        bf.backfill_table("chat_history", ("id",),
                          ("content", "spirit_note", "conscience_ledger", "reasoning_log"),
                          True, batch_size=500)
        row2 = self.raw_one("SELECT content FROM chat_history WHERE id=%s", (self.row_pk,))
        self.assertEqual(row2["content"], first_ct)
        self.assertEqual(self.trail_count(), 1)

        # Chain valid; read path returns plaintext
        self.assertTrue(db.verify_message_audit_trail(self.row_pk)["valid"])
        hist = db.fetch_chat_history_for_conversation(self.cid, user_id=self.uid)
        self.assertEqual(hist[-1]["content"], SECRET)


if __name__ == "__main__":
    unittest.main(verbosity=2)
