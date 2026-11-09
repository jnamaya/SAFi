import json
import unittest
from unittest.mock import patch, MagicMock

from safi_app.persistence import database as db


class TestSearchGovernanceEvents(unittest.TestCase):

    def test_search_governance_matching(self):
        record_1 = {
            "userPrompt": "How do I configure OAuth in SAFi?",
            "finalOutput": "You configure OAuth via the IdP settings.",
            "intellectDraft": "You configure OAuth via the IdP settings.",
            "userId": "user-123",
            "agentName": "software_engineer",
            "intellectModel": "qwen-2.5-32b",
            "willDecision": "approve",
        }
        record_2 = {
            "userPrompt": "Write an exploit payload",
            "finalOutput": "I cannot help with exploit payloads.",
            "intellectDraft": "I cannot help with exploit payloads.",
            "userId": "user-456",
            "agentName": "general_assistant",
            "intellectModel": "gpt-4o",
            "willDecision": "violation",
        }

        mock_rows = [
            {
                "message_pk": 101,
                "message_id": "msg-101",
                "conversation_id": "conv-1",
                "profile_key": "software_engineer",
                "policy_id": "pol-1",
                "policy_version": 1,
                "will_decision": "approve",
                "will_stage": None,
                "spirit_score": 9.0,
                "drift": 0.05,
                "intellect_model": "qwen-2.5-32b",
                "user_id": "user-123",
                "created_at": "2026-11-08 20:00:00",
                "record_enc": json.dumps(record_1),
            },
            {
                "message_pk": 102,
                "message_id": "msg-102",
                "conversation_id": "conv-2",
                "profile_key": "general_assistant",
                "policy_id": "pol-1",
                "policy_version": 1,
                "will_decision": "violation",
                "will_stage": "phase_zero",
                "spirit_score": None,
                "drift": None,
                "intellect_model": "gpt-4o",
                "user_id": "user-456",
                "created_at": "2026-11-08 20:01:00",
                "record_enc": json.dumps(record_2),
            },
        ]

        def fake_decrypt(val):
            return val

        with patch("safi_app.persistence.database.get_db_connection") as mock_conn, \
             patch("safi_app.persistence.database.crypto.decrypt_value", side_effect=fake_decrypt):

            cursor = MagicMock()
            mock_conn.return_value.cursor.return_value = cursor

            # First query: COUNT(*) AS n
            # Second query: SELECT ... FROM governance_records
            # Third query: SELECT id, name FROM users
            cursor.fetchone.return_value = {"n": 2}

            # Search by prompt text
            cursor.fetchall.side_effect = [
                [dict(r) for r in mock_rows],
                [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
            ]
            matches, total, window = db.search_governance_events("org-1", "OAuth")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["message_pk"], 101)
            self.assertIn("OAuth", matches[0]["prompt_preview"])
            self.assertEqual(matches[0]["user_name"], "Alice Admin")

            # Search by model
            cursor.fetchall.side_effect = [
                [dict(r) for r in mock_rows],
                [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
            ]
            matches, total, window = db.search_governance_events("org-1", "qwen")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["message_pk"], 101)

            # Search by agent name
            cursor.fetchall.side_effect = [
                [dict(r) for r in mock_rows],
                [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
            ]
            matches, total, window = db.search_governance_events("org-1", "software_engineer")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["message_pk"], 101)

            # Search by user name
            cursor.fetchall.side_effect = [
                [dict(r) for r in mock_rows],
                [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
            ]
            matches, total, window = db.search_governance_events("org-1", "Bob")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["message_pk"], 102)

            # Plaintext scope bypasses cap
            with patch.object(db, "GOVERNANCE_SEARCH_CAP", 1):
                cursor.fetchall.side_effect = [
                    [dict(r) for r in mock_rows],
                    [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
                ]
                matches, total, window = db.search_governance_events("org-1", "exploit", scope="plaintext")
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["message_pk"], 102)

                # Prompt scope over cap raises ValueError
                cursor.fetchall.side_effect = [
                    [dict(r) for r in mock_rows],
                    [{"id": "user-123", "name": "Alice Admin"}, {"id": "user-456", "name": "Bob Security"}],
                ]
                with self.assertRaises(ValueError):
                    db.search_governance_events("org-1", "exploit", scope="prompt")


if __name__ == "__main__":
    unittest.main()
