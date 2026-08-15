"""
Connector-level authorization: the wizard grants "sharepoint", the model calls
"sharepoint_read", and the Will matches exactly.

Before the fix, mcp_manager expanded connector names into per-function schemas
while WillGate compared the function name against the unexpanded list. An agent
granted "sharepoint" was therefore offered four tools and could use none of them.
sharepoint (7 functions) and google_drive (3) were dead the same way, and
web_news was blocked while web_search worked. The connectors that appeared to
work did so only because their single function shared the connector's name.

The load-bearing test here is test_mapping_matches_the_real_builder: it calls the
actual mcp_manager schema builder for every connector and asserts the emitted
names match CONNECTOR_TOOLS. Adding a function to a connector without updating
the table fails here rather than silently shipping an unauthorizable tool.

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


class TestConnectorGrantAuthorizesItsFunctions(unittest.TestCase):

    def test_every_function_of_every_connector_is_authorized(self):
        for connector, functions in CONNECTOR_TOOLS.items():
            profile = compile_profile([connector])
            for fn in functions:
                with self.subTest(connector=connector, tool=fn):
                    self.assertNotEqual(
                        authorize(fn, profile), "violation",
                        f"granting '{connector}' must authorize '{fn}'")

    def test_the_reported_failure(self):
        # Nelson's exact case: tools_json ["web_search", "sharepoint"], no policy
        # narrowing, model proposes github_get_repo.
        profile = compile_profile(["web_search", "sharepoint"])
        self.assertNotEqual(authorize("sharepoint_read", profile), "violation")

    def test_web_news_no_longer_blocked(self):
        # In READ_ONLY_TOOLS, but the allow-list is checked before the fast pass,
        # so it was rejected before it could be fast-passed.
        profile = compile_profile(["web_search"])
        self.assertEqual(authorize("web_news", profile), "approve")


class TestExpansionDoesNotOverGrant(unittest.TestCase):

    def test_ungranted_connector_still_blocked(self):
        profile = compile_profile(["web_search"])
        for fn in ("sharepoint_upload", "google_upload_file", "send_email"):
            with self.subTest(tool=fn):
                self.assertEqual(authorize(fn, profile), "violation")

    def test_no_tools_is_deny_all(self):
        profile = compile_profile([])
        self.assertEqual(profile["allowed_tools"], [])
        self.assertEqual(authorize("sharepoint_read", profile), "violation")

    def test_hallucinated_tool_name_blocked(self):
        profile = compile_profile(["sharepoint"])
        self.assertEqual(authorize("sharepoint_delete", profile), "violation")

    def test_policy_can_narrow_within_a_connector(self):
        # Agent granted all of SharePoint, policy permits only the search.
        profile = compile_profile(["sharepoint"], policy_allowed=["sharepoint_search"])
        self.assertEqual(profile["allowed_tools"], ["sharepoint_search"])
        self.assertNotEqual(authorize("sharepoint_search", profile), "violation")
        self.assertEqual(authorize("sharepoint_read", profile), "violation")

    def test_policy_cannot_grant_what_the_agent_lacks(self):
        profile = compile_profile(["web_search"], policy_allowed=["sharepoint", "web_search"])
        self.assertNotIn("sharepoint_read", profile["allowed_tools"])
        self.assertEqual(authorize("sharepoint_read", profile), "violation")


class TestExpandConnectors(unittest.TestCase):

    def test_order_preserved_and_deduped(self):
        self.assertEqual(
            expand_connectors(["web_search", "sharepoint", "web_search"]),
            ["web_search", "web_news",
             "sharepoint_search", "sharepoint_read", "sharepoint_upload",
             "sharepoint_search_sites", "sharepoint_search_site_files",
             "sharepoint_list_folders", "sharepoint_get_tree"])

    def test_unknown_names_pass_through(self):
        self.assertEqual(expand_connectors(["send_email"]), ["send_email"])

    def test_non_strings_ignored(self):
        self.assertEqual(expand_connectors(["sharepoint", None, 7]),
                         list(CONNECTOR_TOOLS["sharepoint"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
