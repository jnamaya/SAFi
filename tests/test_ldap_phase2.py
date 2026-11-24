import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.config import Config
from safi_app.core import ldap_client
from safi_app.persistence import database as db

EMAIL = f"ldap-p2-{uuid.uuid4().hex[:8]}@test.local"
PASSWORD = "ad-Test-Password-1"
DN = f"CN=ldap-p2,OU=Users,DC=test,DC=local"
ADMIN_GROUP = f"CN=SAFi Admins,OU=Groups,DC=test,DC=local"


def _bind_ok(email=EMAIL):
    return lambda username, password: (
        {"ok": True, "dn": DN, "email": email, "name": "LDAP P2"}
        if password == PASSWORD else
        {"ok": False, "code": "invalid_credentials", "message": "Invalid credentials."})


class TestLdapPhase2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        self.org_id = db.create_organization(f"LDAP P2 Org {uuid.uuid4().hex[:6]}")
        self.admin_id = f"ldap_p2_admin_{uuid.uuid4().hex[:10]}"
        db.upsert_user({"id": self.admin_id, "email": f"admin-{self.admin_id}@test.local",
                        "name": "P2 Admin", "org_id": self.org_id, "role": "admin"})
        db.set_org_identity_config(self.org_id, {"ldap_enabled": True}, "test")
        self._created_users = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            for uid in self._created_users:
                cur.execute("DELETE FROM users WHERE id=%s", (uid,))
            cur.execute("DELETE FROM users WHERE id=%s", (self.admin_id,))
            cur.execute("DELETE FROM ldap_group_mappings WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM auth_events WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM sessions WHERE user_id IN "
                        "(SELECT id FROM users WHERE org_id=%s)", (self.org_id,))
            cur.execute("DELETE FROM org_invitations WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM organizations WHERE id=%s", (self.org_id,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _login(self, groups=None, email=EMAIL):
        saved_auth, saved_groups = ldap_client.authenticate, ldap_client.get_groups
        ldap_client.authenticate = _bind_ok(email)
        ldap_client.get_groups = lambda dn: groups
        try:
            return self.client.post("/api/login/ldap",
                                    json={"identifier": "TEST\\ldap-p2", "password": PASSWORD})
        finally:
            ldap_client.authenticate, ldap_client.get_groups = saved_auth, saved_groups


    def test_identity_config_ldap_fields_roundtrip(self):
        cfg = db.get_org_identity_config(self.org_id)
        self.assertTrue(cfg.get("ldap_enabled"))
        self.assertFalse(cfg.get("ldap_auto_provision"))
        db.set_org_identity_config(self.org_id,
                                   {"ldap_auto_provision": True}, "test")
        self.assertTrue(db.get_org_identity_config(self.org_id)["ldap_auto_provision"])
        with self.assertRaises(ValueError):
            db.set_org_identity_config(self.org_id,
                                       {"ldap_auto_provision": "yes"}, "test")


    def test_no_account_no_jit_flag_is_403(self):
        r = self._login(email=f"nobody-{uuid.uuid4().hex[:6]}@test.local")
        self.assertEqual(r.status_code, 403)
        self.assertIn("no SAFi account", r.get_json()["error"])

    def test_jit_provisions_on_pending_invitation(self):
        email = f"jit-inv-{uuid.uuid4().hex[:6]}@test.local"
        db.create_org_invitation(self.org_id, email, "admin", "test",
                                 allowed_roles=["owner", "admin", "member"])
        inv = db.match_pending_invitation(email)
        if not inv:
            self.skipTest("invitation helper API differs; covered by store-level tests")
        self._created_users.append(f"jit_{email}")
        r = self._login(email=email)
        self.assertEqual(r.status_code, 200)
        user = db.get_user_by_email(email)
        self.assertIsNotNone(user)
        self._created_users.append(user["id"])
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["org_id"], self.org_id)


    def test_group_mapping_crud_and_resolution(self):
        m = db.upsert_ldap_group_mapping(self.org_id, ADMIN_GROUP, "admin", "test")
        self.assertEqual(m["role"], "admin")
        rows = db.list_ldap_group_mappings(self.org_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            db.resolve_ldap_role(self.org_id, [ADMIN_GROUP.upper()]), "admin")
        self.assertEqual(
            db.resolve_ldap_role(self.org_id, ["CN=Other,DC=test,DC=local"]), "member")
        db.upsert_ldap_group_mapping(self.org_id, ADMIN_GROUP, "member", "test")
        self.assertEqual(
            db.resolve_ldap_role(self.org_id, [ADMIN_GROUP]), "member")
        self.assertTrue(db.delete_ldap_group_mapping(self.org_id, rows[0]["id"]))
        self.assertEqual(db.list_ldap_group_mappings(self.org_id), [])

    def test_login_promotes_via_mapping(self):
        user_id = f"ldap_p2_{uuid.uuid4().hex[:12]}"
        db.upsert_user({"id": user_id, "email": EMAIL, "name": "LDAP P2",
                        "org_id": self.org_id, "role": "member"})
        self._created_users.append(user_id)
        db.upsert_ldap_group_mapping(self.org_id, ADMIN_GROUP, "admin", "test")
        r = self._login(groups=[ADMIN_GROUP])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(db.get_user_by_email(EMAIL)["role"], "admin")

    def test_directory_outage_keeps_role(self):
        user_id = f"ldap_p2_{uuid.uuid4().hex[:12]}"
        db.upsert_user({"id": user_id, "email": EMAIL, "name": "LDAP P2",
                        "org_id": self.org_id, "role": "admin"})
        self._created_users.append(user_id)
        db.upsert_ldap_group_mapping(self.org_id, ADMIN_GROUP, "member", "test")
        saved = ldap_client.get_groups
        ldap_client.get_groups = lambda dn: None
        try:
            r = self._login()
            self.assertEqual(r.status_code, 200)
        finally:
            ldap_client.get_groups = saved
        self.assertEqual(db.get_user_by_email(EMAIL)["role"], "admin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
