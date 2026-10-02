"""Unit tests for the native SAFi CLI local tools and configuration."""

import os
import tempfile
import unittest
from pathlib import Path

from safi_cli.tools import execute_tool, resolve_safe_path
from safi_cli import config


class TestSafiCliTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "test.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=123", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_safe_path_resolution(self):
        # Normal path
        p = resolve_safe_path("src/test.py", self.root)
        self.assertEqual(p, (self.root / "src" / "test.py").resolve())

        # Path traversal refused
        with self.assertRaises(PermissionError):
            resolve_safe_path("../../etc/passwd", self.root)

        # Secret file refused
        with self.assertRaises(PermissionError):
            resolve_safe_path(".env", self.root)

    def test_read_tool(self):
        out = execute_tool("read", {"path": "src/test.py"}, self.root)
        self.assertIn("1: def hello():", out)
        self.assertIn("2:     return 'world'", out)

    def test_list_tool(self):
        out = execute_tool("list", {"path": "."}, self.root)
        self.assertIn("src/", out)
        self.assertNotIn(".env", out)

    def test_glob_tool(self):
        out = execute_tool("glob", {"pattern": "*.py", "path": "src"}, self.root)
        self.assertIn("src/test.py", out)

    def test_grep_tool(self):
        out = execute_tool("grep", {"pattern": "return 'world'"}, self.root)
        self.assertIn("src/test.py:2:", out)

    def test_edit_tool(self):
        out = execute_tool(
            "edit",
            {"path": "src/test.py", "target": "'world'", "replacement": "'safi'"},
            self.root,
        )
        self.assertIn("Successfully applied edit", out)
        content = (self.root / "src" / "test.py").read_text()
        self.assertIn("'safi'", content)

    def test_write_tool(self):
        out = execute_tool("write", {"path": "src/new.txt", "content": "hello safi"}, self.root)
        self.assertIn("Successfully wrote", out)
        self.assertTrue((self.root / "src" / "new.txt").exists())
        self.assertEqual((self.root / "src" / "new.txt").read_text(), "hello safi")

    def test_bash_tool(self):
        out = execute_tool("bash", {"command": "echo 'running bash'"}, self.root)
        self.assertIn("running bash", out)
        self.assertIn("Exit code 0", out)


class TestSafiCliConfig(unittest.TestCase):
    def test_resolve_api_url_default(self):
        url = config.resolve_api_url(None)
        self.assertTrue(url.startswith("http"))

    def test_session_id_is_stable_for_same_root(self):
        s1 = config.resolve_session_id("/tmp/test_repo", new_session=False)
        s2 = config.resolve_session_id("/tmp/test_repo", new_session=False)
        self.assertEqual(s1, s2)

        s3 = config.resolve_session_id("/tmp/test_repo", new_session=True)
        self.assertNotEqual(s1, s3)


from unittest.mock import MagicMock
from safi_cli.main import run_agent_turn, DEFAULT_MAX_STEPS


class TestSafiCliTurn(unittest.TestCase):
    def test_run_agent_turn_respects_max_steps(self):
        client = MagicMock()
        # Simulate continuous tool calls without a terminal answer
        client.send_turn.return_value = {
            "type": "tool_call",
            "tool_name": "list",
            "parameters": {"path": "."},
            "willDecision": "approve",
        }
        res = run_agent_turn(
            client=client,
            prompt="test prompt",
            workspace_root=Path("."),
            conversation_id="test-conv",
            user_id="test-user",
            agent="coding_harness",
            auto_approve=True,
            max_steps=2,
        )
        self.assertIsNone(res)
        self.assertEqual(client.send_turn.call_count, 2)

    def test_run_agent_turn_terminal_response(self):
        client = MagicMock()
        client.send_turn.return_value = {
            "type": "response",
            "finalOutput": "Hello developer!",
            "willDecision": "approve",
            "conscienceLedger": [],
        }
        res = run_agent_turn(
            client=client,
            prompt="hello",
            workspace_root=Path("."),
            conversation_id="test-conv",
            user_id="test-user",
            agent="coding_harness",
            auto_approve=True,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("finalOutput"), "Hello developer!")
        self.assertEqual(client.send_turn.call_count, 1)


    def test_run_agent_turn_auto_approves_by_default(self):
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "list",
                "parameters": {"path": "."},
                "willDecision": "approve",
            },
            {
                "type": "response",
                "finalOutput": "Done listing.",
                "willDecision": "approve",
                "conscienceLedger": [],
            },
        ]
        # Notice auto_approve is not passed, relying on default True
        res = run_agent_turn(
            client=client,
            prompt="list files",
            workspace_root=Path("."),
            conversation_id="test-conv",
            user_id="test-user",
            agent="coding_harness",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("finalOutput"), "Done listing.")
        self.assertEqual(client.send_turn.call_count, 2)


if __name__ == "__main__":
    unittest.main()
