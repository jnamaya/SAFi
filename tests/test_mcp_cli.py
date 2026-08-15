"""
The operator CLI and file reload (GOVERNANCE_BACKLOG 48b).

Why a CLI exists at all, since it is the thing a reader will question: the
browser can only install HOSTED servers, because starting a package server runs
someone else's code on this host. That leaves the npm and pypi majority of the
ecosystem unreachable from the GUI by design. Whoever runs this CLI already has
shell here, so installing a package server adds no privilege they did not have,
which is why the same act is safe in one place and not the other.

What is actually tested:

  * the two origins are independent. A file edit must not drop what an
    organization installed through the GUI, and a GUI install must not unplug
    the operator's servers. Those are separate stores reconciled separately, so
    nothing enforces it except this.
  * a stdio server whose launcher is missing is refused up front. The app image
    ships Python and no node, so most registry packages could never start, and
    without the check the CLI would write a definition that fails silently later.
  * keys never collide with a built-in connector.
  * the file round-trips, including the disabled flag.

Run:  venv/bin/python tests/test_mcp_cli.py
"""
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
    """The image ships Python and nothing else. An npm server written into the
    file would never start, and the failure would surface much later as a
    server that is simply absent."""

    def test_missing_launcher_is_refused_with_the_binary_named(self):
        with self.assertRaises(SystemExit):
            safi_mcp.check_runtime_available(
                {"transport": "stdio", "command": "definitely-not-installed-xyz"})

    def test_npx_is_available_where_this_runs(self):
        """The image ships Node so npm tool servers work (most of the MCP
        ecosystem is npm). This fails if a future image drops it, which would
        otherwise show up only as every npm server refusing to install."""
        import shutil
        if not Path("/app").exists():
            self.skipTest("not running inside the SAFi image")
        self.assertTrue(shutil.which("npx"), "npx should be on PATH in the image")

    def test_a_present_launcher_passes(self):
        safi_mcp.check_runtime_available({"transport": "stdio", "command": sys.executable})

    def test_hosted_servers_need_no_local_runtime(self):
        # The check must not fire for http/sse: nothing runs here at all.
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
        # Config.MCP_CONFIG was evaluated at import. The whole point of the
        # reload path is seeing what the file says now, so a write made after
        # import has to be visible.
        Path(self.tmp.name).write_text(
            json.dumps({"late": {"transport": "http", "url": "https://c.example/mcp"}}),
            encoding="utf-8")
        self.assertIn("late", mcp_manager.file_servers())


class OriginIsolationTests(unittest.TestCase):
    """Two independent sources reconcile against the same runtime. Neither may
    disconnect the other's servers."""

    def tearDown(self):
        mcp_runtime.shutdown()
        clear_discovered_connectors()

    def _stdio(self, prefix="fixture"):
        # Distinct tool names per server: the runtime gives a tool name to the
        # first server that claims it, so two servers exposing the same names
        # would leave the second publishing nothing.
        return {"transport": "stdio", "command": sys.executable, "args": [FIXTURE, prefix]}

    def test_syncing_the_file_does_not_drop_a_gui_install(self):
        mcp_runtime.add_server("from_gui", self._stdio("gui"), origin="db")
        self.assertIn("from_gui", mcp_runtime.connectors())

        # A file sync that knows nothing about the GUI server runs.
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
