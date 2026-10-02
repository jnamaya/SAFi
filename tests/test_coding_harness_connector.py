#!/usr/bin/env python3
"""Tests for the built-in coding_harness MCP connector.

Two things need locking down here, because both fail silently otherwise:

  1. Vocabulary completeness. WillGate matches tool names EXACTLY, so a name the
     connector omits is a tool the agent can never use — it collects a refusal
     every time it tries. The first real symptom was
     `Tool 'task' is not authorized for this agent profile`. Adding a tool to
     opencode without adding it here reintroduces that bug.

  2. That declaring a tool is not claiming to run it. read/grep/glob/list run
     inside SAFi; the other eleven are opencode's, and execute_tool must say so
     instead of raising or silently returning nothing.

Path confinement gets its own coverage because these tools read the repository
from the app container; a missing check here is arbitrary file read.
"""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, "/app")

from safi_app.core.mcp_servers.coding_harness import (  # noqa: E402
    OPENCODE_TOOL_NAMES,
    SAFI_EXECUTED_TOOLS,
    read_file,
    list_directory,
    grep,
    glob_files,
)
from safi_app.core.services.mcp_manager import (  # noqa: E402
    MCPManager,
    coding_harness_declaration_only,
)


class VocabularyTests(unittest.TestCase):
    def test_covers_opencode_tool_set(self):
        # Pinned deliberately: this is opencode 1.18.34's model-facing tool set.
        # A change here means the vocabulary was edited on purpose.
        self.assertEqual(
            set(OPENCODE_TOOL_NAMES),
            {
                "read", "grep", "glob", "list", "bash", "write", "edit", "patch",
                "webfetch", "websearch", "task", "todowrite", "skill", "lsp",
                "question",
            },
        )

    def test_no_duplicates(self):
        self.assertEqual(len(OPENCODE_TOOL_NAMES), len(set(OPENCODE_TOOL_NAMES)))

    def test_executed_subset_is_real_subset(self):
        self.assertTrue(SAFI_EXECUTED_TOOLS.issubset(set(OPENCODE_TOOL_NAMES)))
        self.assertEqual(SAFI_EXECUTED_TOOLS, {"read", "grep", "glob", "list"})

    def test_manager_expands_to_full_vocabulary(self):
        """The names the agent advertises must equal the vocabulary.

        Anything less and the Will refuses the missing tool by exact match,
        regardless of what the policy allows.
        """
        mgr = MCPManager({})
        tools = asyncio.run(mgr.get_tools_for_agent({"tools": ["coding_harness"]}))
        self.assertEqual(
            {t["name"] for t in tools},
            set(OPENCODE_TOOL_NAMES),
            "connector expansion lost a tool; it will be refused forever",
        )

    def test_policy_intersection_keeps_only_approved_client_tools(self):
        from safi_app.core.faculties.synderesis import _stamp_tool_authorization

        profile = _stamp_tool_authorization({
            "tools": ["coding_harness"],
            "will_rules": {"allowed_tools": ["read", "grep", "task"]},
        }, {"coding_harness": OPENCODE_TOOL_NAMES})
        self.assertEqual(profile["allowed_tools"], ["read", "grep", "task"])

    def test_declaration_only_is_the_complement(self):
        self.assertEqual(
            coding_harness_declaration_only(),
            set(OPENCODE_TOOL_NAMES) - SAFI_EXECUTED_TOOLS,
        )

    def test_every_tool_has_a_schema_with_a_description(self):
        mgr = MCPManager({})
        tools = asyncio.run(mgr.get_tools_for_agent({"tools": ["coding_harness"]}))
        for tool in tools:
            self.assertTrue(tool.get("description"), f"{tool['name']} has no description")
            schema = tool.get("input_schema") or {}
            self.assertEqual(schema.get("type"), "object", tool["name"])

    def test_mutating_and_client_tools_say_who_runs_them(self):
        """The model must not expect SAFi to have executed a client tool."""
        mgr = MCPManager({})
        tools = {t["name"]: t for t in asyncio.run(
            mgr.get_tools_for_agent({"tools": ["coding_harness"]}))}
        for name in sorted(coding_harness_declaration_only()):
            self.assertIn(
                "client", tools[name]["description"].lower(),
                f"{name} does not say the client executes it",
            )

    def test_dispatch_refuses_client_tools_explicitly(self):
        mgr = MCPManager({})
        for name in sorted(coding_harness_declaration_only()):
            out = asyncio.run(mgr.execute_tool(name, {}))
            self.assertIn("executed_by", out, f"{name} produced no structured refusal")
            self.assertIn("client", out)


class PathConfinementTests(unittest.TestCase):
    """SAFI_CODE_REVIEW_ROOT is the only tree these tools may touch."""

    def setUp(self):
        self._saved = os.environ.get("SAFI_CODE_REVIEW_ROOT")
        self._root = "/app" if Path("/app/safi_app").exists() else str(Path(__file__).resolve().parent.parent)
        os.environ["SAFI_CODE_REVIEW_ROOT"] = self._root
        import importlib
        import safi_app.core.mcp_servers.coding_harness as mod
        self.mod = importlib.reload(mod)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SAFI_CODE_REVIEW_ROOT", None)
        else:
            os.environ["SAFI_CODE_REVIEW_ROOT"] = self._saved
        import importlib
        import safi_app.core.mcp_servers.coding_harness as mod
        importlib.reload(mod)

    def test_reads_a_real_file(self):
        out = json.loads(asyncio.run(read_file(f"{self._root}/safi_app/core/mcp_servers/coding_harness.py")))
        self.assertIn("Coding-harness MCP server", out["content"])

    def test_lists_a_real_directory(self):
        out = json.loads(asyncio.run(list_directory(f"{self._root}/safi_app/core/mcp_servers")))
        self.assertTrue(any(e["name"] == "coding_harness.py" for e in out["entries"]))

    def test_glob_and_grep_find_real_content(self):
        out = json.loads(asyncio.run(glob_files("**/*.py", f"{self._root}/safi_app/core/mcp_servers")))
        self.assertGreater(out["file_count"], 0)
        self.assertTrue(any(f.endswith("coding_harness.py") for f in out["files"]))
        found = json.loads(asyncio.run(grep("SAFI_EXECUTED_TOOLS", f"{self._root}/safi_app/core/mcp_servers")))
        self.assertGreater(found["match_count"], 0)

    def test_recursive_pattern_matches_depth_zero_too(self):
        """`**/` means zero or more directories.

        Regression: `_walk` matches against the path relative to the SEARCH
        SCOPE, so `**/*.py` was asked to match "coding_harness.py" — no separator,
        no match, zero results, while `*.py` found the same files. The pattern a
        model reaches for first silently returned nothing.
        """
        scope = f"{self._root}/safi_app/core/mcp_servers"
        recursive = json.loads(asyncio.run(glob_files("**/*.py", scope)))
        shallow = json.loads(asyncio.run(glob_files("*.py", scope)))
        self.assertEqual(recursive["file_count"], shallow["file_count"])
        self.assertGreater(recursive["file_count"], 0)

    def test_traversal_outside_root_is_refused(self):
        for bad in (
            "/etc/passwd",
            f"{self._root}/../../etc/passwd",
            "../../../etc/shadow",
            f"{self._root}/safi_app/../../etc/hosts",
        ):
            out = json.loads(asyncio.run(read_file(bad)))
            self.assertIn("error", out, f"{bad} was not refused")
            self.assertNotIn("root:", out.get("error", ""))

    def test_secret_and_dotfiles_are_refused_or_absent(self):
        """A hidden path must never yield file contents.

        These may legitimately not exist in the container; what matters is that
        if one does, it is refused rather than read.
        """
        for bad in (f"{self._root}/.env", f"{self._root}/.git/config", f"{self._root}/.ssh/id_rsa"):
            out = json.loads(asyncio.run(read_file(bad)))
            if "error" not in out:
                self.fail(f"{bad} was read instead of refused")
            self.assertNotIn("API", out.get("error", ""))
            self.assertNotIn("-----BEGIN", out.get("error", ""))

    def test_refusals_also_apply_to_grep_and_glob(self):
        """A confinement check on `read` alone is not confinement."""
        for coro in (grep("root", "/etc"), glob_files("**/*", "/etc")):
            self.assertIn("error", json.loads(asyncio.run(coro)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
