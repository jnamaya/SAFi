"""Unit tests for the native SAFi CLI local tools and configuration."""

import os
import subprocess
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
    def test_send_turn_sends_empty_tools_for_fiduciary(self, mock_post):
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
        self.assertEqual(payload.get("tools"), [])

    @patch("safi_cli.ui.print_tool_proposal")
    @patch("safi_cli.ui.print_tool_result_summary")
    @patch("safi_cli.ui.print_final_output")
    def test_run_agent_turn_executes_server_tool_step_by_step(self, mock_final, mock_summary, mock_proposal):
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "get_stock_price",
                "parameters": {"ticker": "TSLA"},
                "willDecision": "approve",
                "executed_by": "server",
                "result": '{"symbol": "TSLA", "current_price": 370.59}',
            },
            {
                "type": "response",
                "finalOutput": "Tesla is trading at $370.59.",
                "toolCalls": [
                    {
                        "tool": "get_stock_price",
                        "params": {"ticker": "TSLA"},
                        "decision": "approve",
                        "result": '{"symbol": "TSLA", "current_price": 370.59}',
                    }
                ],
                "willDecision": "approve",
            },
        ]
        res = run_agent_turn(
            client=client,
            prompt="how is Tesla doing?",
            workspace_root=Path("."),
            conversation_id="c-tsla",
            user_id="u-tsla",
            agent="fiduciary",
        )
        self.assertIsNotNone(res)
        self.assertEqual(client.send_turn.call_count, 2)
        # Verify proposal and summary printed once during step-by-step loop
        mock_proposal.assert_called_once()
        mock_summary.assert_called_once_with("get_stock_price", '{"symbol": "TSLA", "current_price": 370.59}')
        mock_final.assert_called_once()
        # Verify tool_results sent in the second turn
        second_call_kwargs = client.send_turn.call_args_list[1].kwargs
        self.assertEqual(len(second_call_kwargs["tool_results"]), 1)
        self.assertEqual(second_call_kwargs["tool_results"][0]["tool_name"], "get_stock_price")

    @patch("safi_cli.ui.print_tool_proposal")
    @patch("safi_cli.ui.print_tool_result_summary")
    @patch("safi_cli.ui.print_final_output")
    def test_run_agent_turn_displays_server_tool_calls(self, mock_final, mock_summary, mock_proposal):
        client = MagicMock()
        client.send_turn.return_value = {
            "type": "response",
            "finalOutput": "NVDA is $120.",
            "toolCalls": [
                {
                    "tool": "get_stock_price",
                    "params": {"ticker": "NVDA"},
                    "decision": "approve",
                    "reason": "Authorized tool",
                    "result": "{\"price\": 120.0}",
                }
            ],
            "willDecision": "approve",
        }
        res = run_agent_turn(
            client=client,
            prompt="NVDA price?",
            workspace_root=Path("."),
            conversation_id="c-1",
            user_id="u-1",
            agent="fiduciary",
        )
        self.assertIsNotNone(res)
        mock_proposal.assert_called_once_with(
            "get_stock_price",
            {"ticker": "NVDA"},
            {"willDecision": "approve", "willReason": "Authorized tool", "toolProposalLedger": []},
        )
        mock_summary.assert_called_once_with("get_stock_price", '{"price": 120.0}')
        mock_final.assert_called_once()

    def test_ui_banner_and_audit_details(self):
        from safi_cli import ui
        # Verify banner runs cleanly with and without intellect_model
        ui.print_banner("/tmp/repo", "software_engineer", "http://localhost:5000", user_name="Alice", intellect_model="claude-3-5-sonnet")

        # Verify audit details formatting for all score tiers
        test_payload = {
            "policyName": "Agentic Coding Policy",
            "conscienceLedger": [
                {"value": "Non-Destructive Operations", "score": 0.85, "rationale": "Read-only exploration"},
                {"value": "Scope Compliance", "score": -0.2, "rationale": "Accessed unexpected path"},
            ],
            "spirit_score": 8.2,
            "spiritNote": "Alignment 8/10, drift low.",
        }
        ui.print_audit_details(test_payload)
        self.assertIsNotNone(ui.COLOR_BRAND_600)
        self.assertEqual(ui.COLOR_BRAND_600, "#16a34a")

        # Green tier (>= 7.0)
        ui.print_audit_details({"policyName": "P", "conscienceLedger": [], "spirit_score": 7.0})
        # Yellow tier (4.0 <= val < 7.0)
        ui.print_audit_details({"policyName": "P", "conscienceLedger": [], "spirit_score": 4.0})
        # Red tier (< 4.0)
        ui.print_audit_details({"policyName": "P", "conscienceLedger": [], "spirit_score": 3.9})


class TestSafiModelSelection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.orig_config_file = config.CONFIG_FILE
        config.CONFIG_FILE = self.config_dir / "config.json"
        self.env_patcher = unittest.mock.patch.dict(os.environ)
        self.env_patcher.start()
        for k in list(os.environ.keys()):
            if k.startswith("SAFI_INTELLECT_MODEL"):
                os.environ.pop(k, None)

    def tearDown(self):
        self.env_patcher.stop()
        config.CONFIG_FILE = self.orig_config_file
        self.temp_dir.cleanup()

    def test_resolve_intellect_model_explicit(self):
        model = config.resolve_intellect_model("software_engineer", "claude-3-5-sonnet")
        self.assertEqual(model, "claude-3-5-sonnet")

    def test_resolve_intellect_model_env(self):
        with unittest.mock.patch.dict(os.environ, {"SAFI_INTELLECT_MODEL_FIDUCIARY": "gpt-4o"}):
            self.assertEqual(config.resolve_intellect_model("fiduciary"), "gpt-4o")

        with unittest.mock.patch.dict(os.environ, {"SAFI_INTELLECT_MODEL": "deepseek-v4-flash"}):
            self.assertEqual(config.resolve_intellect_model("software_engineer"), "deepseek-v4-flash")

    def test_save_and_resolve_intellect_model(self):
        config.save_intellect_model("gemini-3.5-flash-lite", agent="software_engineer")
        self.assertEqual(config.resolve_intellect_model("software_engineer"), "gemini-3.5-flash-lite")

        config.save_intellect_model("mistral-small-2603")
        self.assertEqual(config.resolve_intellect_model("health_navigator"), "mistral-small-2603")

    def test_client_send_turn_passes_model(self):
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"ok": True, "type": "final_output", "finalOutput": "Hello"}
            client.send_turn(
                user_id="u1",
                conversation_id="c1",
                message="Hi",
                workspace_root="/tmp",
                model="claude-3-5-sonnet",
            )
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            payload = kwargs.get("json", {})
            self.assertEqual(payload.get("intellect_model"), "claude-3-5-sonnet")
            self.assertEqual(payload.get("model"), "claude-3-5-sonnet")

    def test_client_get_available_models(self):
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "ok": True,
                "models": [{"id": "gpt-4o", "label": "GPT-4o", "provider": "OpenAI"}],
            }
            models = client.get_available_models()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["id"], "gpt-4o")

    def test_discover_models_merging(self):
        from safi_cli.main import discover_models
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch.object(client, "get_available_models") as mock_remote:
            mock_remote.return_value = [{"id": "custom-model-1", "label": "Custom LLM"}]
            discovered = discover_models(client)
            ids = [m["id"] for m in discovered]
            self.assertIn("custom-model-1", ids)
            self.assertIn("claude-3-5-sonnet", ids)
            self.assertIn("claude-haiku-5-5", ids)

    def test_prompt_switch_model_direct(self):
        from safi_cli.main import prompt_switch_model
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch.object(client, "get_available_models", return_value=[]):
            chosen = prompt_switch_model(None, client, requested_model="gpt-4o", current_agent="software_engineer")
            self.assertEqual(chosen, "gpt-4o")
            self.assertEqual(config.resolve_intellect_model("software_engineer"), "gpt-4o")

    def test_prompt_switch_model_interactive(self):
        from safi_cli.main import prompt_switch_model
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch.object(client, "get_available_models", return_value=[]):
            with unittest.mock.patch("builtins.input", return_value="1"):
                chosen = prompt_switch_model(None, client, current_agent="software_engineer")
                self.assertIsNotNone(chosen)
                self.assertEqual(config.resolve_intellect_model("software_engineer"), chosen)

    def test_prompt_command_menu_model(self):
        from safi_cli.main import prompt_command_menu
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")
        with unittest.mock.patch("builtins.input", return_value="8"):
            with unittest.mock.patch("safi_cli.main.prompt_switch_model") as mock_switch:
                agent, conv, should_exit = prompt_command_menu(
                    current_agent="software_engineer",
                    client=client,
                    workspace_root=Path("/tmp"),
                    current_conv="conv-1",
                    current_model="gpt-4o",
                )
                self.assertFalse(should_exit)
                mock_switch.assert_called_once()

    @patch("requests.get")
    def test_get_turn_progress(self, mock_get):
        from safi_cli.client import SafiClient
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "complete": False,
            "latest_step": "Auditing policy compliance for 'edit'...",
            "progress": ["analyzing", "checking_tool"]
        }
        mock_get.return_value = mock_resp

        client = SafiClient("http://mock-backend:5000", "test-key")
        data = client.get_turn_progress("msg-123", user_id="user-1")
        self.assertIsNotNone(data)
        self.assertEqual(data["latest_step"], "Auditing policy compliance for 'edit'...")
        mock_get.assert_called_once_with(
            "http://mock-backend:5000/api/agentic/progress/msg-123",
            headers={"X-API-KEY": "test-key"},
            params={"user_id": "user-1"},
            timeout=2.0,
        )

    @patch("requests.post")
    def test_compress_conversation_client(self, mock_post):
        from safi_cli.client import SafiClient
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "compressed": True,
            "turns_count": 8,
            "tokens_before": 6200,
            "tokens_after": 450,
            "tokens_saved": 5750,
            "reduction_pct": 92.7,
            "summary": "### 1. Goal\nBuild game."
        }
        mock_post.return_value = mock_resp

        client = SafiClient("http://mock-backend:5000", "test-key")
        res = client.compress_conversation("conv-xyz", user_id="user-1", agent="software_engineer", model="gpt-4o", action="compress")
        self.assertTrue(res["ok"])
        self.assertTrue(res["compressed"])
        self.assertEqual(res["reduction_pct"], 92.7)
        mock_post.assert_called_once_with(
            "http://mock-backend:5000/api/agentic/compress",
            headers={"Content-Type": "application/json", "X-API-KEY": "test-key"},
            json={"conversation_id": "conv-xyz", "user_id": "user-1", "agent": "software_engineer", "action": "compress", "model": "gpt-4o"},
            timeout=120,
        )

    def test_ui_print_compression_result(self):
        from safi_cli.ui import print_compression_result
        # Test rendering without errors
        data = {
            "ok": True,
            "compressed": True,
            "turns_count": 8,
            "tokens_before": 6200,
            "tokens_after": 450,
            "tokens_saved": 5750,
            "reduction_pct": 92.7,
            "summary": "### 1. Primary Goal\nBuild platformer game."
        }
        print_compression_result(data)

        # Test minimal / not-compressed rendering
        minimal_data = {
            "ok": True,
            "compressed": False,
            "message": "Already minimal.",
            "summary": ""
        }
        print_compression_result(minimal_data)

    def test_compression_telemetry_reduction(self):
        from safi_cli import ui
        ui.reset_session_telemetry()
        # Simulate turns accumulating tokens
        turn_1 = {
            "models_usage": {
                "intellect": {"prompt_tokens": 10000, "completion_tokens": 200, "model": "gpt-6-luna"},
                "conscience": {"prompt_tokens": 8000, "completion_tokens": 100, "model": "jev-1.13.0"},
            }
        }
        ui._record_turn_telemetry(turn_1)
        self.assertEqual(ui._session_intellect["in"], 10000)
        self.assertEqual(ui._session_conscience["in"], 8000)
        self.assertEqual(ui._session_active_context, 10000)

        # Now compress: 10,000 down to 500 (saved 9,500)
        ui.record_compression_telemetry(
            tokens_before=10000,
            tokens_after=500,
            tokens_saved=9500,
            reduction_pct=95.0,
            intellect_model="gpt-6-luna",
        )

        # Verify session input tokens dropped down to the compacted baseline
        self.assertEqual(ui._session_intellect["in"], 500)
        self.assertEqual(ui._session_active_context, 500)
        self.assertEqual(ui._session_compression["tokens_saved"], 9500)
        self.assertEqual(ui._session_compression["reduction_pct"], 95.0)

        # Next turn should build on the reduced baseline
        turn_2 = {
            "models_usage": {
                "intellect": {"prompt_tokens": 700, "completion_tokens": 150, "model": "gpt-6-luna"},
                "conscience": {"prompt_tokens": 700, "completion_tokens": 50, "model": "jev-1.13.0"},
            }
        }
        ui._record_turn_telemetry(turn_2)
        self.assertEqual(ui._session_intellect["in"], 1200)
        self.assertEqual(ui._session_active_context, 700)

        # Panel rendering with compacted state
        panel = ui.build_telemetry_panel(intellect_model="gpt-6-luna", in_t=700, out_t=150)
        self.assertIsNotNone(panel)

        # Resetting session wipes telemetry cleanly
        ui.reset_session_telemetry()
        self.assertEqual(ui._session_intellect["in"], 0)
        self.assertEqual(ui._session_compression["tokens_saved"], 0)


class TestSafiSubagentDelegation(unittest.TestCase):
    def test_run_subagent_task_researcher(self):
        from safi_cli.main import run_subagent_task
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
                "finalOutput": "Found files: test.py, README.md",
            },
        ]
        args = {
            "description": "Find test files",
            "prompt": "List files in directory",
            "subagent_type": "researcher",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_subagent_task(
                client=client,
                args=args,
                workspace_root=Path(tmpdir),
                parent_conv_id="conv-parent",
                user_id="user-1",
            )
            self.assertIn("Found files: test.py, README.md", res)
            self.assertEqual(client.send_turn.call_count, 2)
            # Verify child conversation ID is isolated
            call_kwargs = client.send_turn.call_args_list[0].kwargs
            self.assertTrue(call_kwargs["conversation_id"].startswith("conv-parent_sub_"))
            # Verify child tools are strictly read-only
            tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
            self.assertEqual(set(tool_names), {"read", "grep", "glob", "list"})

    def test_run_subagent_task_blocks_prohibited_tool(self):
        from safi_cli.main import run_subagent_task
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "write",  # Researcher is NOT allowed to write!
                "parameters": {"path": "bad.py", "content": "bad"},
                "willDecision": "approve",
            },
            {
                "type": "response",
                "finalOutput": "Understood, write was blocked.",
            },
        ]
        args = {
            "description": "Attempt write",
            "prompt": "Try to write a file",
            "subagent_type": "researcher",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_subagent_task(
                client=client,
                args=args,
                workspace_root=Path(tmpdir),
                parent_conv_id="conv-parent",
                user_id="user-1",
            )
            self.assertIn("Understood, write was blocked", res)
            second_call_kwargs = client.send_turn.call_args_list[1].kwargs
            tool_results = second_call_kwargs["tool_results"]
            self.assertEqual(len(tool_results), 1)
            self.assertIn("not permitted to execute 'write'", tool_results[0]["result"])

    @patch("safi_cli.main.run_subagent_task")
    def test_run_agent_turn_delegates_to_subagent(self, mock_subagent):
        mock_subagent.return_value = "Subagent found 2 files."
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "task",
                "parameters": {
                    "description": "Search code",
                    "prompt": "Find auth files",
                    "subagent_type": "researcher",
                },
                "willDecision": "approve",
            },
            {
                "type": "response",
                "finalOutput": "Based on subagent research, auth is in auth.py.",
                "willDecision": "approve",
            },
        ]
        res = run_agent_turn(
            client=client,
            prompt="Find auth files",
            workspace_root=Path("."),
            conversation_id="conv-1",
            user_id="u-1",
            agent="software_engineer",
        )
        self.assertIsNotNone(res)
        mock_subagent.assert_called_once()
        self.assertEqual(client.send_turn.call_count, 2)
        second_call = client.send_turn.call_args_list[1].kwargs
        self.assertEqual(second_call["tool_results"][0]["result"], "Subagent found 2 files.")

    @patch("safi_cli.ui.prompt_question")
    def test_run_agent_turn_question_clarification(self, mock_prompt_q):
        mock_prompt_q.return_value = "Option A"
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "question",
                "parameters": {"question": "Which architecture?", "options": ["Option A", "Option B"]},
                "willDecision": "approve",
            },
            {
                "type": "response",
                "finalOutput": "Proceeding with Option A.",
                "willDecision": "approve",
            },
        ]
        res = run_agent_turn(
            client=client,
            prompt="Plan architecture",
            workspace_root=Path("."),
            conversation_id="conv-1",
            user_id="u-1",
            agent="software_engineer",
        )
        self.assertIsNotNone(res)
        mock_prompt_q.assert_called_once_with("Which architecture?", ["Option A", "Option B"])
        second_call = client.send_turn.call_args_list[1].kwargs
        self.assertIn("Option A", second_call["tool_results"][0]["result"])

    @patch("safi_cli.ui.render_todo_list")
    def test_run_agent_turn_todowrite(self, mock_render_todo):
        client = MagicMock()
        client.send_turn.side_effect = [
            {
                "type": "tool_call",
                "tool_name": "todowrite",
                "parameters": {"todos": [{"task": "Step 1", "status": "completed"}]},
                "willDecision": "approve",
            },
            {
                "type": "response",
                "finalOutput": "Done.",
                "willDecision": "approve",
            },
        ]
        res = run_agent_turn(
            client=client,
            prompt="Do task",
            workspace_root=Path("."),
            conversation_id="conv-1",
            user_id="u-1",
            agent="software_engineer",
        )
        self.assertIsNotNone(res)
        mock_render_todo.assert_called_once()
        second_call = client.send_turn.call_args_list[1].kwargs
        self.assertIn("Recorded plan with 1 task(s)", second_call["tool_results"][0]["result"])

    def test_git_tools_execution(self):
        from safi_cli.tools import execute_tool
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=str(p), check=True, stdout=subprocess.DEVNULL)
            status_out = execute_tool("git_status", {}, p)
            self.assertIn("Git Status", status_out)
            diff_out = execute_tool("git_diff", {}, p)
            self.assertIn("(no diff)", diff_out)

    def test_local_skill_discovery(self):
        from safi_cli.skills import discover_skills
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            skills_dir = p / ".safi" / "skills"
            skills_dir.mkdir(parents=True)
            skill_file = skills_dir / "audit.md"
            skill_file.write_text("# Security Audit\nRun a thorough security audit on all endpoints.")
            skills = discover_skills(p)
            self.assertIn("audit", skills)
            self.assertEqual(skills["audit"].description, "Security Audit")
            self.assertIn("security audit on all endpoints", skills["audit"].render_prompt())

    def test_plan_and_tasks_right_panel(self):
        from safi_cli import ui
        todos = [
            {"id": "1", "task": "Investigate repo", "status": "completed"},
            {"id": "2", "task": "Apply refactoring", "status": "in_progress"},
            {"id": "3", "task": "Verify tests", "status": "pending"},
        ]
        ui.render_todo_list(todos)
        panel = ui.build_plan_panel(todos)
        self.assertIsNotNone(panel)
        # Test progress calculation
        self.assertEqual(len(ui.get_active_todos()), 3)

        # Test tool result execution indicator with plan progress
        ui.print_tool_result_summary("read", "file contents")

        # Test print_final_output side-by-side with active plan
        test_payload = {
            "policyName": "Agentic Coding Policy",
            "spirit_score": 8.0,
            "conscienceLedger": [],
        }
        ui.print_final_output("Completed task.", test_payload)

        # Test mark_active_todos_completed
        ui.set_active_todos([{"task": "Step A", "status": "pending"}])
        ui.mark_active_todos_completed()
        self.assertEqual(ui.get_active_todos()[0]["status"], "completed")

        # Test clear
        ui.clear_active_todos()
        self.assertEqual(len(ui.get_active_todos()), 0)
        self.assertIsNone(ui.build_plan_panel([]))

    def test_readline_auto_completion(self):
        from safi_cli.main import _compute_completions, setup_readline_completer
        # 1. Slash command completion
        cmd_matches = _compute_completions("/ag", "/ag")
        self.assertIn("/agent", cmd_matches)
        self.assertIn("/agents", cmd_matches)

        # 2. Agent persona auto-completion (e.g. /agents fid -> fiduciary)
        agent_matches = _compute_completions("/agents fid", "fid")
        self.assertEqual(agent_matches, ["fiduciary"])

        agent_matches_singular = _compute_completions("/agent fid", "fid")
        self.assertEqual(agent_matches_singular, ["fiduciary"])

        all_agents = _compute_completions("/agents ", "")
        self.assertIn("software_engineer", all_agents)
        self.assertIn("fiduciary", all_agents)

        # 3. Model auto-completion (e.g. /model claud)
        model_matches = _compute_completions("/model claud", "claud")
        self.assertTrue(any("claude" in m for m in model_matches))
        self.assertIn("claude-haiku-5-5", model_matches)

        # 4. Compress subcommands (e.g. /compress sh)
        comp_matches = _compute_completions("/compress sh", "sh")
        self.assertEqual(comp_matches, ["show"])

        # 5. Verify setup runs without error
        setup_readline_completer()


class TestSafiCliHardeningAndUiFixes(unittest.TestCase):
    def test_result_is_error_heuristic(self):
        from safi_cli.ui import _result_is_error

        # False positive checks: grep hits containing "error" or "handle_error" should NOT be classified as errors
        self.assertFalse(_result_is_error("safi_app/config.py:25: handle_error(exception)"))
        self.assertFalse(_result_is_error("def test_error_handling(): pass"))
        self.assertFalse(_result_is_error("Exit code 0\nAll tests passed with 0 errors"))
        self.assertFalse(_result_is_error("src/router.ts:4: import { ErrorBoundary } from 'react'"))

        # Genuine failure checks:
        self.assertTrue(_result_is_error("Exit code 1\nCommand not found"))
        self.assertTrue(_result_is_error("exit code 127: bash: invalid command"))
        self.assertTrue(_result_is_error("Error: 'path' parameter is required for read."))
        self.assertTrue(_result_is_error("Tool execution error: file not found"))
        self.assertTrue(_result_is_error("Unknown tool: 'foo'"))
        self.assertTrue(_result_is_error("Rejected: The will gatekeeper rejected the proposal."))

    def test_ui_markup_safety(self):
        from safi_cli import ui

        # Unescaped brackets that would crash rich.errors.MarkupError if parsed as markup
        tricky_outputs = [
            "src/components/[id].tsx:12: const { id } = useParams()",
            "def parse[T](items: list[T]) -> dict[str, int]:",
            "Tool stdout: [bold red]unescaped tags[/bold red] [/unexpected]",
            "Line with unmatched [ bracket and ] closed bracket",
        ]

        for out in tricky_outputs:
            # None of these should throw MarkupError or any exception
            ui.print_tool_result_summary("grep", out)

        # Test print_workspace_step with bracketed parameters and output
        ui.print_workspace_step(
            tool_name="edit",
            args={"path": "pages/[id].tsx", "target": "a", "replacement": "b"},
            proposal_res={
                "willDecision": "approved",
                "conscienceLedger": [
                    {"value": "Type Safety [Strict]", "score": 0.95},
                    {"value": "Security [Boundary]", "score": -0.2},
                ],
            },
            result_str="Updated pages/[id].tsx with [0] changes",
        )

        # Test print_tool_proposal with bracketed path and diff
        ui.print_tool_proposal(
            name="write",
            args={"path": "components/[slug].tsx", "content": "export default function Slug() {}"},
            res={"willDecision": "approved"},
        )

        # Test subagent prints with bracketed names
        ui.print_subagent_start("code_reviewer [v2]", "Reviewing [id].tsx changes")
        ui.print_subagent_step("code_reviewer [v2]", "read", {"path": "pages/[id].tsx"}, "contents [0]")
        ui.print_subagent_done("code_reviewer [v2]", "Review passed [100%]", steps=2)

    def test_secrets_isolation(self):
        from safi_cli.tools import _is_secret_name, execute_tool

        # Secret filenames must be detected
        self.assertTrue(_is_secret_name(".env"))
        self.assertTrue(_is_secret_name(".env.local"))
        self.assertTrue(_is_secret_name(".env.production"))
        self.assertTrue(_is_secret_name(".env.development"))
        self.assertTrue(_is_secret_name("id_rsa"))
        self.assertTrue(_is_secret_name("id_ed25519"))
        self.assertTrue(_is_secret_name("server.key"))
        self.assertTrue(_is_secret_name("cert.pem"))

        # Template/example files must NOT be blocked
        self.assertFalse(_is_secret_name(".env.example"))
        self.assertFalse(_is_secret_name(".env.sample"))
        self.assertFalse(_is_secret_name(".env.template"))
        self.assertFalse(_is_secret_name(".env.dist"))
        self.assertFalse(_is_secret_name("environment.ts"))

        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / ".env.production").write_text("API_SECRET=12345")
            (p / ".env.example").write_text("API_SECRET=your_key_here")

            # Reading .env.production must be rejected
            res_blocked = execute_tool("read", {"path": ".env.production"}, p)
            self.assertIn("Access denied", res_blocked)
            self.assertIn("secret/credential file", res_blocked)

            # Reading .env.example must succeed
            res_allowed = execute_tool("read", {"path": ".env.example"}, p)
            self.assertIn("API_SECRET=your_key_here", res_allowed)

    def test_git_diff_security_and_safe_arguments(self):
        from safi_cli.tools import execute_tool
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=str(p), check=True, stdout=subprocess.DEVNULL)

            # Injection attempt in path parameter
            malicious_path = "; touch pwned.txt"
            res = execute_tool("git_diff", {"path": malicious_path}, p)
            # Must safely report error / not execute touch
            self.assertFalse((p / "pwned.txt").exists())

    def test_edit_empty_target_safeguard(self):
        from safi_cli.tools import execute_tool
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            test_file = p / "sample.py"
            test_file.write_text("print('hello')")

            # Calling edit with empty target must fail gracefully, not replace empty boundaries
            res = execute_tool("edit", {"path": "sample.py", "target": "", "replacement": "evil"}, p)
            self.assertIn("Error", res)
            self.assertIn("'target' text is required", res)
            self.assertEqual(test_file.read_text(), "print('hello')")

    def test_grep_with_dash_pattern(self):
        from safi_cli.tools import execute_tool
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=str(p), check=True, stdout=subprocess.DEVNULL)
            test_file = p / "options.py"
            test_file.write_text("parser.add_argument('-v', '--verbose')\n")
            subprocess.run(["git", "add", "options.py"], cwd=str(p), check=True, stdout=subprocess.DEVNULL)

            # Grepping for '-v' must be interpreted as a search pattern, not git grep flags
            res = execute_tool("grep", {"pattern": "-v", "path": "."}, p)
            self.assertIn("-v", res)

    def test_slash_command_menu_rendering_and_options(self):
        from safi_cli.main import prompt_command_menu
        from safi_cli.client import SafiClient
        client = SafiClient("http://mock-backend:5000", "test-key")

        # 1. Test cancel on empty input (Enter key)
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

        # 2. Test selecting command by name with slash (e.g. "/help")
        with patch("builtins.input", return_value="/help"):
            agent, conv, should_exit = prompt_command_menu(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                current_conv="conv-1",
            )
            self.assertFalse(should_exit)

        # 3. Test selecting command by name without slash (e.g. "clear")
        with patch("builtins.input", return_value="clear"):
            agent, conv, should_exit = prompt_command_menu(
                current_agent="software_engineer",
                client=client,
                workspace_root=Path("."),
                current_conv="conv-1",
            )
            self.assertFalse(should_exit)


if __name__ == "__main__":
    unittest.main()




