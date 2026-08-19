"""
SCIM 2.0 directory sync (backlog 68).

The contract, pinned here:

- Bearer-token auth per org: no token / wrong token is 401; a token only ever
  reaches its own org's resources.
- Provisioning a not-yet-registered user creates a long-lived invitation (the
  SSO login path accepts it by email); provisioning an existing SAFi user sets
  their org membership and role.
- Deprovisioning (active=false, PATCH or DELETE) runs off-boarding: the
  member's org membership is removed and any pending invitation revoked.
- Group->role: a mapped group elevates its members' effective role; removing
  them from the group returns them to the base role.
- The last admin is never stripped by a directory sync.

Requires local MySQL (drives the HTTP API and writes/deletes rows).
Run: docker compose -f docker-compose.test.yml run --rm tests -k scim
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import scim_store


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _mk_org(name="SCIM Test Org"):
    oid = str(uuid.uuid4())
    _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)", (oid, name))
    return oid


class ScimBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        self.org = _mk_org()
        self.token = scim_store.rotate_token(self.org)  # also enables SCIM
        self.client = self.app.test_client()

    def tearDown(self):
        _exec("DELETE FROM scim_resources WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM scim_groups WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM scim_group_role_map WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM scim_config WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM org_invitations WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM organizations WHERE id=%s", (self.org,))

    def _h(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}",
                "Content-Type": "application/scim+json"}


class Auth(ScimBase):

    def test_missing_token_is_401(self):
        r = self.client.get("/scim/v2/Users")
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_is_401(self):
        r = self.client.get("/scim/v2/Users", headers=self._h("scim_bogus"))
        self.assertEqual(r.status_code, 401)

    def test_disabling_scim_closes_the_endpoint(self):
        scim_store.set_enabled(self.org, False)
        r = self.client.get("/scim/v2/Users", headers=self._h())
        self.assertEqual(r.status_code, 401)

    def test_service_provider_config_reachable(self):
        r = self.client.get("/scim/v2/ServiceProviderConfig", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["patch"]["supported"])


class HttpsEnforcement(ScimBase):
    """On an https deployment, SCIM must refuse a non-TLS request before the
    token is even considered. Localhost/plain-http deployments are exempt."""

    def test_https_deployment_rejects_plain_http(self):
        # The test client forces wsgi.url_scheme via PREFERRED_URL_SCHEME, so
        # drive the incoming scheme explicitly (as ProxyFix would from
        # X-Forwarded-Proto) to simulate a real plain-http vs https request.
        from safi_app.config import Config
        original = Config.WEB_BASE_URL
        Config.WEB_BASE_URL = "https://safi.example.com"
        try:
            r = self.client.get("/scim/v2/Users", headers=self._h(),
                                environ_overrides={"wsgi.url_scheme": "http"})
            self.assertEqual(r.status_code, 403)
            self.assertIn("HTTPS", r.get_json()["detail"])
            r2 = self.client.get("/scim/v2/Users", headers=self._h(),
                                 environ_overrides={"wsgi.url_scheme": "https"})
            self.assertEqual(r2.status_code, 200)
        finally:
            Config.WEB_BASE_URL = original

    def test_localhost_deployment_allows_http(self):
        # Default WEB_BASE_URL is http://localhost:5000 in the test env, so the
        # https requirement does not apply even to a plain-http request.
        r = self.client.get("/scim/v2/Users", headers=self._h(),
                            environ_overrides={"wsgi.url_scheme": "http"})
        self.assertEqual(r.status_code, 200)


class UserProvisioning(ScimBase):

    def _pending_emails(self):
        return {i["email"] for i in db.list_org_invitations(self.org, pending_only=True)}

    def test_provision_new_user_creates_invitation(self):
        email = f"newhire_{uuid.uuid4().hex[:8]}@example.test"
        r = self.client.post("/scim/v2/Users", headers=self._h(),
                             json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                                   "userName": email, "active": True})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["userName"], email)
        self.assertTrue(body["active"])
        self.assertIn(email, self._pending_emails(),
                      "a not-yet-registered user should become a pending invitation")

    def test_duplicate_create_is_409(self):
        email = f"dup_{uuid.uuid4().hex[:8]}@example.test"
        self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email})
        r = self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email})
        self.assertEqual(r.status_code, 409)

    def test_filter_by_username(self):
        email = f"find_{uuid.uuid4().hex[:8]}@example.test"
        self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email})
        r = self.client.get(f'/scim/v2/Users?filter=userName eq "{email}"', headers=self._h())
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["totalResults"], 1)
        self.assertEqual(body["Resources"][0]["userName"], email)

    def test_provision_existing_user_sets_membership(self):
        email = f"exist_{uuid.uuid4().hex[:8]}@example.test"
        uid = f"u_{uuid.uuid4().hex[:10]}"
        _exec("INSERT INTO users (id, email, name, role) VALUES (%s, %s, 'E', 'member')", (uid, email))
        try:
            r = self.client.post("/scim/v2/Users", headers=self._h(),
                                 json={"userName": email, "active": True})
            self.assertEqual(r.status_code, 201)
            row = db.get_user_details(uid)
            self.assertEqual(str(row["org_id"]), self.org,
                             "existing user should be added to the org")
        finally:
            _exec("DELETE FROM users WHERE id=%s", (uid,))

    def test_deprovision_via_patch_active_false_revokes_invitation(self):
        email = f"leaver_{uuid.uuid4().hex[:8]}@example.test"
        cr = self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email})
        sid = cr.get_json()["id"]
        self.assertIn(email, self._pending_emails())
        r = self.client.patch(f"/scim/v2/Users/{sid}", headers=self._h(),
                             json={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                                   "Operations": [{"op": "replace", "path": "active", "value": False}]})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["active"])
        self.assertNotIn(email, self._pending_emails(),
                         "deprovision must revoke the pending invitation")

    def test_delete_deprovisions_and_removes_resource(self):
        email = f"del_{uuid.uuid4().hex[:8]}@example.test"
        sid = self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email}).get_json()["id"]
        r = self.client.delete(f"/scim/v2/Users/{sid}", headers=self._h())
        self.assertEqual(r.status_code, 204)
        self.assertIsNone(scim_store.get_resource(self.org, sid))
        self.assertNotIn(email, self._pending_emails())


class GroupRoleSync(ScimBase):

    def _invite_role(self, email):
        for i in db.list_org_invitations(self.org, pending_only=True):
            if i["email"] == email:
                return i["role"]
        return None

    def test_group_membership_elevates_role(self):
        scim_store.set_group_role(self.org, "SAFi-Admins", "admin")
        email = f"gm_{uuid.uuid4().hex[:8]}@example.test"
        sid = self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email}).get_json()["id"]
        self.assertEqual(self._invite_role(email), "member")

        r = self.client.post("/scim/v2/Groups", headers=self._h(),
                             json={"displayName": "SAFi-Admins",
                                   "members": [{"value": sid}]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self._invite_role(email), "admin",
                         "membership in a mapped group must elevate the role")

    def test_removing_from_group_restores_base_role(self):
        scim_store.set_group_role(self.org, "SAFi-Editors", "editor")
        email = f"gr_{uuid.uuid4().hex[:8]}@example.test"
        sid = self.client.post("/scim/v2/Users", headers=self._h(), json={"userName": email}).get_json()["id"]
        gid = self.client.post("/scim/v2/Groups", headers=self._h(),
                              json={"displayName": "SAFi-Editors", "members": [{"value": sid}]}).get_json()["id"]
        self.assertEqual(self._invite_role(email), "editor")
        r = self.client.patch(f"/scim/v2/Groups/{gid}", headers=self._h(),
                             json={"Operations": [{"op": "remove", "path": "members",
                                                   "value": [{"value": sid}]}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._invite_role(email), "member",
                         "leaving the mapped group returns the user to base role")


class OrgIsolation(ScimBase):

    def test_token_only_sees_its_own_org(self):
        other = _mk_org("Other Org")
        other_token = scim_store.rotate_token(other)
        try:
            # Create a user in the other org via its own token.
            self.client.post("/scim/v2/Users", headers=self._h(other_token),
                            json={"userName": f"other_{uuid.uuid4().hex[:8]}@example.test"})
            # This org's token lists zero.
            r = self.client.get("/scim/v2/Users", headers=self._h())
            self.assertEqual(r.get_json()["totalResults"], 0,
                             "one org's token must never see another org's resources")
        finally:
            _exec("DELETE FROM scim_resources WHERE org_id=%s", (other,))
            _exec("DELETE FROM scim_config WHERE org_id=%s", (other,))
            _exec("DELETE FROM org_invitations WHERE org_id=%s", (other,))
            _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (other,))
            _exec("DELETE FROM organizations WHERE id=%s", (other,))


class LastAdminProtection(ScimBase):

    def test_deprovision_does_not_strip_the_last_admin(self):
        email = f"soleadmin_{uuid.uuid4().hex[:8]}@example.test"
        uid = f"a_{uuid.uuid4().hex[:10]}"
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'A', %s, 'admin')",
              (uid, email, self.org))
        sid = scim_store.create_resource(self.org, email, None, "A", True, "admin")["scim_id"]
        try:
            self.client.delete(f"/scim/v2/Users/{sid}", headers=self._h())
            row = db.get_user_details(uid)
            self.assertEqual(row["role"], "admin",
                             "a directory sync must never remove the final admin")
            self.assertEqual(str(row["org_id"]), self.org)
        finally:
            _exec("DELETE FROM users WHERE id=%s", (uid,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
