"""
Connector-level authorization: the wizard grants "web_search", the model calls
"web_news", and the Will matches exactly.

Before the fix, mcp_manager expanded connector names into per-function schemas
while WillGate compared the function name against the unexpanded list. An agent
granted a multi-function connector was offered its tools and could use none of
them; web_news was blocked while web_search worked. The connectors that
appeared to work did so only because their single function shared the
connector's name. (The three multi-function connectors that motivated the fix,
github, google_drive and sharepoint, all retired 2026-08-15 in favour of MCP
servers; web_search is the multi-function case that remains, and the mechanism
now also governs every discovered server.)

The load-bearing test here is test_mapping_matches_the_real_builder: it calls the
actual mcp_manager schema builder for every connector and asserts the emitted
names match CONNECTOR_TOOLS. Adding a function to a connector without updating
the table fails here rather than silently shipping an unauthorizable tool.

The retired names earn their own tests. "sharepoint" survives in agents'
stored tools_json; it must expand to itself, authorize nothing callable, and
never resurrect the old functions.

Run:  venv/bin/python tests/test_tool_connector_expansion.py
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.will import WillGate
from safi_app.core.faculties.synderesis import _stamp_tool_authorization
from safi_app.core.tool_connectors import CONNECTOR_TOOLS, expand_connectors


def compile_profile(tools, policy_allowed=None):
    """What synderesis stamps for an agent granted `tools`."""
    profile = {"tools": list(tools)}
    if policy_allowed is not None:
        profile["will_rules"] = {"allowed_tools": list(policy_allowed)}
    return _stamp_tool_authorization(profile)


def authorize(tool, profile, params=None):
    gate = WillGate(None, values=[], profile={})
    decision, _ = asyncio.run(
        gate.evaluate_tool_intent(tool, params or {}, profile))
    return decision


class TestMappingIsPinnedToReality(unittest.TestCase):

    def test_mapping_matches_the_real_builder(self):
        # Calls production mcp_manager, not a copy of its table.
        from safi_app.core.services.mcp_manager import MCPManager
        mgr = MCPManager({})

        async def emitted(connector):
            schemas = await mgr.get_tools_for_agent({"tools": [connector]})
            return [s["name"] for s in schemas]

        for connector, expected in CONNECTOR_TOOLS.items():
            with self.subTest(connector=connector):
                actual = asyncio.run(emitted(connector))
                self.assertEqual(
                    actual, list(expected),
                    f"CONNECTOR_TOOLS['{connector}'] is out of step with "
                    f"mcp_manager. Builder emits {actual}. Any name missing from "
                    f"the table cannot be authorized by the Will.")

    def test_every_gated_connector_appears_in_the_table(self):
        # A connector the builder gates on but the table omits would expand to
        # itself, which authorizes nothing callable.
        import re
        src = (Path(__file__).resolve().parent.parent
               / "safi_app/core/services/mcp_manager.py").read_text(encoding="utf-8")
        gated = set(re.findall(r'if "([a-z0-9_]+)" in allowed_tools:', src))
        missing = gated - set(CONNECTOR_TOOLS)
        self.assertEqual(missing, set(),
                         f"connectors gated in mcp_manager but absent from "
                         f"CONNECTOR_TOOLS: {sorted(missing)}")

    def test_retired_connectors_stay_retired(self):
        # The builder must not gate on a retired name, and the table must not
        # carry one. A reappearance here means someone resurrected a built-in
        # whose successor is an MCP server.
        for retired in ("github", "google_drive", "sharepoint"):
            with self.subTest(connector=retired):
                self.assertNotIn(retired, CONNECTOR_TOOLS)


class TestConnectorGrantAuthorizesItsFunctions(unittest.TestCase):

    def test_every_function_of_every_connector_is_authorized(self):
        for connector, functions in CONNECTOR_TOOLS.items():
            profile = compile_profile([connector])
            for fn in functions:
                with self.subTest(connector=connector, tool=fn):
                    self.assertNotEqual(
                        authorize(fn, profile), "violation",
                        f"granting '{connector}' must authorize '{fn}'")

    def test_web_news_no_longer_blocked(self):
        # In READ_ONLY_TOOLS, but the allow-list is checked before the fast pass,
        # so it was rejected before it could be fast-passed.
        profile = compile_profile(["web_search"])
        self.assertEqual(authorize("web_news", profile), "approve")


class TestRetiredKeysFailClosed(unittest.TestCase):
    """Agents' tools_json still carries the retired names. Each must be inert:
    expand to itself, authorize none of its old functions, and leave the
    connectors that still exist unaffected."""

    def test_a_stored_retired_grant_authorizes_nothing(self):
        profile = compile_profile(["web_search", "sharepoint"])
        self.assertEqual(authorize("web_news", profile), "approve")
        for old_fn in ("sharepoint_read", "sharepoint_search", "sharepoint_upload"):
            with self.subTest(tool=old_fn):
                self.assertEqual(authorize(old_fn, profile), "violation")

    def test_retired_names_expand_to_themselves(self):
        for retired in ("github", "google_drive", "sharepoint"):
            with self.subTest(connector=retired):
                self.assertEqual(expand_connectors([retired]), [retired])


class TestExpansionDoesNotOverGrant(unittest.TestCase):

    def test_ungranted_function_still_blocked(self):
        profile = compile_profile(["web_search"])
        for fn in ("find_places", "send_files", "send_email"):
            with self.subTest(tool=fn):
                self.assertEqual(authorize(fn, profile), "violation")

    def test_no_tools_is_deny_all(self):
        profile = compile_profile([])
        self.assertEqual(profile["allowed_tools"], [])
        self.assertEqual(authorize("web_search", profile), "violation")

    def test_hallucinated_tool_name_blocked(self):
        profile = compile_profile(["web_search"])
        self.assertEqual(authorize("web_delete_history", profile), "violation")

    def test_policy_can_narrow_within_a_connector(self):
        # Agent granted both search tools, policy permits only the news one.
        profile = compile_profile(["web_search"], policy_allowed=["web_news"])
        self.assertEqual(profile["allowed_tools"], ["web_news"])
        self.assertNotEqual(authorize("web_news", profile), "violation")
        self.assertEqual(authorize("web_search", profile), "violation")

    def test_policy_cannot_grant_what_the_agent_lacks(self):
        profile = compile_profile(["find_places"],
                                  policy_allowed=["web_search", "find_places"])
        self.assertNotIn("web_news", profile["allowed_tools"])
        self.assertEqual(authorize("web_news", profile), "violation")


class TestExpandConnectors(unittest.TestCase):

    def test_order_preserved_and_deduped(self):
        self.assertEqual(
            expand_connectors(["find_places", "web_search", "find_places"]),
            ["find_places", "web_search", "web_news"])

    def test_unknown_names_pass_through(self):
        self.assertEqual(expand_connectors(["send_email"]), ["send_email"])

    def test_non_strings_ignored(self):
        self.assertEqual(expand_connectors(["web_search", None, 7]),
                         list(CONNECTOR_TOOLS["web_search"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
