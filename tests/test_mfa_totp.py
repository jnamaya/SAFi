"""
E2E tests for TOTP MFA (enterprise identity Phase 2): stdlib TOTP module,
enrollment lifecycle, login challenge, org-mandated enrollment gate, and the
auth_events journal.

Run:  SAFI_LOCAL_ADMIN_EMAIL=mfa-test@test.local SAFI_LOCAL_ADMIN_PASSWORD=x \
      venv/bin/python tests/test_mfa_totp.py
(The env vars are set below if absent — the local-login endpoints 404 without them.)
"""
import base64
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EMAIL = "mfa-e2e-test@test.local"
PASSWORD = "e2e-Test-Password-1"
os.environ.setdefault("SAFI_LOCAL_ADMIN_EMAIL", EMAIL)
os.environ.setdefault("SAFI_LOCAL_ADMIN_PASSWORD", PASSWORD)

from safi_app import create_app
from safi_app.core import totp as totp_lib
from safi_app.core import identity as identity_mod
from safi_app.persistence import database as db


def live_code(secret):
    return totp_lib._code_at(secret, int(time.time() // 30))


class TestTotpModule(unittest.TestCase):
    """RFC 6238 Appendix B vectors (SHA1, 6 digits)."""

    SECRET = base64.b32encode(b"12345678901234567890").decode()

    def test_rfc6238_vectors(self):
        for t, expected in [(59, "287082"), (1111111109, "081804"),
                            (1234567890, "005924"), (2000000000, "279037")]:
            self.assertEqual(totp_lib._code_at(self.SECRET, t // 30), expected)
            self.assertTrue(totp_lib.verify_code(self.SECRET, expected, at_time=t))

    def test_skew_window_and_rejects(self):
        self.assertTrue(totp_lib.verify_code(self.SECRET, "287082", at_time=59 + 29))
        self.assertFalse(totp_lib.verify_code(self.SECRET, "000000", at_time=59))
        self.assertFalse(totp_lib.verify_code(self.SECRET, "28708", at_time=59))
        self.assertFalse(totp_lib.verify_code(self.SECRET, "abcdef", at_time=59))
        self.assertFalse(totp_lib.verify_code("not-base32!!", "287082", at_time=59))


class TestMfaLifecycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()  # seeds the local admin from the env vars

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, org_id FROM users WHERE email=%s", (EMAIL,))
        row = cur.fetchone()
        if row:
            uid, org = row
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM users WHERE id=%s", (uid,))
            if org:
                cur.execute("DELETE FROM organizations WHERE id=%s AND name='MFA E2E Org'", (org,))
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def _journal_counts(uid):
        """auth_events is append-only and survives user deletion, so counts
        must be read as deltas against a baseline, not absolutes."""
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT event, COUNT(*) FROM auth_events WHERE user_id=%s "
                    "AND event IN ('mfa_enrolled','mfa_failed','mfa_disabled') GROUP BY event", (uid,))
        counts = dict(cur.fetchall())
        cur.close()
        conn.close()
        return counts

    def test_full_lifecycle(self):
        c = self.app.test_client()

        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (EMAIL,))
        uid = cur.fetchone()[0]
        cur.close()
        conn.close()
        baseline = self._journal_counts(uid)

        # Plain password login while unenrolled
        r = c.post("/api/login/local", json={"email": EMAIL, "password": PASSWORD})
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True))

        j = c.get("/api/me/mfa").get_json()
        self.assertTrue(j["local_account"])
        self.assertFalse(j["totp_enabled"])

        # Enrollment: wrong code rejected, right code enables
        j = c.post("/api/me/mfa/totp/setup").get_json()
        secret = j["secret"]
        self.assertTrue(j["otpauth_uri"].startswith("otpauth://"))
        self.assertEqual(c.post("/api/me/mfa/totp/verify", json={"code": "000000"}).status_code, 401)
        r = c.post("/api/me/mfa/totp/verify", json={"code": live_code(secret)})
        self.assertTrue(r.get_json().get("totp_enabled"), r.get_data(as_text=True))

        # Login now challenges; bad code fails; good code carries amr pwd+otp
        c.post("/api/logout")
        j = c.post("/api/login/local", json={"email": EMAIL, "password": PASSWORD}).get_json()
        self.assertTrue(j.get("mfa_required"))
        token = j["mfa_token"]
        self.assertEqual(
            c.post("/api/login/local/mfa", json={"mfa_token": token, "code": "111111"}).status_code, 401)
        r = c.post("/api/login/local/mfa", json={"mfa_token": token, "code": live_code(secret)})
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True))

        me = c.get("/api/me").get_json()["user"]
        self.assertNotIn("password_hash", me)
        self.assertNotIn("totp_secret", me)

        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT s.auth_context FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE u.email=%s AND s.revoked_at IS NULL ORDER BY s.created_at DESC LIMIT 1", (EMAIL,))
        ctx = cur.fetchone()["auth_context"]
        cur.close()
        conn.close()
        ctx = json.loads(ctx) if isinstance(ctx, str) else ctx
        self.assertEqual(set(ctx["amr"]), {"pwd", "otp"})
        self.assertTrue(ctx["mfa"])

        # Org-mandated MFA: unenrolled user gets a session restricted to
        # /me + /me/mfa/* + logout until verification upgrades it in place
        org_id = db.create_organization("MFA E2E Org")
        db.update_user_org_and_role(uid, org_id, "admin")
        db.set_org_identity_config(org_id, {"require_mfa": True}, "test:e2e")
        db.disable_user_totp(uid, "test:e2e", org_id=org_id)
        identity_mod.invalidate_user_cache(uid)

        c2 = self.app.test_client()
        j = c2.post("/api/login/local", json={"email": EMAIL, "password": PASSWORD}).get_json()
        self.assertTrue(j.get("mfa_setup_required"))
        self.assertEqual(c2.get("/api/conversations").status_code, 401)
        me = c2.get("/api/me").get_json()["user"]
        self.assertTrue(me.get("mfa_setup_required"))

        secret2 = c2.post("/api/me/mfa/totp/setup").get_json()["secret"]
        r = c2.post("/api/me/mfa/totp/verify", json={"code": live_code(secret2)})
        self.assertTrue(r.get_json().get("totp_enabled"))
        self.assertEqual(c2.get("/api/conversations").status_code, 200)

        # Journal carries the lifecycle (delta vs baseline — journal is append-only)
        events = self._journal_counts(uid)
        delta = {k: events.get(k, 0) - baseline.get(k, 0)
                 for k in ("mfa_enrolled", "mfa_failed", "mfa_disabled")}
        self.assertEqual(delta["mfa_enrolled"], 2, delta)
        self.assertEqual(delta["mfa_failed"], 2, delta)
        self.assertEqual(delta["mfa_disabled"], 1, delta)

        # Self-service disable requires a live code
        self.assertEqual(c2.delete("/api/me/mfa/totp", json={"code": "999999"}).status_code, 401)
        r = c2.delete("/api/me/mfa/totp", json={"code": live_code(secret2)})
        self.assertFalse(r.get_json().get("totp_enabled"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
