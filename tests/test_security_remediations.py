"""
P1/P2/P3 remediation regression tests: login oracle collapse, internal-key
auth on /api/public/process_prompt (warn vs enforce), 8 KB message cap,
UUID conversation-id check, per-minute throttle.

Requires no database — requests are rejected (or logged in warn mode) before
any DB/LLM work. Run:
    venv/bin/python tests/test_security_remediations.py
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.api import keys as keys_mod


VALID_KEY = "test-internal-key-abc123"


def setUpModule():
    os.environ.setdefault("FLASK_ENV", "development")
    os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
    os.environ["SAFI_INTERNAL_KEYS"] = VALID_KEY
    # Re-resolve config attributes that were frozen at first import.
    from safi_app.config import Config
    Config.SAFI_INTERNAL_KEYS = [VALID_KEY]


class AppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safi_app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def _post_public(self, convo_id, message="hi", headers=None):
        with self.app.test_client() as c:
            return c.post("/api/public/process_prompt",
                          headers=headers or {},
                          data=json.dumps({"conversation_id": convo_id,
                                           "message": message}),
                          content_type="application/json")


class InternalKeyBehavior(AppCase):
    def setUp(self):
        keys_mod.clear_rate_state()
        from safi_app.config import Config
        self._orig = Config.SAFI_ENFORCE_INTERNAL_KEY

    def tearDown(self):
        from safi_app.config import Config
        Config.SAFI_ENFORCE_INTERNAL_KEY = self._orig
        keys_mod.clear_rate_state()

    # BAD_ID keeps the request below the throttle but failing validation with
    # 400, so no test ever needs a database or model backend.
    BAD_ID = "wp_" + "a" * 32  # right length, not a UUID

    def test_01_warn_mode_serves_without_key(self):
        from safi_app.config import Config
        Config.SAFI_ENFORCE_INTERNAL_KEY = False
        r = self._post_public(self.BAD_ID)
        self.assertNotEqual(r.status_code, 401,
                            "warn mode must not 401 (migration window)")

    def test_02_enforce_mode_rejects_without_key(self):
        from safi_app.config import Config
        Config.SAFI_ENFORCE_INTERNAL_KEY = True
        r = self._post_public("11111111-1111-1111-1111-111111111111")
        self.assertEqual(r.status_code, 401,
                         "no key must be 401, not 200/429/400")

    def test_03_enforce_mode_rejects_wrong_key(self):
        from safi_app.config import Config
        Config.SAFI_ENFORCE_INTERNAL_KEY = True
        r = self._post_public("11111111-1111-1111-1111-111111111111",
                              headers={"X-Internal-Key": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_04_enforce_mode_allows_valid_key(self):
        from safi_app.config import Config
        Config.SAFI_ENFORCE_INTERNAL_KEY = True
        with patch.object(db, "ensure_conversation_access"), \
             patch.object(db, "upsert_user"), \
             patch.object(db, "record_prompt_usage"):
            r = self._post_public("11111111-1111-1111-1111-111111111111",
                                  headers={"X-Internal-Key": VALID_KEY})
        self.assertNotEqual(r.status_code, 401)


class MessageAndIdValidation(AppCase):
    def setUp(self):
        keys_mod.clear_rate_state()

    def test_05_non_uuid_conversation_id_rejected(self):
        r = self._post_public("wp_" + "a" * 32)  # 35 chars, not a UUID
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get("code"), "CONVERSATION_ID_INVALID")

    def test_06_over_8kb_message_rejected_with_413(self):
        r = self._post_public("11111111-1111-1111-1111-111111111111",
                              message="x" * 9000)
        self.assertEqual(r.status_code, 413,
                         f"8 KB+ payload must be 413, got {r.status_code}")


class PerMinuteThrottle(AppCase):
    def setUp(self):
        keys_mod.clear_rate_state()

    def test_07_eleventh_request_in_a_minute_is_429(self):
        ok, throttled = 0, 0
        with patch.object(db, "ensure_conversation_access"), \
             patch.object(db, "upsert_user"), \
             patch.object(db, "record_prompt_usage"):
            for _ in range(11):
                r = self._post_public(
                    "11111111-1111-1111-1111-111111111111")
                if r.status_code == 429:
                    throttled += 1
                else:
                    ok += 1
        self.assertEqual(throttled, 1,
                         "exactly one of 11 rapid requests should be 429")
        self.assertEqual(ok, 10)


class LoginOracleCollapsed(AppCase):
    def _login(self, body):
        with self.app.test_client() as c:
            return c.post("/api/login/local", data=json.dumps(body),
                          content_type="application/json")

    def test_08_missing_fields_and_unknown_user_are_identical(self):
        keys_mod.clear_rate_state()
        a = self._login({})
        keys_mod.clear_rate_state()
        with patch.object(db, "get_user_by_identifier", return_value=None):
            b = self._login({"identifier": "ghost@example.com",
                             "password": "whatever"})
        self.assertEqual(a.status_code, 401)
        self.assertEqual(b.status_code, 401)
        self.assertEqual(a.get_data(), b.get_data(),
                         "missing-fields and unknown-user responses must be "
                         "byte-identical (no enumeration oracle)")

    def test_09_rapid_failures_hit_the_throttle(self):
        keys_mod.clear_rate_state()
        saw_429 = False
        with patch.object(db, "get_user_by_identifier", return_value=None):
            for _ in range(12):
                r = self._login({"identifier": "ghost@example.com",
                                 "password": "nope"})
                if r.status_code == 429:
                    saw_429 = True
                    break
        self.assertTrue(saw_429, "12 rapid bad logins must produce a 429")


if __name__ == "__main__":
    unittest.main(verbosity=2)
