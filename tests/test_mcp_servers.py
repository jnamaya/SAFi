"""
Operator-installed MCP servers (GOVERNANCE_BACKLOG 47b).

Two halves, and the second is the one that matters:

  * Unit coverage of the seams: config parsing, env expansion, connector
    registration precedence, result rendering.

  * A LIVE server. tests/fixture_mcp_server.py is a real MCP server spoken to
    over real stdio, so these tests fail if the session does not stay open
    across calls, if the runtime's event loop and the caller's loop are not
    bridged correctly, or if discovery does not reach the Will. The previous
    implementation would have passed every mock-based test ever written: it
    imported the SDK, constructed StdioServerParameters, and then returned
    without connecting to anything.

The governance assertions are the point of the file:

  * a discovered server is a CONNECTOR, so granting it authorizes its functions
    and nothing else,
  * a server cannot claim a built-in tool name,
  * a tool nobody granted is blocked by the Will even though it is connected,
  * discovery that never ran fails CLOSED rather than open.

Run:  venv/bin/python tests/test_mcp_servers.py
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core import mcp_runtime
from safi_app.core.faculties.synderesis import _stamp_tool_authorization
from safi_app.core.faculties.will import WillGate
from safi_app.core.services import mcp_manager
from safi_app.core.tool_connectors import (
    CONNECTOR_TOOLS,
    clear_discovered_connectors,
    discovered_connectors,
    expand_connectors,
    register_discovered_connector,
)

FIXTURE = str(Path(__file__).resolve().parent / "fixture_mcp_server.py")


def authorize(tool, profile, params=None):
    gate = WillGate(None, values=[], profile={})
    decision, reason = asyncio.run(
        gate.evaluate_tool_intent(tool, params or {}, profile))
    return decision, reason


class ConfigLoadingTests(unittest.TestCase):
    """The server file is read once at import. Every malformed shape must
    degrade to 'no MCP tools', never to a partially-applied config."""

    def _load(self, contents):
        from safi_app.config import _load_mcp_servers
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(contents)
            path = fh.name
        old = os.environ.get("MCP_SERVERS_JSON")
        os.environ["MCP_SERVERS_JSON"] = path
        try:
            return _load_mcp_servers()
        finally:
            if old is None:
                os.environ.pop("MCP_SERVERS_JSON", None)
            else:
                os.environ["MCP_SERVERS_JSON"] = old
            os.unlink(path)

    def test_bare_mapping(self):
        self.assertEqual(
            self._load('{"acme": {"command": "x"}}'),
            {"acme": {"command": "x"}},
        )

    def test_wrapped_mapping(self):
        self.assertEqual(
            self._load('{"mcp_servers": {"acme": {"command": "x"}}}'),
            {"acme": {"command": "x"}},
        )

    def test_empty_file_is_not_an_error(self):
        self.assertEqual(self._load(""), {})

    def test_malformed_json_yields_no_servers(self):
        self.assertEqual(self._load("{not json"), {})

    def test_non_object_yields_no_servers(self):
        self.assertEqual(self._load("[1, 2, 3]"), {})

    def test_missing_file_yields_no_servers(self):
        from safi_app.config import _load_mcp_servers
        old = os.environ.get("MCP_SERVERS_JSON")
        os.environ["MCP_SERVERS_JSON"] = "/nonexistent/path/servers.json"
        try:
            self.assertEqual(_load_mcp_servers(), {})
        finally:
            if old is None:
                os.environ.pop("MCP_SERVERS_JSON", None)
            else:
                os.environ["MCP_SERVERS_JSON"] = old


class EnvExpansionTests(unittest.TestCase):
    """Secrets belong in the environment, not in a file that gets copied."""

    def test_expands_nested_values(self):
        os.environ["SAFI_TEST_TOKEN"] = "s3cret"
        try:
            out = mcp_runtime._expand(
                {"env": {"TOKEN": "${SAFI_TEST_TOKEN}"}, "args": ["--k=${SAFI_TEST_TOKEN}"]}
            )
        finally:
            os.environ.pop("SAFI_TEST_TOKEN", None)
        self.assertEqual(out["env"]["TOKEN"], "s3cret")
        self.assertEqual(out["args"], ["--k=s3cret"])

    def test_unset_variable_expands_to_empty_not_an_exception(self):
        self.assertEqual(mcp_runtime._expand("${SAFI_DEFINITELY_UNSET}"), "")


class ConnectorRegistrationTests(unittest.TestCase):
    """Precedence: built-ins win, and the failure mode is fail-closed."""

    def setUp(self):
        clear_discovered_connectors()

    tearDown = setUp

    def test_discovered_connector_expands_to_its_functions(self):
        register_discovered_connector("acme", ("acme_invoice", "acme_search"))
        self.assertEqual(
            expand_connectors(["acme"]), ["acme_invoice", "acme_search"]
        )

    def test_cannot_shadow_a_builtin_connector(self):
        self.assertFalse(register_discovered_connector("google_drive", ("evil_tool",)))
        self.assertNotIn("google_drive", discovered_connectors())
        # The built-in expansion is untouched.
        self.assertEqual(list(expand_connectors(["google_drive"])), list(CONNECTOR_TOOLS["google_drive"]))

    def test_builtin_table_is_consulted_first(self):
        # Even if a discovered entry somehow existed under a built-in key, the
        # built-in wins at expansion time as well as at registration time.
        from safi_app.core import tool_connectors
        tool_connectors._DISCOVERED["web_search"] = ("impostor",)
        try:
            self.assertEqual(expand_connectors(["web_search"]), ["web_search", "web_news"])
        finally:
            clear_discovered_connectors()

    def test_unknown_name_passes_through_which_is_fail_closed(self):
        # Discovery never ran. The connector name expands to itself, so none of
        # the server's real function names reach allowed_tools, and the Will
        # blocks every call the model makes.
        profile = _stamp_tool_authorization({"tools": ["acme"]})
        self.assertEqual(profile["allowed_tools"], ["acme"])
        decision, _ = authorize("acme_invoice", profile)
        self.assertEqual(decision, "violation")

    def test_empty_function_list_is_refused(self):
        self.assertFalse(register_discovered_connector("acme", ()))


class ResultRenderingTests(unittest.TestCase):
    def test_text_blocks_are_joined(self):
        class Block:
            type = "text"
            text = "hello"

        class Result:
            content = [Block(), Block()]
            structured_content = None
            is_error = False

        self.assertEqual(mcp_runtime._render_result(Result()), "hello\nhello")

    def test_error_results_are_marked(self):
        class Block:
            type = "text"
            text = "boom"

        class Result:
            content = [Block()]
            structured_content = None
            is_error = True

        self.assertTrue(mcp_runtime._render_result(Result()).startswith("ERROR:"))

    def test_structured_content_is_used_when_there_are_no_text_blocks(self):
        class Result:
            content = []
            structured_content = {"total": 3}
            is_error = False

        self.assertIn('"total": 3', mcp_runtime._render_result(Result()))


class LiveServerTests(unittest.TestCase):
    """The real thing: a genuine MCP server over real stdio."""

    @classmethod
    def setUpClass(cls):
        clear_discovered_connectors()
        cls.summary = mcp_runtime.start(
            {"fixture": {
                "label": "Fixture Server",
                "transport": "stdio",
                "command": sys.executable,
                "args": [FIXTURE],
            }},
            reserved_tool_names=mcp_manager.builtin_tool_names(),
        )
        for server, functions in mcp_runtime.connectors().items():
            register_discovered_connector(server, functions)

    @classmethod
    def tearDownClass(cls):
        mcp_runtime.shutdown()
        clear_discovered_connectors()

    def test_server_connected_and_tools_discovered(self):
        entry = self.summary["servers"]["fixture"]
        self.assertIsNone(entry["error"], f"server failed: {entry['error']}")
        self.assertIn("fixture_echo", entry["tools"])
        self.assertIn("fixture_add", entry["tools"])

    def test_a_builtin_name_is_refused_at_discovery(self):
        # The fixture also exposes web_search. It must not have been registered,
        # or a third-party server could repoint an existing agent's tool.
        self.assertNotIn("web_search", mcp_runtime.tools())
        self.assertNotIn("web_search", mcp_runtime.tools_for_server("fixture"))

    def test_schemas_are_real(self):
        spec = mcp_runtime.tools()["fixture_add"]
        self.assertEqual(spec["input_schema"]["type"], "object")
        self.assertIn("a", spec["input_schema"]["properties"])

    def test_call_round_trip(self):
        out = asyncio.run(mcp_runtime.call("fixture_echo", {"message": "hi"}))
        self.assertIn("echo: hi", out)

    def test_session_stays_open_across_calls_on_different_loops(self):
        # Each asyncio.run is a NEW event loop, which is what Flask[async] does
        # per request. If the session were bound to the caller's loop rather
        # than the runtime's, the second call here would fail.
        first = asyncio.run(mcp_runtime.call("fixture_add", {"a": 1, "b": 2}))
        second = asyncio.run(mcp_runtime.call("fixture_add", {"a": 20, "b": 22}))
        self.assertIn("3", first)
        self.assertIn("42", second)

    def test_unknown_tool_returns_an_error_string_not_an_exception(self):
        out = asyncio.run(mcp_runtime.call("no_such_tool", {}))
        self.assertTrue(out.startswith("ERROR:"))

    def test_manager_dispatches_discovered_tools(self):
        manager = mcp_manager.MCPManager({})
        out = asyncio.run(manager.execute_tool("fixture_echo", {"message": "via manager"}))
        self.assertIn("echo: via manager", out)

    def test_manager_advertises_discovered_tools_by_connector_grant(self):
        manager = mcp_manager.MCPManager({})
        schemas = asyncio.run(manager.get_tools_for_agent({"tools": ["fixture"]}))
        names = {s["name"] for s in schemas}
        self.assertIn("fixture_echo", names)
        self.assertIn("fixture_add", names)

    def test_manager_advertises_a_single_function_when_narrowed(self):
        manager = mcp_manager.MCPManager({})
        schemas = asyncio.run(manager.get_tools_for_agent({"tools": ["fixture_echo"]}))
        self.assertEqual({s["name"] for s in schemas}, {"fixture_echo"})

    def test_catalogue_offers_each_tool_separately(self):
        """One card per TOOL, not per server (backlog 48d).

        A built-in connector is offered as a bundle because its contents were
        reviewed when they shipped. A server the operator installed is not: the
        policy step exists so an editor can enable some of its tools and block
        the rest, and a single checkbox for the whole server would make that
        decision unavailable.
        """
        categories = mcp_manager.MCPManager({}).list_all_tools()
        fixture = [c for c in categories if c["category"] == "Fixture Server"]
        self.assertEqual(len(fixture), 1)
        offered = {t["name"] for t in fixture[0]["tools"]}
        self.assertIn("fixture_echo", offered)
        self.assertIn("fixture_add", offered)
        self.assertNotIn("fixture", offered)

    def test_a_policy_can_authorize_one_tool_of_a_server(self):
        """What the per-tool cards are FOR: naming a function directly
        authorizes exactly that function, because expand_connectors passes an
        unknown name through and the Will matches exactly."""
        profile = _stamp_tool_authorization({"tools": ["fixture_echo"]})
        self.assertEqual(profile["allowed_tools"], ["fixture_echo"])
        self.assertEqual(authorize("fixture_echo", profile)[0], "approve")
        self.assertEqual(authorize("fixture_add", profile)[0], "violation")

    # --- the governance assertions ---

    def test_granting_the_server_authorizes_its_functions(self):
        profile = _stamp_tool_authorization({"tools": ["fixture"]})
        self.assertIn("fixture_echo", profile["allowed_tools"])
        self.assertEqual(authorize("fixture_echo", profile)[0], "approve")

    def test_a_connected_tool_nobody_granted_is_still_blocked(self):
        profile = _stamp_tool_authorization({"tools": ["web_search"]})
        decision, reason = authorize("fixture_echo", profile)
        self.assertEqual(decision, "violation")
        self.assertIn("not authorized", reason)

    def test_a_policy_can_narrow_within_a_server(self):
        profile = _stamp_tool_authorization({
            "tools": ["fixture"],
            "will_rules": {"allowed_tools": ["fixture_echo"]},
        })
        self.assertEqual(profile["allowed_tools"], ["fixture_echo"])
        self.assertEqual(authorize("fixture_echo", profile)[0], "approve")
        self.assertEqual(authorize("fixture_add", profile)[0], "violation")

    def test_discovered_tools_take_the_write_path_not_the_fast_pass(self):
        # No promotion mechanism exists on purpose: a server must not be able to
        # declare itself read-only and skip a policy's parameter constraints.
        from safi_app.core.faculties.will import READ_ONLY_TOOLS
        for name in mcp_runtime.tools():
            self.assertNotIn(name, READ_ONLY_TOOLS)

    def test_parameter_constraints_are_enforced_on_a_discovered_tool(self):
        profile = _stamp_tool_authorization({
            "tools": ["fixture"],
            "will_rules": {"tool_parameter_constraints": {"fixture_echo": {"message": ["safe"]}}},
        })
        self.assertEqual(authorize("fixture_echo", profile, {"message": "safe"})[0], "approve")
        self.assertEqual(authorize("fixture_echo", profile, {"message": "other"})[0], "violation")
        # Omitting a constrained parameter is a block, not a bypass.
        self.assertEqual(authorize("fixture_echo", profile, {})[0], "violation")


class ConcurrentProbeTests(unittest.TestCase):
    """Probing has to be concurrent to be usable: most public registry entries
    do not answer, and each failure costs the full timeout, so a catalogue page
    probed one server at a time would take minutes."""

    def tearDown(self):
        mcp_runtime.shutdown()

    def test_probe_reports_tools_without_registering_anything(self):
        result = mcp_runtime.probe(
            {"transport": "stdio", "command": sys.executable, "args": [FIXTURE]}, timeout=20)
        self.assertTrue(result["ok"], result["error"])
        self.assertIn("fixture_echo", result["tools"])
        # A probe must leave no trace: nothing connected, nothing registered.
        self.assertEqual(mcp_runtime.connectors(), {})
        self.assertEqual(mcp_runtime.tools(), {})

    def test_probe_many_returns_one_result_per_key(self):
        results = mcp_runtime.probe_many({
            "good": {"transport": "stdio", "command": sys.executable, "args": [FIXTURE]},
            "bad": {"transport": "stdio", "command": "/nonexistent/binary"},
        }, timeout=20)
        self.assertEqual(set(results), {"good", "bad"})
        self.assertTrue(results["good"]["ok"])
        self.assertFalse(results["bad"]["ok"])
        self.assertTrue(results["bad"]["error"])

    def test_probe_of_a_broken_server_is_not_an_exception(self):
        result = mcp_runtime.probe({"transport": "stdio", "command": "/nonexistent"}, timeout=10)
        self.assertFalse(result["ok"])
        self.assertNotIn("TaskGroup", result["error"])


class BrokenServerTests(unittest.TestCase):
    """A server that cannot start must leave the deployment tool-less, running,
    and fail-closed. Never tool-present-and-unguarded."""

    def tearDown(self):
        mcp_runtime.shutdown()
        clear_discovered_connectors()

    def test_a_server_that_will_not_start_is_skipped(self):
        summary = mcp_runtime.start(
            {"broken": {
                "transport": "stdio",
                "command": "/nonexistent/binary",
                "connect_timeout": 5,
            }},
            reserved_tool_names=frozenset(),
        )
        self.assertEqual(summary["tool_count"], 0)
        self.assertIsNotNone(summary["servers"]["broken"]["error"])
        self.assertEqual(mcp_runtime.connectors(), {})

    def test_start_is_idempotent(self):
        first = mcp_runtime.start({}, reserved_tool_names=frozenset())
        second = mcp_runtime.start(
            {"late": {"transport": "stdio", "command": "/nonexistent"}},
            reserved_tool_names=frozenset(),
        )
        # The second call must not spawn anything: discovery happens once.
        self.assertEqual(first["tool_count"], 0)
        self.assertEqual(second["tool_count"], 0)
        self.assertNotIn("late", second["servers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
