"""
Data-source connector governance: which external accounts members may link.

Before this, /api/auth/{provider}/login checked only that you were logged in.
Any member of any org could link Google Drive, SharePoint or GitHub to a
governed agent, with no admin involvement and no record it happened.

The load-bearing tests:

  * test_callback_fails_closed_when_blocked — the guard everyone forgets. If
    only the login route is guarded, the callback is still reachable directly,
    and a code obtained seconds before an admin revoked the connector still
    redeems into a stored token.
  * test_connect_writes_evidence_in_the_same_transaction — the evidence row and
    the token must be one transaction, or a connection can exist with no record
    that it was made.
  * test_connections_never_cross_orgs — the admin visibility endpoint joins on
    users.org_id; a Python-side filter would be one refactor away from leaking.

Run:  venv/bin/python tests/test_connector_governance.py
"""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.core.services import connector_governance as cg
from support import login_as


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _log_events(org_id):
    return [r["event_type"] for r in db.list_compliance_log(org_id, limit=50)]


class ConnectorGovernanceBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.other_org = str(uuid.uuid4())
        cls.uid = f"conn_{uuid.uuid4().hex[:8]}"
        cls.other_uid = f"conn_other_{uuid.uuid4().hex[:8]}"
        for oid, name in ((cls.org_id, 'Connector Test Org'), (cls.other_org, 'Other Org')):
            _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)", (oid, name))
        for uid, oid in ((cls.uid, cls.org_id), (cls.other_uid, cls.other_org)):
            _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, %s, %s, 'admin')",
                  (uid, f"{uid}@example.test", "Conn Test", oid))

    @classmethod
    def tearDownClass(cls):
        for oid in (cls.org_id, cls.other_org):
            _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (oid,))
        for uid in (cls.uid, cls.other_uid):
            _exec("DELETE FROM oauth_tokens WHERE user_id=%s", (uid,))
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))
        for oid in (cls.org_id, cls.other_org):
            _exec("DELETE FROM organizations WHERE id=%s", (oid,))

    def tearDown(self):
        # Back to unrestricted, and drop the 60s cache so the next test does not
        # read this one's policy.
        db.set_org_connector_allowlist(self.org_id, None, "test")
        cg.invalidate_org(self.org_id)
        cg.invalidate_org(self.other_org)
        _exec("DELETE FROM oauth_tokens WHERE user_id IN (%s, %s)", (self.uid, self.other_uid))


class AllowListSemantics(ConnectorGovernanceBase):

    def test_absent_means_unrestricted(self):
        """Every pre-existing org has no stored list; they must be unaffected."""
        self.assertIsNone(db.get_org_connector_config(self.org_id)["allowlist"])
        self.assertIsNone(cg.get_org_allowlist(self.org_id))
        for key in cg.CONNECTOR_METADATA:
            self.assertTrue(cg.connector_allowed(key, self.org_id))

    def test_empty_list_blocks_everything(self):
        """Unlike providers, an empty connector list is a coherent policy:
        'members may link nothing'. An empty PROVIDER list would brick the org,
        which is why that write path rejects it and this one does not."""
        db.set_org_connector_allowlist(self.org_id, [], "admin@example.test")
        cg.invalidate_org(self.org_id)
        self.assertEqual(frozenset(), cg.get_org_allowlist(self.org_id))
        for key in cg.CONNECTOR_METADATA:
            self.assertFalse(cg.connector_allowed(key, self.org_id))

    def test_partial_list(self):
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        cg.invalidate_org(self.org_id)
        self.assertTrue(cg.connector_allowed("google", self.org_id))
        self.assertFalse(cg.connector_allowed("github", self.org_id))

    def test_unknown_key_rejected_on_write(self):
        with self.assertRaises(ValueError):
            db.set_org_connector_allowlist(self.org_id, ["dropbox"], "admin@example.test")

    def test_unknown_key_dropped_on_read(self):
        """A key removed from CONNECTOR_METADATA must not come back via a list
        stored before the removal."""
        _exec("UPDATE organizations SET settings=%s WHERE id=%s",
              ('{"connector_allowlist": ["google", "legacy_thing"]}', self.org_id))
        cg.invalidate_org(self.org_id)
        self.assertEqual(frozenset({"google"}), cg.get_org_allowlist(self.org_id))

    def test_no_org_is_unrestricted(self):
        """A single-user install has no admin to set a policy; failing closed
        there would break the Quick Start for no security gain."""
        self.assertIsNone(cg.get_org_allowlist(None))
        self.assertTrue(cg.connector_allowed("github", None))

    def test_allowlist_change_is_evidence_logged(self):
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        self.assertIn("connector_allowlist_changed", _log_events(self.org_id))

    def test_unchanged_write_logs_nothing(self):
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        before = _log_events(self.org_id).count("connector_allowlist_changed")
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        after = _log_events(self.org_id).count("connector_allowlist_changed")
        self.assertEqual(before, after, "a no-op write should not manufacture evidence")

    def test_assert_raises_for_unknown_connector(self):
        with self.assertRaises(cg.ConnectorNotAllowedError):
            cg.assert_connector_allowed("dropbox", self.org_id)


class RouteEnforcement(ConnectorGovernanceBase):

    def setUp(self):
        self.client = self.app.test_client()
        login_as(self.client, self.uid, "admin", org_id=self.org_id)

    def test_login_redirects_when_allowed(self):
        """Unrestricted: the route proceeds to the provider (or fails on missing
        OAuth config) — either way it is NOT the connector-policy bounce."""
        r = self.client.get('/api/auth/github/login')
        self.assertNotIn('connector_not_allowed', r.headers.get('Location', ''))

    def test_login_fails_closed_when_blocked(self):
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        cg.invalidate_org(self.org_id)
        r = self.client.get('/api/auth/github/login')
        self.assertEqual(302, r.status_code)
        self.assertIn('connector_not_allowed', r.headers['Location'])

    def test_callback_fails_closed_when_blocked(self):
        """Guarding only the login route leaves this reachable directly, and
        lets a code obtained before the revocation still redeem into a token."""
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        cg.invalidate_org(self.org_id)
        for path in ('/api/auth/github/callback?code=x&state=y',
                     '/api/auth/microsoft/callback?code=x&state=y'):
            r = self.client.get(path)
            self.assertEqual(302, r.status_code, path)
            self.assertIn('connector_not_allowed', r.headers['Location'], path)
        # And no token was written by the attempt.
        self.assertEqual([], db.get_connected_providers(self.uid))

    def test_every_connector_has_both_routes_guarded(self):
        """Adding a connector without guarding its pair is the regression this
        catches — it would be invisible until someone tried to exploit it."""
        db.set_org_connector_allowlist(self.org_id, [], "admin@example.test")
        cg.invalidate_org(self.org_id)
        for key in cg.CONNECTOR_METADATA:
            for path in (f'/api/auth/{key}/login', f'/api/auth/{key}/callback?code=x&state=y'):
                r = self.client.get(path)
                self.assertIn('connector_not_allowed', r.headers.get('Location', ''),
                              f"{path} is not fail-closed")

    def test_disconnect_is_always_permitted(self):
        """Revoking access must work even for a connector since blocked — that
        is the direction the policy wants to travel in."""
        db.upsert_oauth_token(self.uid, 'github', 'tok', org_id=self.org_id)
        db.set_org_connector_allowlist(self.org_id, [], "admin@example.test")
        cg.invalidate_org(self.org_id)
        r = self.client.post('/api/auth/github/disconnect')
        self.assertEqual(200, r.status_code)
        self.assertEqual([], db.get_connected_providers(self.uid))


class EvidenceAndVisibility(ConnectorGovernanceBase):

    def test_connect_writes_evidence_in_the_same_transaction(self):
        db.upsert_oauth_token(self.uid, 'google', 'tok', scope='drive.readonly',
                              org_id=self.org_id)
        self.assertIn("connector_connected", _log_events(self.org_id))
        self.assertIn('google', db.get_connected_providers(self.uid))

    def test_disconnect_writes_evidence(self):
        db.upsert_oauth_token(self.uid, 'google', 'tok', org_id=self.org_id)
        db.delete_oauth_token(self.uid, 'google', org_id=self.org_id)
        self.assertIn("connector_disconnected", _log_events(self.org_id))

    def test_disconnecting_nothing_writes_nothing(self):
        """A repeat disconnect, or a probe for a provider never linked, must not
        manufacture history that did not happen."""
        before = _log_events(self.org_id).count("connector_disconnected")
        db.delete_oauth_token(self.uid, 'github', org_id=self.org_id)
        after = _log_events(self.org_id).count("connector_disconnected")
        self.assertEqual(before, after)

    def test_no_org_still_stores_the_token(self):
        """Single-user install: no evidence log to write to, but the connection
        must still work."""
        db.upsert_oauth_token(self.uid, 'google', 'tok', org_id=None)
        self.assertIn('google', db.get_connected_providers(self.uid))

    def test_connections_never_cross_orgs(self):
        db.upsert_oauth_token(self.uid, 'google', 'tok', org_id=self.org_id)
        db.upsert_oauth_token(self.other_uid, 'github', 'tok', org_id=self.other_org)
        mine = db.list_org_connections(self.org_id)
        self.assertEqual({self.uid}, {r["user_id"] for r in mine})
        self.assertEqual({'google'}, {r["provider"] for r in mine})

    def test_connections_carry_no_token_material(self):
        db.upsert_oauth_token(self.uid, 'google', 'super-secret-token', org_id=self.org_id)
        rows = db.list_org_connections(self.org_id)
        self.assertTrue(rows)
        blob = repr(rows)
        self.assertNotIn('super-secret-token', blob)
        for forbidden in ('access_token', 'refresh_token'):
            self.assertNotIn(forbidden, rows[0], f"{forbidden} must not be selected")


class AdminApi(ConnectorGovernanceBase):

    def setUp(self):
        self.client = self.app.test_client()

    def test_admin_can_read_and_write(self):
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        r = self.client.get(f'/api/organizations/{self.org_id}/connectors')
        self.assertEqual(200, r.status_code)
        self.assertIsNone(r.get_json()["allowlist"])
        self.assertEqual(len(cg.CONNECTOR_METADATA), len(r.get_json()["connectors"]))

        r = self.client.put(f'/api/organizations/{self.org_id}/connectors',
                            json={"allowlist": ["google"]})
        self.assertEqual(200, r.status_code)
        self.assertEqual(["google"], r.get_json()["allowlist"])

    def test_blocked_connectors_are_still_listed_for_the_admin(self):
        """An admin needs to see a blocked source to be able to re-enable it."""
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        self.client.put(f'/api/organizations/{self.org_id}/connectors',
                        json={"allowlist": ["google"]})
        body = self.client.get(f'/api/organizations/{self.org_id}/connectors').get_json()
        by_key = {c["key"]: c for c in body["connectors"]}
        self.assertTrue(by_key["google"]["allowed"])
        self.assertFalse(by_key["github"]["allowed"])

    def test_non_admin_is_refused(self):
        login_as(self.client, self.uid, "member", org_id=self.org_id)
        for verb, kwargs in (("get", {}), ("put", {"json": {"allowlist": []}})):
            r = getattr(self.client, verb)(f'/api/organizations/{self.org_id}/connectors', **kwargs)
            self.assertIn(r.status_code, (401, 403), f"{verb} allowed for a member")
        r = self.client.get(f'/api/organizations/{self.org_id}/connections')
        self.assertIn(r.status_code, (401, 403))

    def test_admin_cannot_read_another_org(self):
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        for path in (f'/api/organizations/{self.other_org}/connectors',
                     f'/api/organizations/{self.other_org}/connections'):
            self.assertEqual(403, self.client.get(path).status_code, path)

    def test_status_reports_what_the_org_permits(self):
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        db.set_org_connector_allowlist(self.org_id, ["google"], "admin@example.test")
        cg.invalidate_org(self.org_id)
        body = self.client.get('/api/auth/status').get_json()
        allowed = {c["key"] for c in body["connectors"] if c["allowed"]}
        self.assertEqual({"google"}, allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
