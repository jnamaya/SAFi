"""
The Tool Servers screen reports real status, not a fixed sentence (backlog 48d).

The bug this exists to prevent: the screen printed "Inactive. Enable the ones you
want in a policy" as static text, so it went on saying that after a policy
enabled the tool. That is the one moment the reader is looking for confirmation,
and the page answered with a claim it had never checked.

Status is therefore read from the same place enforcement reads it. A policy's
`will_rules.allowed_tools` may name a connector or an individual function, and
both authorize the function, so the endpoint expands through `expand_connectors`
exactly as Synderesis does. Anything else would drift into a second opinion
about what a policy allows.

Run:  venv/bin/python tests/test_mcp_tool_status.py
"""
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
        """Every tool the endpoint reports, keyed by name."""
        body = self._client().get('/api/mcp/servers').get_json()
        self.assertTrue(body["ok"])
        return {
            tool["name"]: tool
            for server in body["servers"]
            for tool in server["tools"]
        }

    def test_endpoint_reports_policy_usage_per_tool(self):
        """The whole point: enabling a tool changes what this says."""
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
        """With no MCP server installed the endpoint still answers cleanly, so
        the screen renders an empty state rather than an error."""
        body = self._client().get('/api/mcp/servers').get_json()
        self.assertTrue(body["ok"])
        self.assertIsInstance(body["servers"], list)
        for server in body["servers"]:
            self.assertIn("enabled_count", server)
            for tool in server["tools"]:
                self.assertIn("policies", tool)
                self.assertIn("agents", tool)

    def test_the_tools_endpoint_marks_what_a_policy_authorizes(self):
        """The ceiling used to be applied only in the browser, so every way that
        client-side lookup could fail put the full catalogue on screen."""
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
        """The bug Nelson hit: an agent saw none of a server's tools even though
        its policy authorized the whole server.

        A policy may store the connector name (`demo_server`) while the picker
        cards are function names (`demo_echo`). The browser compared those raw
        strings, matched nothing, and hid every tool. The ceiling has to be
        expanded exactly as the compiler expands it, which is what this pins.
        """
        from safi_app.api.agent_api_routes import policy_tool_ceiling
        from safi_app.core.tool_connectors import (
            clear_discovered_connectors, expand_connectors, register_discovered_connector,
        )

        register_discovered_connector("probe_server", ("probe_echo", "probe_add"))
        self.addCleanup(clear_discovered_connectors)

        self._policy(["probe_server"])
        ceiling = policy_tool_ceiling(self._only_policy_id())
        self.assertEqual(ceiling, {"probe_echo", "probe_add"})

        # Which is what the per-tool cards are checked against.
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
        """Absent is not the same as empty: a policy written before tool
        authorization existed must keep working."""
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
