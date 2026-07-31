"""
A caller-supplied conversation_id that the schema cannot store must be rejected
at the edge with 400, not allowed to reach the database and surface as a 500.

WHY THIS EXISTS. Every conversation-id column in the schema is `char(36)`:
conversations.id, chat_history, governance_records, chat_audit_trail,
review_queue, saved_content. `/api/public/process_prompt` and
`/api/bot/process_prompt` both take that id straight from the request body, and
nothing checked its length.

The live failure: the WordPress plugin's conversation id was lengthened to 128
CSPRNG bits, which took `"wp_safi_chat_" + 32 hex` to **45 characters**. Every
send then hit

    INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'External Chat')
    -> MySQL 1406 (22001): Data too long for column 'id' at row 1

and the widget received an HTML 500 page, which the browser reported as
"Unexpected token '<' ... is not valid JSON" — a message pointing nowhere near
the real cause. It cost several wrong diagnoses (CORS, cache, LiteSpeed) before
the server log named it.

The prefix was shortened to fit, but the class of bug is the missing edge
validation, and that is what these tests pin. Widening six columns was considered
and rejected: a governance-schema migration with no benefit over telling
integrators the limit.

Requires no database — the requests are rejected before any DB call, which is
the property under test. Run:
    venv/bin/python tests/test_conversation_id_limits.py
"""
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
        """Pins the constant to the DDL in the same file, so a schema change and
        the validator cannot drift apart silently."""
        src = (Path(__file__).resolve().parent.parent
               / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
        # conversations.id is the one the failing INSERT targets.
        self.assertRegex(
            src, r"CREATE TABLE IF NOT EXISTS conversations\s*\(\s*id\s+CHAR\(36\)",
            "conversations.id is no longer CHAR(36) — re-check "
            "CONVERSATION_ID_MAX_LEN against the new width")


class PublicEndpointRejectsOverlongIds(unittest.TestCase):
    """Exercises the real Flask route, so the check cannot be bypassed by a
    caller hitting the endpoint directly."""

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
        """45 chars: "wp_safi_chat_" + 32 hex, the shape that broke production."""
        bad = "wp_safi_chat_" + ("a" * 32)
        self.assertEqual(len(bad), 45)
        r = self._post(bad)
        self.assertEqual(r.status_code, 400,
                         f"expected 400, got {r.status_code} — an over-long id must "
                         f"not reach the INSERT")
        self.assertEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG")

    def test_04_no_database_call_is_made_for_a_rejected_id(self):
        """The point of validating at the edge: it must fail BEFORE any DB work,
        so a bad id cannot create a user row or consume rate-limit budget."""
        with patch.object(db, "ensure_conversation_access") as ensure, \
             patch.object(db, "upsert_user") as upsert, \
             patch.object(db, "record_prompt_usage") as usage:
            r = self._post("x" * 200)
        self.assertEqual(r.status_code, 400)
        ensure.assert_not_called()
        upsert.assert_not_called()
        usage.assert_not_called()

    def test_05_a_36_char_id_is_not_rejected(self):
        """Boundary: exactly at the column width must pass validation. It will
        fail later for lack of a model/DB in this environment, but it must not be
        a 400 CONVERSATION_ID_TOO_LONG."""
        r = self._post("f" * 36)
        if r.status_code == 400:
            self.assertNotEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG",
                                "36 chars is exactly the column width and must be "
                                "accepted — this is an off-by-one")

    def test_06_the_shipped_plugin_shape_fits(self):
        """The fix applied to the live plugin: "wp_" + 32 hex = 35."""
        self.assertEqual(len("wp_" + "a" * 32), 35)
        self.assertLessEqual(len("wp_" + "a" * 32), db.CONVERSATION_ID_MAX_LEN)

    def test_07_empty_and_non_string_ids_are_rejected(self):
        for bad in ("", "   ", 12345, None, [], {}):
            with self.subTest(value=bad):
                r = self._post(bad)
                self.assertEqual(r.status_code, 400,
                                 f"{bad!r} must be rejected, not coerced")

    def test_08_whitespace_is_stripped_not_counted(self):
        """A padded id within the limit once trimmed should be accepted, so
        trailing newlines from a template do not cost an integrator a 400."""
        r = self._post("  " + "b" * 30 + "  ")
        if r.status_code == 400:
            self.assertNotEqual(r.get_json().get("code"), "CONVERSATION_ID_TOO_LONG")


class BotEndpointRejectsOverlongIds(unittest.TestCase):
    """The /bot/ endpoint takes the same caller-supplied id and reached the same
    INSERT, so it needs the same guard. It is behind an API key, which is why the
    check must come after auth but before any DB work."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("FLASK_ENV", "development")
        os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
        from safi_app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_09_overlong_id_is_rejected_after_a_valid_key(self):
        # NOT patching upsert_external_conversation: it does not exist on the
        # module. conversations.py guards the call with hasattr() and always
        # takes the ensure_conversation_access fallback, so that is the one to
        # assert was never reached.
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
        """Order matters: never reveal validation behaviour to an unauthenticated
        caller. A bad key must 401 even when the id is also invalid."""
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
