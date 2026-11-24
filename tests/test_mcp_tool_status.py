import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from support import login


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class ToolStatusTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org = str(uuid.uuid4())
        cls.admin = f"ts_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)", (cls.org, 'Tool Status Org'))
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, %s, %s, 'admin')",
              (cls.admin, f"{cls.admin}@example.test", "Status", cls.org))

    @classmethod
    def tearDownClass(cls):
        _exec("DELETE FROM policies WHERE org_id=%s", (cls.org,))
        _exec("DELETE FROM agents WHERE org_id=%s", (cls.org,))
        _exec("DELETE FROM sessions WHERE user_id=%s", (cls.admin,))
        _exec("DELETE FROM users WHERE id=%s", (cls.admin,))
        _exec("DELETE FROM organizations WHERE id=%s", (cls.org,))

    def tearDown(self):
        _exec("DELETE FROM policies WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM agents WHERE org_id=%s", (self.org,))

    def _client(self):
        client = self.app.test_client()
        login(client, self.admin, self.org)
        return client

    def _policy(self, allowed):
        _exec("""INSERT INTO policies
                 (id, name, org_id, created_by, worldview, will_rules, values_weights, policy_config)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
              (str(uuid.uuid4()), 'Status Policy', self.org, self.admin, 'test',
               json.dumps({"allowed_tools": allowed}), json.dumps([]), json.dumps({})))

    def _tools(self):
        body = self._client().get('/api/mcp/servers').get_json()
        self.assertTrue(body["ok"])
        return {
            tool["name"]: tool
            for server in body["servers"]
            for tool in server["tools"]
        }

    def test_endpoint_reports_policy_usage_per_tool(self):
        self._policy(["web_search"])
        tools = self._tools()
        if "web_search" not in tools:
            self.skipTest("no MCP server connected in this environment")
        self.assertIn('Status Policy', tools["web_search"]["policies"])

    def test_a_tool_no_policy_names_stays_inactive(self):
        self._policy(["web_search"])
        tools = self._tools()
        for name, tool in tools.items():
            if name != "web_search":
                self.assertEqual(tool["policies"], [],
                                 f"{name} should not be reported as enabled")

    def test_shape_is_present_even_with_no_servers(self):
        body = self._client().get('/api/mcp/servers').get_json()
        self.assertTrue(body["ok"])
        self.assertIsInstance(body["servers"], list)
        for server in body["servers"]:
            self.assertIn("enabled_count", server)
            for tool in server["tools"]:
                self.assertIn("policies", tool)
                self.assertIn("agents", tool)

    def test_the_tools_endpoint_marks_what_a_policy_authorizes(self):
        self._policy(["web_search"])
        policy_id = self._only_policy_id()
        body = self._client().get(f'/api/agents/tools?policy_id={policy_id}').get_json()
        self.assertTrue(body["policy_narrows"])
        marks = {
            tool["name"]: tool.get("allowed_by_policy")
            for cat in body["tools"] for tool in cat["tools"]
        }
        self.assertTrue(marks.get("web_search"))
        for name, allowed in marks.items():
            if name not in ("web_search", "web_news"):
                self.assertFalse(allowed, f"{name} should not be marked authorized")

    def test_a_policy_naming_a_SERVER_authorizes_its_tools(self):
        from safi_app.api.agent_api_routes import policy_tool_ceiling
        from safi_app.core.tool_connectors import (
            clear_discovered_connectors, expand_connectors, register_discovered_connector,
        )

        register_discovered_connector("probe_server", ("probe_echo", "probe_add"))
        self.addCleanup(clear_discovered_connectors)

        self._policy(["probe_server"])
        ceiling = policy_tool_ceiling(self._only_policy_id())
        self.assertEqual(ceiling, {"probe_echo", "probe_add"})

        for card in ("probe_echo", "probe_add"):
            self.assertTrue(set(expand_connectors([card])) <= ceiling,
                            f"{card} should be authorized by a policy naming its server")

    def test_a_policy_naming_one_tool_does_not_authorize_its_siblings(self):
        from safi_app.api.agent_api_routes import policy_tool_ceiling
        from safi_app.core.tool_connectors import (
            clear_discovered_connectors, register_discovered_connector,
        )
        register_discovered_connector("probe_server", ("probe_echo", "probe_add"))
        self.addCleanup(clear_discovered_connectors)

        self._policy(["probe_echo"])
        self.assertEqual(policy_tool_ceiling(self._only_policy_id()), {"probe_echo"})

    def test_an_absent_allowed_tools_key_does_not_narrow(self):
        from safi_app.api.agent_api_routes import policy_tool_ceiling
        _exec("""INSERT INTO policies
                 (id, name, org_id, created_by, worldview, will_rules, values_weights, policy_config)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
              (str(uuid.uuid4()), 'Legacy', self.org, self.admin, 'test',
               json.dumps({"rules": []}), json.dumps([]), json.dumps({})))
        self.assertIsNone(policy_tool_ceiling(self._only_policy_id()))

    def test_no_policy_means_no_narrowing(self):
        body = self._client().get('/api/agents/tools').get_json()
        self.assertFalse(body["policy_narrows"])

    def test_saving_a_tool_the_policy_blocks_is_refused(self):
        self._policy(["web_search"])
        policy_id = self._only_policy_id()
        resp = self._client().post('/api/agents', json={
            "key": f"probe_{uuid.uuid4().hex[:6]}",
            "name": "Probe",
            "policy_id": policy_id,
            "tools": ["find_places"],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("does not authorize", resp.get_json()["error"])

    def test_saving_an_authorized_tool_succeeds(self):
        self._policy(["web_search"])
        policy_id = self._only_policy_id()
        resp = self._client().post('/api/agents', json={
            "key": f"probe_{uuid.uuid4().hex[:6]}",
            "name": "Probe",
            "policy_id": policy_id,
            "tools": ["web_search"],
        })
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def _only_policy_id(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM policies WHERE org_id=%s LIMIT 1", (self.org,))
            return cur.fetchone()[0]
        finally:
            cur.close()
            conn.close()

    def test_a_guest_is_offered_no_installed_tools(self):
        from safi_app.core.services.mcp_manager import MCPManager, is_guest

        self.assertTrue(is_guest("demo_abc123"))
        self.assertTrue(is_guest("x", "someone@demo.local"))
        self.assertFalse(is_guest("real_user", "person@example.test"))

        from safi_app.core.tool_connectors import (
            clear_discovered_connectors, register_discovered_connector,
        )
        register_discovered_connector("probe_server", ("probe_echo",))
        self.addCleanup(clear_discovered_connectors)

        offered = MCPManager.known_connectors(self.org, guest=True)
        self.assertNotIn("probe_server", offered)
        self.assertIn("web_search", offered)

    def test_a_guest_cannot_save_an_agent_with_an_installed_tool(self):
        guest = f"demo_{uuid.uuid4()}"
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, %s, %s, 'admin')",
              (guest, f"{guest}@demo.local", "Guest", self.org))
        try:
            client = self.app.test_client()
            login(client, guest, self.org)
            resp = client.post('/api/agents', json={
                "key": f"g_{uuid.uuid4().hex[:6]}",
                "name": "Guest Agent",
                "tools": ["probe_tool_that_is_not_builtin"],
            })
            self.assertEqual(resp.status_code, 400)
        finally:
            _exec("DELETE FROM sessions WHERE user_id=%s", (guest,))
            _exec("DELETE FROM users WHERE id=%s", (guest,))

    def test_members_cannot_read_the_inventory(self):
        member = f"ts_m_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, %s, %s, 'member')",
              (member, f"{member}@example.test", "Member", self.org))
        try:
            client = self.app.test_client()
            login(client, member, self.org)
            self.assertEqual(client.get('/api/mcp/servers').status_code, 403)
        finally:
            _exec("DELETE FROM sessions WHERE user_id=%s", (member,))
            _exec("DELETE FROM users WHERE id=%s", (member,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
