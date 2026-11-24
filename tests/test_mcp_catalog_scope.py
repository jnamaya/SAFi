import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class CatalogScopeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({
            "org_a_server": {
                "label": "Org A Only",
                "transport": "http",
                "url": "https://a.example.com/mcp",
            },
            "everyone_server": {
                "label": "Unrestricted",
                "transport": "http",
                "url": "https://open.example.com/mcp",
            },
        }, cls.tmp)
        cls.tmp.close()
        cls.old_env = os.environ.get("MCP_SERVERS_JSON")
        os.environ["MCP_SERVERS_JSON"] = cls.tmp.name

        from safi_app import create_app
        from safi_app.persistence import database as db
        cls.db = db
        cls.app = create_app()
        cls.app.config["TESTING"] = True

        cls.org_a = str(uuid.uuid4())
        cls.org_b = str(uuid.uuid4())
        cls.admin_a = f"cat_a_{uuid.uuid4().hex[:8]}"
        cls.admin_b = f"cat_b_{uuid.uuid4().hex[:8]}"
        cls.guest = f"demo_{uuid.uuid4().hex[:8]}"

        cls._exec("INSERT INTO organizations (id, name) VALUES (%s, %s)",
                  (cls.org_a, "Org A"))
        cls._exec("INSERT INTO organizations (id, name) VALUES (%s, %s)",
                  (cls.org_b, "Org B"))
        for uid, org in ((cls.admin_a, cls.org_a),
                         (cls.admin_b, cls.org_b),
                         (cls.guest, cls.org_b)):
            cls._exec(
                "INSERT INTO users (id, email, name, org_id, role) "
                "VALUES (%s, %s, %s, %s, %s)",
                (uid, f"{uid}@example.com", uid, org, "admin"))

        from safi_app.core import mcp_runtime
        mcp_runtime.register_offline("org_a_server", {
            "label": "Org A Only",
            "transport": "http",
            "url": "https://a.example.com/mcp",
            "orgs": [cls.org_a],
            "cached_tools": [{"name": "a_tool", "description": "org A only"}],
        })
        mcp_runtime.register_offline("everyone_server", {
            "label": "Unrestricted",
            "transport": "http",
            "url": "https://open.example.com/mcp",
            "cached_tools": [{"name": "open_tool", "description": "anyone"}],
        })

    @classmethod
    def tearDownClass(cls):
        for uid in (cls.admin_a, cls.admin_b, cls.guest):
            cls._exec("DELETE FROM users WHERE id = %s", (uid,))
        for org in (cls.org_a, cls.org_b):
            cls._exec("DELETE FROM organizations WHERE id = %s", (org,))
        from safi_app.core import mcp_runtime
        mcp_runtime.shutdown()
        os.unlink(cls.tmp.name)
        if cls.old_env is None:
            os.environ.pop("MCP_SERVERS_JSON", None)
        else:
            os.environ["MCP_SERVERS_JSON"] = cls.old_env

    @classmethod
    def _exec(cls, sql, params):
        conn = cls.db.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            cur.close()
        finally:
            conn.close()

    def _get(self, user_id, org_id):
        from support import login
        client = self.app.test_client()
        login(client, user_id, org_id=org_id)
        r = client.get("/api/mcp/servers")
        self.assertEqual(r.status_code, 200, r.data)
        return r.get_json()

    def _keys(self, payload):
        return {s["key"] for s in payload["servers"]}

    def test_restricted_server_is_hidden_from_another_org(self):
        body = self._get(self.admin_b, self.org_b)
        self.assertNotIn("org_a_server", self._keys(body))
        self.assertIn("everyone_server", self._keys(body))
        self.assertEqual(body["tool_count"], 1)

    def test_restricted_server_is_visible_to_its_own_org(self):
        body = self._get(self.admin_a, self.org_a)
        self.assertEqual(self._keys(body), {"org_a_server", "everyone_server"})
        self.assertEqual(body["tool_count"], 2)

    def test_no_orgs_key_means_every_organization(self):
        body = self._get(self.admin_b, self.org_b)
        self.assertIn("everyone_server", self._keys(body))

    def test_guest_sees_no_installed_servers(self):
        body = self._get(self.guest, self.org_b)
        self.assertEqual(body["servers"], [])
        self.assertEqual(body["tool_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
