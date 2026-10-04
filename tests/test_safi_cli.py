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
            agent="software_engineer",
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
            agent="software_engineer",
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
            agent="software_engineer",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("finalOutput"), "Done listing.")
        self.assertEqual(client.send_turn.call_count, 2)


from unittest.mock import patch
from safi_cli.main import prompt_switch_agent, prompt_command_menu, AVAILABLE_AGENTS



class TestSafiCliAgentSwitching(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cfg_file = Path(self.temp_dir.name) / "config.json"
        self.patch_cfg = patch.object(config, "CONFIG_FILE", self.cfg_file)
        self.patch_cfg_dir = patch.object(config, "CONFIG_DIR", Path(self.temp_dir.name))
        self.patch_cfg.start()
        self.patch_cfg_dir.start()

    def tearDown(self):
        self.patch_cfg.stop()
        self.patch_cfg_dir.stop()
        self.temp_dir.cleanup()

    def test_per_agent_key_storage_and_resolution(self):
        # Save key for fiduciary
        config.save_agent_api_key("fiduciary", "sk-fiduciary-123")
        # Save key for software_engineer
        config.save_agent_api_key("software_engineer", "sk-coding-456")

        self.assertEqual(config.resolve_agent_api_key("fiduciary"), "sk-fiduciary-123")
        self.assertEqual(config.resolve_agent_api_key("software_engineer"), "sk-coding-456")
        self.assertIsNone(config.resolve_agent_api_key("health_navigator"))

        # Test environment variable override
        with patch.dict(os.environ, {"SAFI_API_KEY_HEALTH_NAVIGATOR": "sk-env-health"}):
            self.assertEqual(config.resolve_agent_api_key("health_navigator"), "sk-env-health")

    def test_prompt_switch_agent_with_existing_key(self):
        config.save_agent_api_key("fiduciary", "sk-fiduciary-key")
        client = MagicMock()
        client.api_key = "old-key"

        new_agent, new_conv = prompt_switch_agent(
            current_agent="software_engineer",
            client=client,
            workspace_root=Path("."),
            requested_agent="fiduciary",
        )

        self.assertEqual(new_agent, "fiduciary")
        self.assertEqual(client.api_key, "sk-fiduciary-key")
        self.assertIsNotNone(new_conv)

    def test_prompt_switch_agent_prompts_and_saves_missing_key(self):
        client = MagicMock()
        client.api_key = "coding-key"

        with patch("builtins.input", return_value="sk-new-financial-key"):
            new_agent, new_conv = prompt_switch_agent(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                requested_agent="fiduciary",
            )

        self.assertEqual(new_agent, "fiduciary")
        self.assertEqual(client.api_key, "sk-new-financial-key")
        # Check saved to config
        saved_key = config.resolve_agent_api_key("fiduciary")
        self.assertEqual(saved_key, "sk-new-financial-key")

    def test_prompt_switch_agent_via_number_selection(self):
        config.save_agent_api_key("fiduciary", "sk-fiduciary-key")
        client = MagicMock()
        client.api_key = "coding-key"

        # "2" corresponds to fiduciary in AVAILABLE_AGENTS
        with patch("builtins.input", return_value="2"):
            new_agent, new_conv = prompt_switch_agent(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                requested_agent=None,
            )

        self.assertEqual(new_agent, "fiduciary")
        self.assertEqual(client.api_key, "sk-fiduciary-key")

    def test_prompt_switch_agent_cancelled_on_empty_choice(self):
        client = MagicMock()
        client.api_key = "coding-key"

        with patch("builtins.input", return_value=""):
            new_agent, new_conv = prompt_switch_agent(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                requested_agent=None,
            )

        # Should remain on current agent
        self.assertEqual(new_agent, "software_engineer")
        self.assertEqual(client.api_key, "coding-key")

    def test_prompt_switch_agent_cancelled_on_empty_key_input(self):
        client = MagicMock()
        client.api_key = "coding-key"

        # User chooses fiduciary (2), but presses Enter when asked for key
        with patch("builtins.input", side_effect=["2", ""]):
            new_agent, new_conv = prompt_switch_agent(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                requested_agent=None,
            )

        self.assertEqual(new_agent, "software_engineer")
        self.assertEqual(client.api_key, "coding-key")

    def test_prompt_command_menu_exit(self):
        client = MagicMock()
        with patch("builtins.input", return_value="6"):
            agent, conv, should_exit = prompt_command_menu(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                current_conv="conv-1",
            )
        self.assertTrue(should_exit)

    def test_prompt_command_menu_new(self):
        client = MagicMock()
        with patch("builtins.input", return_value="new"):
            agent, conv, should_exit = prompt_command_menu(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                current_conv="conv-1",
            )
        self.assertFalse(should_exit)
        self.assertNotEqual(conv, "conv-1")

    def test_prompt_command_menu_cancel(self):
        client = MagicMock()
        with patch("builtins.input", return_value=""):
            agent, conv, should_exit = prompt_command_menu(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                current_conv="conv-1",
            )
        self.assertFalse(should_exit)
        self.assertEqual(agent, "software_engineer")
        self.assertEqual(conv, "conv-1")


from safi_cli.main import DEFAULT_AGENTS, discover_agents
from safi_cli.client import SafiClient


class TestSafiCliDynamicAgentDiscovery(unittest.TestCase):
    def setUp(self):
        AVAILABLE_AGENTS.clear()
        AVAILABLE_AGENTS.update(DEFAULT_AGENTS)

    def tearDown(self):
        AVAILABLE_AGENTS.clear()
        AVAILABLE_AGENTS.update(DEFAULT_AGENTS)

    @patch("requests.get")
    def test_client_get_available_agents_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "available": [
                {"key": "software_engineer", "name": "Software Engineer", "description": "Eng"},
                {"key": "custom_financial_bot", "name": "Custom Financial Bot", "description": "Org Bot"},
            ],
        }
        mock_get.return_value = mock_resp

        client = SafiClient("https://safi.demo.com", "sk-safi-key123")
        agents = client.get_available_agents()

        self.assertEqual(len(agents), 2)
        self.assertEqual(agents[1]["key"], "custom_financial_bot")
        mock_get.assert_called_once_with(
            "https://safi.demo.com/api/agents/all",
            headers={"X-API-KEY": "sk-safi-key123"},
            timeout=5,
        )

    @patch("requests.get")
    def test_client_get_available_agents_fallback_route(self, mock_get):
        mock_404 = MagicMock()
        mock_404.status_code = 404

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "ok": True,
            "available": [{"key": "remote_agent", "name": "Remote Agent"}],
        }
        mock_get.side_effect = [mock_404, mock_200]

        client = SafiClient("https://safi.demo.com")
        agents = client.get_available_agents()

        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["key"], "remote_agent")
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.get", side_effect=Exception("Connection refused"))
    def test_client_get_available_agents_error_returns_empty(self, mock_get):
        client = SafiClient("https://offline-instance.local")
        agents = client.get_available_agents()
        self.assertEqual(agents, [])

    def test_discover_agents_updates_available_agents(self):
        client = MagicMock()
        client.get_available_agents.return_value = [
            {"key": "marketing_writer", "name": "Marketing Copywriter", "description": "Writes copy"},
            {"key": "sec_auditor", "name": "SEC Auditor", "description": "Financial compliance"},
        ]

        discovered = discover_agents(client)
        self.assertEqual(len(discovered), 2)
        self.assertIn("marketing_writer", AVAILABLE_AGENTS)
        self.assertEqual(AVAILABLE_AGENTS["marketing_writer"]["title"], "Marketing Copywriter")
        self.assertIn("sec_auditor", AVAILABLE_AGENTS)
        self.assertNotIn("software_engineer", AVAILABLE_AGENTS)

    def test_url_switching_discovers_instance_specific_agents(self):
        # Instance 1: safi.demo.com
        client_demo = MagicMock()
        client_demo.api_url = "https://safi.demo.com"
        client_demo.get_available_agents.return_value = [
            {"key": "demo_specialist", "name": "Demo Specialist", "description": "On demo.com"},
        ]
        discover_agents(client_demo)
        self.assertIn("demo_specialist", AVAILABLE_AGENTS)
        self.assertEqual(list(AVAILABLE_AGENTS.keys()), ["demo_specialist"])

        # Instance 2: safi.demo1.com
        client_demo1 = MagicMock()
        client_demo1.api_url = "https://safi.demo1.com"
        client_demo1.get_available_agents.return_value = [
            {"key": "demo1_analyst", "name": "Demo1 Analyst", "description": "On demo1.com"},
            {"key": "demo1_coder", "name": "Demo1 Coder", "description": "On demo1.com"},
        ]
        discover_agents(client_demo1)
        self.assertNotIn("demo_specialist", AVAILABLE_AGENTS)
        self.assertIn("demo1_analyst", AVAILABLE_AGENTS)
        self.assertIn("demo1_coder", AVAILABLE_AGENTS)

    def test_prompt_switch_agent_with_dynamically_discovered_agent(self):
        client = MagicMock()
        client.api_url = "https://safi.demo1.com"
        client.api_key = "current-key"
        client.get_available_agents.return_value = [
            {"key": "billing_auditor", "name": "Billing Auditor", "description": "Audits bills"},
        ]

        with patch("safi_cli.config.resolve_agent_api_key", return_value="sk-billing-key"):
            new_agent, _ = prompt_switch_agent(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                requested_agent="billing_auditor",
            )

        self.assertEqual(new_agent, "billing_auditor")
        self.assertEqual(client.api_key, "sk-billing-key")


class TestSafiClientToolPayload(unittest.TestCase):
    @patch("requests.post")
    def test_send_turn_includes_tools_for_software_engineer(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "finalOutput": "Done"}
        mock_post.return_value = mock_resp

        client = SafiClient("https://safi.test", "sk-test")
        client.send_turn(
            user_id="u1",
            conversation_id="c1",
            message="Inspect repo",
            workspace_root="/tmp/repo",
            agent="software_engineer",
        )

        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertIsNotNone(payload.get("tools"))
        tool_names = [t["function"]["name"] for t in payload["tools"]]
        self.assertIn("read", tool_names)
        self.assertIn("write", tool_names)

    @patch("requests.post")
    def test_send_turn_omits_tools_for_fiduciary(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "finalOutput": "Market analysis"}
        mock_post.return_value = mock_resp

        client = SafiClient("https://safi.test", "sk-test")
        client.send_turn(
            user_id="u1",
            conversation_id="c1",
            message="What is AAPL price?",
            workspace_root="/tmp/repo",
            agent="fiduciary",
        )

        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertIsNone(payload.get("tools"))


if __name__ == "__main__":
    unittest.main()




