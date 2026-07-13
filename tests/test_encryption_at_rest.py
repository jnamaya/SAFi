"""
DB-backed lifecycle test for encryption at rest.

Verifies that a full chat turn stores ciphertext in chat_history AND in the
chat_audit_trail state (no plaintext at rest), that every read path returns
plaintext, that the read-modify-write reasoning log works over ciphertext,
that the hash chain stays valid, and that legacy plaintext rows dual-read.

Requires the local MySQL instance (throwaway user/conversation, cleaned up).
Skips (exits 0 with a notice) if SAFI_ENCRYPTION_KEY is not set.

Run:  venv/bin/python tests/test_encryption_at_rest.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.persistence import crypto

PROMPT = "ENCTEST what is the capital of France?"
ANSWER = "ENCTEST the capital of France is Paris."


@unittest.skipUnless(crypto.is_enabled(), "SAFI_ENCRYPTION_KEY not set — encryption disabled")
class TestEncryptionAtRest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.uid = f"enctest_{uuid.uuid4().hex[:8]}"
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, email, name) VALUES (%s, %s, %s)",
                    (cls.uid, f"{cls.uid}@example.test", "Enc Test"))
        conn.commit()
        cur.close()
        conn.close()
        cls.cid = db.create_conversation(cls.uid)["id"]
        cls.msg_id = str(uuid.uuid4())

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.uid)
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,))
        cur.execute("DELETE FROM prompt_usage WHERE user_id=%s", (cls.uid,))
        conn.commit()
        cur.close()
        conn.close()

    def raw(self, sql, params):
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    def test_lifecycle(self):
        # 1. Turn insert: prompt is ciphertext in the DB and in the trail
        self.assertTrue(db.insert_turn_atomic(self.cid, PROMPT, self.msg_id))
        rows = self.raw("SELECT id, role, content FROM chat_history WHERE conversation_id=%s ORDER BY id", (self.cid,))
        user_row, ai_row = rows[0], rows[1]
        self.assertTrue(crypto.is_token(user_row["content"]))
        trail = self.raw("SELECT state FROM chat_audit_trail WHERE message_pk=%s", (user_row["id"],))
        self.assertNotIn(PROMPT, trail[0]["state"])

        # 2. Reasoning RMW twice over ciphertext
        db.update_message_reasoning(self.msg_id, "Analyzing your request...")
        db.update_message_reasoning(self.msg_id, "Drafting a response...", phase="gather")

        # 3. Content + audit results stored encrypted
        db.update_message_content(self.msg_id, ANSWER, audit_status="complete")
        db.update_audit_results(self.msg_id, [{"value": "truth", "score": 1}], 9,
                                "ENCTEST aligned note", "test", ["truth"], None)
        raw_ai = self.raw("SELECT content, spirit_note, conscience_ledger, reasoning_log "
                          "FROM chat_history WHERE message_id=%s", (self.msg_id,))[0]
        for col in ("content", "spirit_note", "conscience_ledger", "reasoning_log"):
            self.assertTrue(crypto.is_token(raw_ai[col]), f"{col} not encrypted at rest")

        # 4. No plaintext anywhere in this message's trail
        trail = self.raw("SELECT state FROM chat_audit_trail WHERE message_pk=%s ORDER BY id", (ai_row["id"],))
        joined = " ".join(t["state"] or "" for t in trail)
        self.assertNotIn("ENCTEST", joined)

        # 5. Read paths return plaintext
        hist = db.fetch_chat_history_for_conversation(self.cid, user_id=self.uid)
        self.assertEqual(hist[0]["content"], PROMPT)
        self.assertEqual(hist[1]["content"], ANSWER)
        audit = db.get_audit_result(self.msg_id)
        self.assertEqual(audit["spirit_note"], "ENCTEST aligned note")
        self.assertEqual(json.loads(audit["ledger"])[0]["value"], "truth")
        self.assertEqual(len(json.loads(audit["reasoning_log"])), 2)

        # 6. Hash chain valid over ciphertext states
        self.assertTrue(db.verify_message_audit_trail(ai_row["id"])["valid"])
        self.assertTrue(db.verify_message_audit_trail(user_row["id"])["valid"])

        # 7. Saved content: copy stays ciphertext at rest, reads back plaintext
        saved = db.save_content(self.uid, self.msg_id)
        self.assertIsNotNone(saved)
        raw_saved = self.raw("SELECT content, title FROM saved_content WHERE id=%s", (saved["id"],))[0]
        self.assertTrue(crypto.is_token(raw_saved["content"]))
        self.assertIn("capital of France", raw_saved["title"])  # title derived from plaintext
        fetched = db.fetch_saved_content(self.uid)
        self.assertEqual(fetched[0]["content"], ANSWER)

        # 8. Summary / profile / agent-context round-trips, ciphertext at rest
        db.update_conversation_summary(self.cid, "ENCTEST summary")
        self.assertEqual(db.fetch_conversation_summary(self.cid), "ENCTEST summary")
        db.upsert_user_profile_memory(self.uid, '{"tone": "ENCTEST"}')
        self.assertEqual(json.loads(db.fetch_user_profile_memory(self.uid))["tone"], "ENCTEST")
        db.upsert_agent_context_memory(self.uid, "agent-1", '{"notes": "ENCTEST"}')
        self.assertEqual(json.loads(db.fetch_agent_context_memory(self.uid, "agent-1"))["notes"], "ENCTEST")
        for table, col, where, param in [
            ("conversations", "memory_summary", "id", self.cid),
            ("user_profiles", "profile_json", "user_id", self.uid),
            ("agent_context_memory", "context_json", "user_id", self.uid),
        ]:
            v = self.raw(f"SELECT {col} AS v FROM {table} WHERE {where}=%s", (param,))[0]["v"]
            self.assertTrue(crypto.is_token(v), f"{table}.{col} not encrypted at rest")

        # 9. OAuth tokens encrypted at rest, transparent read
        db.upsert_oauth_token(self.uid, "github", "gho_secret_token", "refresh_xyz", None, "repo")
        raw_tok = self.raw("SELECT access_token, refresh_token FROM oauth_tokens "
                           "WHERE user_id=%s AND provider='github'", (self.uid,))[0]
        self.assertTrue(crypto.is_token(raw_tok["access_token"]))
        self.assertTrue(crypto.is_token(raw_tok["refresh_token"]))
        tok = db.get_oauth_token(self.uid, "github")
        self.assertEqual(tok["access_token"], "gho_secret_token")
        self.assertEqual(tok["refresh_token"], "refresh_xyz")

        # 10. Legacy plaintext row dual-reads
        conn = db.get_db_connection()
        cur = conn.cursor()
        legacy_mid = str(uuid.uuid4())
        cur.execute("INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) "
                    "VALUES (%s, 'ai', 'legacy plaintext answer', %s, 'complete')", (self.cid, legacy_mid))
        conn.commit()
        cur.close()
        conn.close()
        hist = db.fetch_chat_history_for_conversation(self.cid, user_id=self.uid)
        self.assertEqual(hist[-1]["content"], "legacy plaintext answer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
