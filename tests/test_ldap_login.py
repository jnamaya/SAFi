"""
E2E tests for LDAP/AD sign-in (Phase 1): /api/login/ldap two-step flow.

The directory itself is mocked (core/ldap_client.authenticate is patched),
because the point under test is SAFi's own logic: email reconciliation, the
org ldap_enabled gate, the TOTP chain when require_mfa is on, and
first-login restricted enrollment sessions.

Run:  venv/bin/python tests/test_ldap_login.py
"""
import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.config import Config
from safi_app.core import totp as totp_lib
from safi_app.core import ldap_client
from safi_app.persistence import database as db

EMAIL = f"ldap-e2e-{uuid.uuid4().hex[:8]}@test.local"
PASSWORD = "ad-Test-Password-1"
DN = f"CN=ldap-e2e,OU=Users,DC=test,DC=local"


def live_code(secret):
    return totp_lib._code_at(secret, int(time.time() // 30))


class TestLdapLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Global LDAP config present (Config.ldap_configured()), org opts in.
        cls._saved = (Config.LDAP_URL, Config.LDAP_BASE_DN)
        Config.LDAP_URL = "ldap://dc01.test.local"
        Config.LDAP_BASE_DN = "DC=test,DC=local"
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        Config.LDAP_URL, Config.LDAP_BASE_DN = cls._saved

    def setUp(self):
        self.client = self.app.test_client()
        org_id = db.create_organization(f"LDAP E2E Org {uuid.uuid4().hex[:6]}")
        self.org_id = org_id
        # upsert_user requires a caller-supplied id ('sub'/'id' key) — same
        # pattern as tests/test_mfa_totp.py.
        self.user_id = f"ldap_e2e_{uuid.uuid4().hex[:12]}"
        db.upsert_user({"id": self.user_id, "email": EMAIL, "name": "LDAP E2E",
                        "picture": None, "org_id": org_id})
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # No delete_organization helper exists; raw SQL, keyed on the ids this
        # test created (same pattern as tests/test_mfa_totp.py teardown).
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (self.user_id,))
            cur.execute("DELETE FROM users WHERE id=%s", (self.user_id,))
            cur.execute("DELETE FROM organizations WHERE id=%s", (self.org_id,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _bind_ok(self, email=EMAIL):
        return lambda username, password: (
            {"ok": True, "dn": DN, "email": email, "name": "LDAP E2E"}
            if password == PASSWORD else
            {"ok": False, "code": "invalid_credentials", "message": "Invalid credentials."})

    # -- gate / reconciliation ------------------------------------------------

    def test_404_when_not_configured(self):
        saved = Config.LDAP_URL
        Config.LDAP_URL = ""
        try:
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": "y"})
            self.assertEqual(r.status_code, 404)
        finally:
            Config.LDAP_URL = saved

    def test_rejects_bad_bind(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = lambda u, p: {"ok": False, "code": "invalid_credentials",
                                                 "message": "Invalid credentials."}
        try:
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": "wrong"})
            self.assertEqual(r.status_code, 401)
        finally:
            ldap_client.authenticate = orig

    def test_rejects_when_org_has_not_enabled_ldap(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = self._bind_ok()
        try:
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": PASSWORD})
            self.assertEqual(r.status_code, 403)
        finally:
            ldap_client.authenticate = orig

    def test_rejects_unmatched_email(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = self._bind_ok(email="nobody@nowhere.local")
        try:
            db.set_org_identity_config(self.org_id, {"ldap_enabled": True}, "test:e2e")
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": PASSWORD})
            self.assertEqual(r.status_code, 403)
        finally:
            ldap_client.authenticate = orig

    # -- session / MFA paths --------------------------------------------------

    def test_plain_login_no_mfa_required(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = self._bind_ok()
        try:
            db.set_org_identity_config(self.org_id, {"ldap_enabled": True}, "test:e2e")
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": PASSWORD})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.get_json().get("ok"))
            me = self.client.get("/api/me")
            self.assertTrue(me.get_json().get("ok"))
        finally:
            ldap_client.authenticate = orig

    def test_totp_enrolled_yields_mfa_pending(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = self._bind_ok()
        try:
            db.set_org_identity_config(self.org_id, {"ldap_enabled": True, "require_mfa": True}, "test:e2e")
            secret = totp_lib.generate_secret()
            db.set_user_totp_pending(self.user_id, secret)
            db.enable_user_totp(self.user_id, "test:e2e")

            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": PASSWORD})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertFalse(data.get("ok"))
            self.assertTrue(data.get("mfa_required"))
            self.assertIn("mfa_token", data)

            # No session before the second factor.
            self.assertFalse(self.client.get("/api/me").get_json().get("ok"))

            # Wrong code rejected...
            r2 = self.client.post("/api/login/ldap/mfa",
                                  json={"mfa_token": data["mfa_token"], "code": "000000"})
            self.assertEqual(r2.status_code, 401)
            # ...right code establishes the session.
            r3 = self.client.post("/api/login/ldap/mfa",
                                  json={"mfa_token": data["mfa_token"], "code": live_code(secret)})
            self.assertEqual(r3.status_code, 200)
            self.assertTrue(r3.get_json().get("ok"))
            self.assertTrue(self.client.get("/api/me").get_json().get("ok"))
        finally:
            ldap_client.authenticate = orig

    def test_require_mfa_without_totp_gives_enrollment_session(self):
        orig = ldap_client.authenticate
        ldap_client.authenticate = self._bind_ok()
        try:
            db.set_org_identity_config(self.org_id, {"ldap_enabled": True, "require_mfa": True}, "test:e2e")
            r = self.client.post("/api/login/ldap", json={"identifier": "TEST\\x", "password": PASSWORD})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("mfa_setup_required"))
            # Restricted session: /me works, app endpoints do not.
            me = self.client.get("/api/me").get_json()
            self.assertTrue(me.get("ok"))
            self.assertTrue(me.get("user", {}).get("mfa_setup_required"))
            blocked = self.client.get("/api/conversations")
            self.assertIn(blocked.status_code, (401, 403))
        finally:
            ldap_client.authenticate = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
