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
