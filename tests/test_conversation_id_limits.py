import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db


class TheLimitMatchesTheSchema(unittest.TestCase):

    def test_01_constant_exists_and_is_36(self):
        self.assertEqual(db.CONVERSATION_ID_MAX_LEN, 36,
                         "the limit must match the char(36) columns; changing it "
                         "without a migration re-opens the 1406 error")

    def test_02_the_columns_really_are_that_wide(self):
        src = (Path(__file__).resolve().parent.parent
               / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
        self.assertRegex(
            src, r"CREATE TABLE IF NOT EXISTS conversations\s*\(\s*id\s+CHAR\(36\)",
            "conversations.id is no longer CHAR(36) — re-check "
            "CONVERSATION_ID_MAX_LEN against the new width")


class PublicEndpointRejectsOverlongIds(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("FLASK_ENV", "development")
        os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
        from safi_app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def _post(self, convo_id, message="hello"):
        with self.app.test_client() as c:
            return c.post("/api/public/process_prompt",
                          data=json.dumps({"conversation_id": convo_id,
                                           "message": message}),
                          content_type="application/json")

    def test_03_the_exact_failing_id_is_rejected_with_400(self):
        bad = "wp_safi_chat_" + ("a" * 32)
        self.assertEqual(len(bad), 45)
        r = self._post(bad)
        self.assertEqual(r.status_code, 400,
                         f"expected 400, got {r.status_code} — an over-long id must "
                         f"not reach the INSERT")
        self.assertEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG")

    def test_04_no_database_call_is_made_for_a_rejected_id(self):
        with patch.object(db, "ensure_conversation_access") as ensure, \
             patch.object(db, "upsert_user") as upsert, \
             patch.object(db, "record_prompt_usage") as usage:
            r = self._post("x" * 200)
        self.assertEqual(r.status_code, 400)
        ensure.assert_not_called()
        upsert.assert_not_called()
        usage.assert_not_called()

    def test_05_a_36_char_id_is_not_rejected(self):
        r = self._post("f" * 36)
        if r.status_code == 400:
            self.assertNotEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG",
                                "36 chars is exactly the column width and must be "
                                "accepted — this is an off-by-one")

    def test_06_the_shipped_plugin_shape_fits(self):
        self.assertEqual(len("wp_" + "a" * 32), 35)
        self.assertLessEqual(len("wp_" + "a" * 32), db.CONVERSATION_ID_MAX_LEN)

    def test_07_empty_and_non_string_ids_are_rejected(self):
        for bad in ("", "   ", 12345, None, [], {}):
            with self.subTest(value=bad):
                r = self._post(bad)
                self.assertEqual(r.status_code, 400,
                                 f"{bad!r} must be rejected, not coerced")

    def test_08_whitespace_is_stripped_not_counted(self):
        r = self._post("  " + "b" * 30 + "  ")
        if r.status_code == 400:
            self.assertNotEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG")


class BotEndpointRejectsOverlongIds(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("FLASK_ENV", "development")
        os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
        from safi_app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_09_overlong_id_is_rejected_after_a_valid_key(self):
        with patch.object(db, "get_policy_id_by_api_key", return_value="some_policy"), \
             patch.object(db, "ensure_conversation_access") as ensure, \
             patch.object(db, "upsert_user") as upsert:
            with self.app.test_client() as c:
                r = c.post("/api/bot/process_prompt",
                           headers={"X-API-KEY": "sk-safi-test"},
                           data=json.dumps({"user_id": "u1",
                                            "conversation_id": "wp_safi_chat_" + "a" * 32,
                                            "message": "hello"}),
                           content_type="application/json")
        self.assertEqual(r.status_code, 400,
                         f"expected 400, got {r.status_code}")
        self.assertEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG")
        ensure.assert_not_called()
        upsert.assert_not_called()

    def test_10_an_invalid_key_still_wins_over_the_length_check(self):
        with patch.object(db, "get_policy_id_by_api_key", return_value=None):
            with self.app.test_client() as c:
                r = c.post("/api/bot/process_prompt",
                           headers={"X-API-KEY": "sk-safi-bogus"},
                           data=json.dumps({"user_id": "u1",
                                            "conversation_id": "z" * 200,
                                            "message": "hello"}),
                           content_type="application/json")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
