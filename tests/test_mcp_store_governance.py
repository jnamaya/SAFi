"""
Governance of GUI-installed MCP servers: approval, evidence, tenancy (backlog 48).

The three properties that make one-click install defensible, and each one is
tested against the database rather than against a mock, because each one is a
claim we would otherwise be making on the strength of a docstring:

  * INSTALLING IS NOT ACTIVATING. A new server lands pending and reaches no
    agent until a second admin approves it.
  * THE INSTALLER IS NOT THE APPROVER, unless they are the org's only eligible
    reviewer, in which case the sign-off is recorded as non-independent instead
    of being quietly counted as real oversight. Same rule and same helper as
    knowledge base documents.
  * ONE ORGANIZATION'S INSTALL IS NOT ANOTHER'S TOOL. The catalogue is scoped,
    and the save path re-checks rather than trusting that the picker hid it.

Also covered: every state change writes an evidence row, and the generation
counter moves so the other gunicorn workers reconnect without a restart.

Run:  venv/bin/python tests/test_mcp_store_governance.py
"""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.core.services import mcp_install
from safi_app.core.services.mcp_manager import MCPManager
from safi_app.core.tool_connectors import CONNECTOR_TOOLS
from safi_app.persistence import database as db
from safi_app.persistence import mcp_store
from support import login


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _events(org_id):
    return [r["event_type"] for r in db.list_compliance_log(org_id, limit=50)]


ENTRY = {
    "connector_key": "billing_test",
    "registry_name": "com.example/billing",
    "registry_version": "1.2.0",
    "title": "Billing API",
    "description": "Invoices.",
    "transport": "http",
    "url": "https://mcp.example.com/mcp",
}


class McpStoreBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.other_org = str(uuid.uuid4())
        cls.admin = f"mcp_a_{uuid.uuid4().hex[:8]}"
        cls.admin2 = f"mcp_b_{uuid.uuid4().hex[:8]}"
        cls.other_admin = f"mcp_c_{uuid.uuid4().hex[:8]}"
        for oid, name in ((cls.org_id, 'MCP Test Org'), (cls.other_org, 'MCP Other Org')):
            _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)", (oid, name))
        for uid, oid in ((cls.admin, cls.org_id), (cls.admin2, cls.org_id),
                         (cls.other_admin, cls.other_org)):
            _exec("INSERT INTO users (id, email, name, org_id, role) "
                  "VALUES (%s, %s, %s, %s, 'admin')",
                  (uid, f"{uid}@example.test", "MCP Test", oid))

    @classmethod
    def tearDownClass(cls):
        for oid in (cls.org_id, cls.other_org):
            _exec("DELETE FROM org_mcp_servers WHERE org_id=%s", (oid,))
            _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (oid,))
        for uid in (cls.admin, cls.admin2, cls.other_admin):
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))
        for oid in (cls.org_id, cls.other_org):
            _exec("DELETE FROM organizations WHERE id=%s", (oid,))

    def tearDown(self):
        for oid in (self.org_id, self.other_org):
            _exec("DELETE FROM org_mcp_servers WHERE org_id=%s", (oid,))

    def install(self, org=None, actor=None, key=None):
        entry = dict(ENTRY)
        if key:
            entry["connector_key"] = key
        return mcp_store.install(org or self.org_id, actor or self.admin, entry)


class InstallIsNotActivation(McpStoreBase):

    def test_install_lands_pending(self):
        row = self.install()
        self.assertEqual(row["status"], mcp_store.STATUS_PENDING)

    def test_pending_server_is_not_in_the_runtime_set(self):
        self.install()
        self.assertNotIn("billing_test", mcp_install.desired_runtime_servers())

    def test_approved_server_enters_the_runtime_set(self):
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        desired = mcp_install.desired_runtime_servers()
        self.assertIn("billing_test", desired)
        self.assertEqual(desired["billing_test"]["url"], ENTRY["url"])
        self.assertEqual(desired["billing_test"]["transport"], "http")

    def test_rejected_server_never_enters_the_runtime_set(self):
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_REJECTED, self.admin2, self.org_id)
        self.assertNotIn("billing_test", mcp_install.desired_runtime_servers())

    def test_generation_moves_so_other_workers_resync(self):
        before = mcp_store.current_generation()
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        self.assertGreater(mcp_store.current_generation(), before)


class EvidenceTests(McpStoreBase):

    def test_every_state_change_writes_an_evidence_row(self):
        row = self.install()
        self.assertIn("mcp_server_installed", _events(self.org_id))
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        self.assertIn("mcp_server_active", _events(self.org_id))
        mcp_store.delete(row["id"], self.org_id, self.admin)
        self.assertIn("mcp_server_removed", _events(self.org_id))

    def test_evidence_names_the_endpoint_and_version(self):
        self.install()
        detail = db.list_compliance_log(self.org_id, limit=5)[0]["detail"]
        blob = detail if isinstance(detail, str) else str(detail)
        self.assertIn("mcp.example.com", blob)
        self.assertIn("1.2.0", blob)


class SeparationOfDuties(McpStoreBase):
    """The installer may not approve their own install while anyone else could."""

    def test_installer_is_not_a_sole_reviewer_when_a_second_admin_exists(self):
        self.assertFalse(mcp_install.can_review_own_install(self.org_id, self.admin))

    def test_api_refuses_self_approval(self):
        row = self.install()
        client = self.app.test_client()
        login(client, self.admin, self.org_id)
        resp = client.post(f"/api/mcp/servers/{row['id']}/review", json={"decision": "approve"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(mcp_store.get_server(row["id"])["status"], mcp_store.STATUS_PENDING)

    def test_api_allows_a_second_admin(self):
        row = self.install()
        client = self.app.test_client()
        login(client, self.admin2, self.org_id)
        resp = client.post(f"/api/mcp/servers/{row['id']}/review", json={"decision": "approve"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["independent_review"])
        self.assertEqual(mcp_store.get_server(row["id"])["status"], mcp_store.STATUS_ACTIVE)

    def test_sole_admin_may_self_approve_and_it_is_recorded_as_non_independent(self):
        row = self.install(org=self.other_org, actor=self.other_admin, key="sole_test")
        self.assertTrue(mcp_install.can_review_own_install(self.other_org, self.other_admin))
        client = self.app.test_client()
        login(client, self.other_admin, self.other_org)
        resp = client.post(f"/api/mcp/servers/{row['id']}/review", json={"decision": "approve"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["independent_review"])
        # And the database says so too, not just the response.
        self.assertFalse(mcp_store.get_server(row["id"])["independent_review"])


class TenancyTests(McpStoreBase):
    """One organization's install must not become another's tool."""

    def test_connector_key_is_unique_across_the_deployment(self):
        self.install()
        self.assertTrue(mcp_store.connector_key_taken("billing_test"))
        with self.assertRaises(Exception):
            self.install(org=self.other_org, actor=self.other_admin)

    def test_available_key_avoids_builtins(self):
        self.assertIn("github", CONNECTOR_TOOLS)
        self.assertNotEqual(mcp_install.available_key("vendor/github"), "github")

    def test_available_key_avoids_an_existing_install(self):
        self.install(key="weather_mcp")
        self.assertNotEqual(mcp_install.available_key("x/weather-mcp"), "weather_mcp")

    def test_visible_connectors_are_scoped_to_the_installing_org(self):
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        self.assertIn("billing_test", MCPManager.visible_connectors(self.org_id))
        self.assertNotIn("billing_test", MCPManager.visible_connectors(self.other_org))

    def test_a_pending_server_is_not_visible_even_to_its_own_org(self):
        self.install()
        self.assertNotIn("billing_test", MCPManager.visible_connectors(self.org_id))

    def test_builtins_are_visible_to_every_org(self):
        for org in (self.org_id, self.other_org):
            self.assertIn("web_search", MCPManager.visible_connectors(org))

    def test_another_org_cannot_grant_the_connector_to_an_agent(self):
        """The picker hides it, but hiding is not a check."""
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        client = self.app.test_client()
        login(client, self.other_admin, self.other_org)
        resp = client.post("/api/agents", json={
            "key": f"probe_{uuid.uuid4().hex[:6]}",
            "name": "Probe",
            "tools": ["billing_test"],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertIn("billing_test", resp.get_json()["error"])

    def test_the_catalogue_does_not_offer_another_orgs_server(self):
        row = self.install()
        mcp_store.set_status(row["id"], mcp_store.STATUS_ACTIVE, self.admin2, self.org_id)
        client = self.app.test_client()
        login(client, self.other_admin, self.other_org)
        categories = client.get("/api/agents/tools").get_json()["tools"]
        names = {t["name"] for c in categories for t in c["tools"]}
        self.assertNotIn("billing_test", names)


class RoleTests(McpStoreBase):

    def test_registry_routes_require_admin(self):
        member = f"mcp_m_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, %s, %s, 'member')",
              (member, f"{member}@example.test", "Member", self.org_id))
        try:
            client = self.app.test_client()
            login(client, member, self.org_id)
            self.assertEqual(client.get("/api/mcp/servers").status_code, 403)
            self.assertEqual(
                client.post("/api/mcp/servers", json={"name": "x/y"}).status_code, 403)
        finally:
            _exec("DELETE FROM sessions WHERE user_id=%s", (member,))
            _exec("DELETE FROM users WHERE id=%s", (member,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
