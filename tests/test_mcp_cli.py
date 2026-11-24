import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from safi_app.core import mcp_runtime
from safi_app.core.services import mcp_manager
from safi_app.core.tool_connectors import CONNECTOR_TOOLS, clear_discovered_connectors

import safi_mcp

FIXTURE = str(Path(__file__).resolve().parent / "fixture_mcp_server.py")


class KeyDerivationTests(unittest.TestCase):
    def test_key_from_a_registry_name(self):
        self.assertEqual(safi_mcp.derive_key("io.github.owner/weather-mcp"), "weather_mcp")

    def test_key_from_a_package_spec(self):
        self.assertEqual(safi_mcp.derive_key("@scope/server@1.2.3"), "server_1_2_3")

    def test_unique_key_avoids_builtins(self):
        self.assertIn("web_search", CONNECTOR_TOOLS)
        self.assertNotEqual(safi_mcp.unique_key("web_search", {}), "web_search")

    def test_unique_key_avoids_an_existing_entry(self):
        self.assertNotEqual(safi_mcp.unique_key("acme", {"acme": {}}), "acme")

    def test_empty_input_still_yields_a_key(self):
        self.assertTrue(safi_mcp.derive_key(""))


class RuntimeAvailabilityTests(unittest.TestCase):

    def test_missing_launcher_is_refused_with_the_binary_named(self):
        with self.assertRaises(SystemExit):
            safi_mcp.check_runtime_available(
                {"transport": "stdio", "command": "definitely-not-installed-xyz"})

    def test_npx_is_available_where_this_runs(self):
        import shutil
        if not Path("/app").exists():
            self.skipTest("not running inside the SAFi image")
        self.assertTrue(shutil.which("npx"), "npx should be on PATH in the image")

    def test_a_present_launcher_passes(self):
        safi_mcp.check_runtime_available({"transport": "stdio", "command": sys.executable})

    def test_hosted_servers_need_no_local_runtime(self):
        safi_mcp.check_runtime_available({"transport": "http", "url": "https://example.com/mcp"})


class ServerFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.tmp.write("{}")
        self.tmp.close()
        self.old = os.environ.get("MCP_SERVERS_JSON")
        os.environ["MCP_SERVERS_JSON"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("MCP_SERVERS_JSON", None)
        else:
            os.environ["MCP_SERVERS_JSON"] = self.old
        os.unlink(self.tmp.name)

    def test_round_trip(self):
        safi_mcp.write_servers({"acme": {"transport": "http", "url": "https://a.example/mcp"}})
        self.assertEqual(safi_mcp.read_servers()["acme"]["url"], "https://a.example/mcp")

    def test_write_is_atomic_and_leaves_no_temp_file(self):
        safi_mcp.write_servers({"acme": {"transport": "http", "url": "https://a.example/mcp"}})
        self.assertFalse(Path(self.tmp.name + ".tmp").exists())

    def test_disabled_servers_are_excluded_from_the_runtime_set(self):
        payload = {
            "on": {"transport": "http", "url": "https://a.example/mcp"},
            "off": {"transport": "http", "url": "https://b.example/mcp", "enabled": False},
        }
        Path(self.tmp.name).write_text(json.dumps(payload), encoding="utf-8")
        servers = mcp_manager.file_servers()
        self.assertIn("on", servers)
        self.assertNotIn("off", servers)

    def test_file_servers_reads_from_disk_not_from_the_cached_config(self):
        Path(self.tmp.name).write_text(
            json.dumps({"late": {"transport": "http", "url": "https://c.example/mcp"}}),
            encoding="utf-8")
        self.assertIn("late", mcp_manager.file_servers())


class OriginIsolationTests(unittest.TestCase):

    def tearDown(self):
        mcp_runtime.shutdown()
        clear_discovered_connectors()

    def _stdio(self, prefix="fixture"):
        return {"transport": "stdio", "command": sys.executable, "args": [FIXTURE, prefix]}

    def test_syncing_the_file_does_not_drop_a_gui_install(self):
        mcp_runtime.add_server("from_gui", self._stdio("gui"), origin="db")
        self.assertIn("from_gui", mcp_runtime.connectors())

        mcp_runtime.sync_origin({"from_file": self._stdio("file")}, origin="file")

        self.assertIn("from_gui", mcp_runtime.connectors())
        self.assertIn("from_file", mcp_runtime.connectors())
        self.assertEqual(mcp_runtime.origin_of("from_gui"), "db")
        self.assertEqual(mcp_runtime.origin_of("from_file"), "file")

    def test_syncing_the_db_does_not_drop_an_operator_server(self):
        mcp_runtime.add_server("from_file", self._stdio("file"), origin="file")
        mcp_runtime.sync_origin({}, origin="db")
        self.assertIn("from_file", mcp_runtime.connectors())

    def test_removing_from_the_file_disconnects_only_that_one(self):
        mcp_runtime.add_server("from_gui", self._stdio("gui"), origin="db")
        mcp_runtime.sync_origin({"from_file": self._stdio("file")}, origin="file")
        mcp_runtime.sync_origin({}, origin="file")
        self.assertNotIn("from_file", mcp_runtime.connectors())
        self.assertIn("from_gui", mcp_runtime.connectors())


if __name__ == "__main__":
    unittest.main(verbosity=2)
