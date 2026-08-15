"""
Data-source connector governance in the zero-catalog world.

The delegated connectors this module governed retired one by one through
2026-08-15 (github, google_drive, then microsoft/sharepoint, GOVERNANCE_BACKLOG
48k), so CONNECTOR_METADATA is deliberately empty. The machinery stays, and
what this suite now pins is different from what it pinned before:

  * The retirement is total and fail-closed. Retired account keys refuse on
    write, drop on read from lists stored before the retirement, and their
    linking routes are GONE (404), not guarded. A resurrection of any of that
    fails here first.
  * The parts of the machinery that OUTLIVED the catalog still work, because
    the MCP OAuth servers use them: oauth_tokens storage with org attribution
    and evidence, the always-permitted generic disconnect, and the admin
    visibility endpoint that must not leak across orgs or expose token
    material.
  * The admin allowlist API stays honest about an empty catalog rather than
    erroring on it.

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

# The oauth_tokens machinery's live consumers are MCP servers; exercise it the
# way they use it, with a provider key in their namespace.
MCP_PROVIDER = "mcp:workspace"


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
        db.set_org_connector_allowlist(self.org_id, None, "test")
        cg.invalidate_org(self.org_id)
        cg.invalidate_org(self.other_org)
        _exec("DELETE FROM oauth_tokens WHERE user_id IN (%s, %s)", (self.uid, self.other_uid))


class TheCatalogIsEmpty(ConnectorGovernanceBase):

    def test_no_delegated_connectors_remain(self):
        self.assertEqual({}, cg.CONNECTOR_METADATA)
        self.assertEqual([], cg.list_connectors_for_org(self.org_id))
        self.assertEqual([], cg.connectors_for_member(self.uid, self.org_id, 'admin'))
        self.assertEqual(frozenset(), cg.usable_connector_keys(self.uid, self.org_id, 'admin'))

    def test_every_key_fails_closed(self):
        """With nothing in the catalog, assert_connector_allowed refuses
        everything, retired keys included. There is no 'still works for old
        names' path."""
        for key in ("microsoft", "google", "github", "dropbox"):
            with self.subTest(key=key):
                with self.assertRaises(cg.ConnectorNotAllowedError):
                    cg.assert_connector_allowed(key, self.org_id)

    def test_retired_keys_refuse_on_write(self):
        """An admin script replaying an old allowlist must fail loudly, not
        store keys the catalog no longer knows."""
        for key in ("microsoft", "google", "github"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    db.set_org_connector_allowlist(self.org_id, [key], "admin@example.test")

    def test_stale_stored_lists_drop_on_read(self):
        """Lists stored before the retirements read as empty rather than
        resurrecting the keys. All three retired names are the live case."""
        _exec("UPDATE organizations SET settings=%s WHERE id=%s",
              ('{"connector_allowlist": ["microsoft", "google", "github"]}', self.org_id))
        cg.invalidate_org(self.org_id)
        self.assertEqual(frozenset(), cg.get_org_allowlist(self.org_id))

    def test_status_reports_an_empty_catalog(self):
        client = self.app.test_client()
        login_as(client, self.uid, "admin", org_id=self.org_id)
        body = client.get('/api/auth/status').get_json()
        self.assertEqual([], body["connectors"])
        self.assertIn("mcp_servers", body, "the successor list must ride along")


class TheRoutesAreGone(ConnectorGovernanceBase):
    """The linking routes were deleted with their connectors. 404, not a
    guard: a guarded route implies the thing behind it still exists."""

    def setUp(self):
        self.client = self.app.test_client()
        login_as(self.client, self.uid, "admin", org_id=self.org_id)

    def test_retired_login_and_callback_routes_404(self):
        for provider in ("microsoft", "google", "github"):
            for path in (f'/api/auth/{provider}/login',
                         f'/api/auth/{provider}/callback?code=x&state=y'):
                with self.subTest(path=path):
                    self.assertEqual(404, self.client.get(path).status_code)

    def test_disconnect_is_always_permitted(self):
        """The generic disconnect outlives every catalog entry: it is how a
        member removes ANY stored token, MCP ones included."""
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'tok', org_id=self.org_id)
        r = self.client.post(f'/api/auth/{MCP_PROVIDER}/disconnect')
        self.assertEqual(200, r.status_code)
        self.assertEqual([], db.get_connected_providers(self.uid))


class EvidenceAndVisibility(ConnectorGovernanceBase):
    """The storage layer outlived the catalog; the MCP servers are its
    consumers now, and every property the delegated world needed still holds."""

    def test_connect_writes_evidence_in_the_same_transaction(self):
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'tok', scope='workspace.read',
                              org_id=self.org_id)
        self.assertIn("connector_connected", _log_events(self.org_id))
        self.assertIn(MCP_PROVIDER, db.get_connected_providers(self.uid))

    def test_disconnect_writes_evidence(self):
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'tok', org_id=self.org_id)
        db.delete_oauth_token(self.uid, MCP_PROVIDER, org_id=self.org_id)
        self.assertIn("connector_disconnected", _log_events(self.org_id))

    def test_disconnecting_nothing_writes_nothing(self):
        """A repeat disconnect, or a probe for a provider never linked, must not
        manufacture history that did not happen."""
        before = _log_events(self.org_id).count("connector_disconnected")
        db.delete_oauth_token(self.uid, MCP_PROVIDER, org_id=self.org_id)
        after = _log_events(self.org_id).count("connector_disconnected")
        self.assertEqual(before, after)

    def test_no_org_still_stores_the_token(self):
        """Single-user install: no evidence log to write to, but the connection
        must still work."""
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'tok', org_id=None)
        self.assertIn(MCP_PROVIDER, db.get_connected_providers(self.uid))

    def test_connections_never_cross_orgs(self):
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'tok', org_id=self.org_id)
        db.upsert_oauth_token(self.other_uid, MCP_PROVIDER, 'tok', org_id=self.other_org)
        mine = db.list_org_connections(self.org_id)
        self.assertEqual({self.uid}, {r["user_id"] for r in mine})
        self.assertEqual({MCP_PROVIDER}, {r["provider"] for r in mine})

    def test_connections_carry_no_token_material(self):
        db.upsert_oauth_token(self.uid, MCP_PROVIDER, 'super-secret-token', org_id=self.org_id)
        rows = db.list_org_connections(self.org_id)
        self.assertTrue(rows)
        blob = repr(rows)
        self.assertNotIn('super-secret-token', blob)
        for forbidden in ('access_token', 'refresh_token'):
            self.assertNotIn(forbidden, rows[0], f"{forbidden} must not be selected")


class AdminApi(ConnectorGovernanceBase):

    def setUp(self):
        self.client = self.app.test_client()

    def test_admin_reads_an_empty_catalog_without_error(self):
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        r = self.client.get(f'/api/organizations/{self.org_id}/connectors')
        self.assertEqual(200, r.status_code)
        self.assertIsNone(r.get_json()["allowlist"])
        self.assertEqual([], r.get_json()["connectors"])

    def test_admin_can_still_write_the_empty_policy(self):
        """'Members may link nothing' remains a coherent, storable policy even
        with nothing to block; it will bind any future catalog entry from the
        moment it exists."""
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        r = self.client.put(f'/api/organizations/{self.org_id}/connectors',
                            json={"allowlist": []})
        self.assertEqual(200, r.status_code)
        self.assertEqual([], r.get_json()["allowlist"])
        self.assertIn("connector_allowlist_changed", _log_events(self.org_id))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
