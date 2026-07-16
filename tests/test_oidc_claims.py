"""
Tests for per-tenant OIDC claim enforcement (enterprise identity Phase 2):
org config validation, the claim gate, SSO auth_context evidence, and the
dashboard JWT expiry.

Run:  venv/bin/python tests/test_oidc_claims.py
"""
import os
import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EMAIL = "oidc-e2e-test@test.local"
PASSWORD = "e2e-Test-Password-2"
os.environ.setdefault("SAFI_LOCAL_ADMIN_EMAIL", EMAIL)
os.environ.setdefault("SAFI_LOCAL_ADMIN_PASSWORD", PASSWORD)

from safi_app import create_app
from safi_app.persistence import database as db

TID = "11111111-2222-3333-4444-555555555555"


class TestOrgClaimConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, 'OIDC Claim Test Org')",
                    (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM organizations WHERE id=%s", (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    def test_validation_and_roundtrip(self):
        cfg = db.set_org_identity_config(
            self.org_id, {"ms_tenant_id": TID.upper(), "google_hd": "Example.COM"}, "test:oidc")
        self.assertEqual(cfg["ms_tenant_id"], TID)          # normalized lowercase
        self.assertEqual(cfg["google_hd"], "example.com")

        with self.assertRaises(ValueError):
            db.set_org_identity_config(self.org_id, {"ms_tenant_id": "not-a-guid"}, "test:oidc")
        with self.assertRaises(ValueError):
            db.set_org_identity_config(self.org_id, {"google_hd": "bad domain!"}, "test:oidc")

        cfg = db.set_org_identity_config(
            self.org_id, {"ms_tenant_id": None, "google_hd": None}, "test:oidc")
        self.assertIsNone(cfg["ms_tenant_id"])
        self.assertIsNone(cfg["google_hd"])


class TestClaimGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.org_id = str(uuid.uuid4())
        cls.user = {"id": f"oidc-gate-{uuid.uuid4()}", "email": "gate@example.com",
                    "org_id": cls.org_id}
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, 'OIDC Gate Test Org')",
                    (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM organizations WHERE id=%s", (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    def gate(self, idp, claims):
        from safi_app.api.auth import _org_claim_gate
        with self.app.test_request_context():
            return _org_claim_gate(self.user, idp, claims)

    def configure(self, changes):
        db.set_org_identity_config(self.org_id, changes, "test:oidc")

    def test_unconfigured_org_passes(self):
        self.configure({"ms_tenant_id": None, "google_hd": None, "require_mfa": False})
        self.assertIsNone(self.gate("google", {"hd": "anything.com"}))
        self.assertIsNone(self.gate("microsoft", {"tid": "any-tenant"}))

    def test_google_hd_enforced(self):
        self.configure({"google_hd": "example.com", "require_mfa": False})
        self.assertIsNone(self.gate("google", {"hd": "example.com"}))
        self.assertIsNone(self.gate("google", {"hd": "EXAMPLE.com"}))
        self.assertEqual(self.gate("google", {"hd": "evil.com"}), "hd_mismatch")
        # consumer accounts carry no hd → rejected
        self.assertEqual(self.gate("google", {}), "hd_mismatch")
        self.assertEqual(self.gate("google_mobile", {"hd": "evil.com"}), "hd_mismatch")
        # a Google restriction never blocks Microsoft logins
        self.assertIsNone(self.gate("microsoft", {"tid": "whatever"}))
        self.configure({"google_hd": None})

    def test_microsoft_tid_enforced(self):
        self.configure({"ms_tenant_id": TID, "require_mfa": False})
        self.assertIsNone(self.gate("microsoft", {"tid": TID}))
        self.assertIsNone(self.gate("microsoft", {"tid": TID.upper()}))
        self.assertEqual(self.gate("microsoft", {"tid": str(uuid.uuid4())}), "tid_mismatch")
        self.assertEqual(self.gate("microsoft", {}), "tid_mismatch")
        # a Microsoft restriction never blocks Google logins
        self.assertIsNone(self.gate("google", {"hd": "whatever.com"}))
        self.configure({"ms_tenant_id": None})

    def test_microsoft_mfa_evidence(self):
        self.configure({"require_mfa": True})
        self.assertIsNone(self.gate("microsoft", {"amr": ["pwd", "mfa"]}))
        self.assertIsNone(self.gate("microsoft", {"amr": ["ngcmfa"]}))
        self.assertEqual(self.gate("microsoft", {"amr": ["pwd"]}), "mfa_evidence_missing")
        self.assertEqual(self.gate("microsoft", {}), "mfa_evidence_missing")
        # Google MFA is enforced at Workspace, attested by policy — no gate
        self.assertIsNone(self.gate("google", {"hd": "anything.com"}))
        self.configure({"require_mfa": False})

    def test_denials_are_journaled(self):
        self.configure({"ms_tenant_id": TID})
        self.gate("microsoft", {"tid": str(uuid.uuid4())})
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT detail FROM auth_events WHERE user_id=%s AND event='login_denied' "
                    "ORDER BY id DESC LIMIT 1", (self.user["id"],))
        row = cur.fetchone()
        cur.close()
        conn.close()
        self.assertIsNotNone(row)
        self.assertIn("tid_mismatch", str(row["detail"]))
        self.configure({"ms_tenant_id": None})

    def test_sso_evidence_shape(self):
        from safi_app.api.auth import _sso_evidence
        ev = _sso_evidence("microsoft", {"iss": "https://login/x", "tid": TID,
                                         "amr": ["pwd", "mfa"], "auth_time": 123})
        self.assertEqual(ev["tid"], TID)
        self.assertTrue(ev["mfa"])
        self.assertEqual(ev["amr"], ["pwd", "mfa"])
        ev = _sso_evidence("google", {"hd": "example.com"})
        self.assertEqual(ev["hd"], "example.com")
        self.assertIsNone(ev["mfa"])  # no amr → unknown, not false


class TestDashboardTokenExpiry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()  # seeds local admin (role admin)

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (EMAIL,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (row[0],))
            cur.execute("DELETE FROM users WHERE id=%s", (row[0],))
        conn.commit()
        cur.close()
        conn.close()

    def test_token_expires(self):
        import jwt as pyjwt
        from safi_app.config import Config
        c = self.app.test_client()
        r = c.post("/api/login/local", json={"email": EMAIL, "password": PASSWORD})
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True))
        r = c.post("/api/auth/dashboard-token")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        token = r.get_json()["token"]
        payload = pyjwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        self.assertIn("exp", payload)
        remaining = payload["exp"] - time.time()
        self.assertTrue(0 < remaining <= 15 * 60 + 5, f"remaining={remaining}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
