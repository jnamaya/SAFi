import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from safi_app.core.faculties.conscience import ConscienceAuditor
from safi_app.core.orchestrator import SAFi


class TestConsciencePromptScope(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.conscience = ConscienceAuditor(
            llm_provider=self.mock_llm,
            values=[],
        )

    async def test_evaluate_prompt_scope_calls_provider(self):
        self.mock_llm.uses_typed_conscience.return_value = False
        self.mock_llm.run_conscience = AsyncMock(return_value=[
            {
                "value": "Domain Scope Adherence",
                "score": 1.0,
                "confidence": 0.95,
                "reason": "Directly requests server log inspection which is within Systems Administration scope."
            }
        ])

        ledger = await self.conscience.evaluate_prompt_scope(
            user_prompt="check systemctl status nginx",
            agent_title="Systems Administrator",
            scope_statement="Governed systems administration across servers and network services.",
        )

        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["value"], "Domain Scope Adherence")
        self.assertEqual(ledger[0]["score"], 1.0)
        self.assertIn("assessment_explanation", ledger[0])
        self.mock_llm.run_conscience.assert_awaited_once()

    async def test_orchestrator_phase_one_blocks_out_of_scope_prompt(self):
        orch = SAFi.__new__(SAFi)
        orch.log = MagicMock()
        orch.store = MagicMock()
        orch.config = MagicMock()
        orch.intellect_engine = MagicMock()
        orch.will_gate = MagicMock()
        orch.spirit = MagicMock()
        orch.phase_zero = MagicMock()
        orch.conscience = MagicMock()
        orch.active_profile_name = "sysadmin"
        orch.intellect_model = "test-model"
        orch.conscience_model = "test-conscience"
        orch.model_attribution = None
        orch.review_alert_callback = None
        orch._append_log = MagicMock()
        orch.background_task_callback = None
        orch.values = []
        orch._spirit_state_lock = MagicMock()
        orch.mu_history = []
        orch.last_drift = 0.0
        orch.mcp_manager = None
        orch.profile = {
            "name": "sysadmin",
            "title": "Systems Administrator",
            "scope_statement": "Infrastructure and systems administration operations only.",
            "will_rules": {
                "preflight_prompt_scope": True,
                "allowed_tools": ["bash", "read", "write"],
            }
        }

        orch.phase_zero.evaluate_prompt.return_value = (True, "safe")
        orch.activate_org = MagicMock()
        orch.activate_agent = MagicMock()
        orch._pii_enabled = MagicMock(return_value=False)
        orch.context_budgeter = MagicMock(return_value="{}")
        orch._resolve_history_window = MagicMock(return_value=(5, 4000))
        orch._is_cancelled = MagicMock(return_value=False)
        orch.trigger_agent_redirect = AsyncMock(return_value={"finalOutput": "Redirected", "willDecision": "violation"})

        orch.conscience.evaluate_prompt_scope = AsyncMock(return_value=[
            {
                "value": "Domain Scope Adherence",
                "score": -1.0,
                "confidence": 0.9,
                "reason": "Writing financial tax returns is completely outside infrastructure administration."
            }
        ])

        result = await orch.process_prompt(
            user_prompt="Help me prepare my federal tax return form 1040",
            user_id="user_123",
            conversation_id="conv_456",
            client_owned_tools=[{"name": "bash"}],
        )

        orch.intellect_engine.generate.assert_not_called()

        orch.trigger_agent_redirect.assert_awaited_once()
        _, kwargs = orch.trigger_agent_redirect.call_args
        self.assertEqual(kwargs.get("will_stage"), "phase_one_scope")
        self.assertEqual(kwargs.get("violation_type"), "scope_violation")
        self.assertIsNotNone(kwargs.get("failing_ledger"))

    async def test_orchestrator_phase_one_passes_in_scope_prompt(self):
        orch = SAFi.__new__(SAFi)
        orch.log = MagicMock()
        orch.store = MagicMock()
        orch.config = MagicMock()
        orch.intellect_engine = MagicMock()
        orch.will_gate = MagicMock()
        orch.spirit = MagicMock()
        orch.phase_zero = MagicMock()
        orch.conscience = MagicMock()
        orch.active_profile_name = "sysadmin"
        orch.intellect_model = "test-model"
        orch.conscience_model = "test-conscience"
        orch.model_attribution = None
        orch.review_alert_callback = None
        orch._append_log = MagicMock()
        orch.background_task_callback = None
        orch.values = []
        orch._spirit_state_lock = MagicMock()
        orch.mu_history = []
        orch.last_drift = 0.0
        orch.mcp_manager = None
        orch.profile = {
            "name": "sysadmin",
            "title": "Systems Administrator",
            "scope_statement": "Infrastructure and systems administration operations only.",
            "will_rules": {
                "preflight_prompt_scope": True,
                "allowed_tools": ["bash", "read", "write"],
            }
        }

        orch.phase_zero.evaluate_prompt.return_value = (True, "safe")
        orch.activate_org = MagicMock()
        orch.activate_agent = MagicMock()
        orch._pii_enabled = MagicMock(return_value=False)
        orch.context_budgeter = MagicMock(return_value="{}")
        orch._resolve_history_window = MagicMock(return_value=(5, 4000))
        orch._is_cancelled = MagicMock(return_value=False)

        orch.conscience.evaluate_prompt_scope = AsyncMock(return_value=[
            {
                "value": "Domain Scope Adherence",
                "score": 1.0,
                "confidence": 0.95,
                "reason": "Apache configuration is standard systems administration."
            }
        ])

        orch.intellect_engine.generate = AsyncMock(return_value=(
            {"type": "message", "content": "Here is the Apache config."},
            "reflection",
            "context"
        ))
        orch.store.update_spirit_memory_atomic.return_value = (
            (1.0, "ok", {}, {}, 0.0, []),
            1,
        )
        orch._finalize_draft = AsyncMock(return_value={
            "verdict": "approve",
            "stage": "audit",
            "draft": "Here is the Apache config.",
            "finalOutput": "Here is the Apache config.",
            "willDecision": "approve",
            "ledger": [],
            "reason": None,
        })

        result = await orch.process_prompt(
            user_prompt="Inspect apache2.conf on local-VM",
            user_id="user_123",
            conversation_id="conv_456",
            client_owned_tools=[{"name": "bash"}],
        )

        orch.intellect_engine.generate.assert_awaited_once()

    async def test_orchestrator_skips_scope_preflight_on_tool_continuation_turn(self):
        orch = SAFi.__new__(SAFi)
        orch.log = MagicMock()
        orch.store = MagicMock()
        orch.config = MagicMock()
        orch.intellect_engine = MagicMock()
        orch.will_gate = MagicMock()
        orch.spirit = MagicMock()
        orch.phase_zero = MagicMock()
        orch.conscience = MagicMock()
        orch.mcp_manager = None
        orch._spirit_state_lock = MagicMock()
        orch.mu_history = []
        orch.last_drift = 0.0
        orch.values = [{"value": "Helpfulness", "weight": 1.0}]
        orch.active_profile_name = "sysadmin"
        orch.intellect_model = "test-model"
        orch.conscience_model = "test-conscience"
        orch.model_attribution = None
        orch.review_alert_callback = None
        orch._append_log = MagicMock()
        orch.background_task_callback = None
        orch.profile = {
            "title": "Systems Administrator",
            "scope_statement": "Governed systems administration across servers and network services.",
            "allowed_tools": ["bash"],
            "will_rules": {"preflight_prompt_scope": True},
        }
        orch.context_budgeter = MagicMock(return_value="{}")
        orch._resolve_history_window = MagicMock(return_value=(5, 4000))
        orch.phase_zero.evaluate_prompt = MagicMock(return_value=(True, "Prompt safe"))
        orch._pii_enabled = MagicMock(return_value=False)
        orch.activate_org = MagicMock()
        orch.activate_agent = MagicMock()
        orch.max_context_chars = 12000
        orch._is_cancelled = MagicMock(return_value=False)

        orch.conscience.evaluate_prompt_scope = AsyncMock(return_value=[
            {"value": "Scope Compliance", "score": 1.0, "reason": "In scope"}
        ])
        orch.intellect_engine.generate = AsyncMock(return_value=(
            {"type": "message", "content": "Tool finished."},
            "reflection",
            "context"
        ))
        orch.store.update_spirit_memory_atomic.return_value = (
            (1.0, "ok", {}, {}, 0.0, []),
            1,
        )
        orch._finalize_draft = AsyncMock(return_value={
            "verdict": "approve",
            "stage": "audit",
            "draft": "Tool finished.",
            "finalOutput": "Tool finished.",
            "willDecision": "approve",
            "ledger": [],
            "reason": None,
        })

        result = await orch.process_prompt(
            user_prompt="Inspect apache2.conf on local-VM",
            user_id="user_123",
            conversation_id="conv_456",
            client_owned_tools=[{"name": "bash"}],
            client_tool_results=[{"tool_name": "bash", "result": "active (running)"}],
        )

        orch.conscience.evaluate_prompt_scope.assert_not_called()
        orch.intellect_engine.generate.assert_awaited_once()

    async def test_chatbot_with_scope_statement_runs_preflight(self):
        orch = SAFi.__new__(SAFi)
        orch.log = MagicMock()
        orch.store = MagicMock()
        orch.config = MagicMock()
        orch.intellect_engine = MagicMock()
        orch.will_gate = MagicMock()
        orch.spirit = MagicMock()
        orch.phase_zero = MagicMock()
        orch.conscience = MagicMock()
        orch.active_profile_name = "academic_tutor"
        orch.intellect_model = "test-model"
        orch.conscience_model = "test-conscience"
        orch.model_attribution = None
        orch.review_alert_callback = None
        orch._append_log = MagicMock()
        orch.background_task_callback = None
        orch.values = []
        orch._spirit_state_lock = MagicMock()
        orch.mu_history = []
        orch.last_drift = 0.0
        orch.mcp_manager = None
        orch.profile = {
            "name": "academic_tutor",
            "title": "Academic Tutor",
            "scope_statement": "STEM education only.",
            "will_rules": {},
        }
        orch.context_budgeter = MagicMock(return_value="{}")
        orch._resolve_history_window = MagicMock(return_value=(5, 4000))
        orch.phase_zero.evaluate_prompt = MagicMock(return_value=(True, "Prompt safe"))
        orch._pii_enabled = MagicMock(return_value=False)
        orch.activate_org = MagicMock()
        orch.activate_agent = MagicMock()
        orch.max_context_chars = 12000
        orch._is_cancelled = MagicMock(return_value=False)

        orch.conscience.evaluate_prompt_scope = AsyncMock(return_value=[
            {"value": "Scope Compliance", "score": 1.0, "reason": "In scope"}
        ])
        orch.intellect_engine.generate = AsyncMock(return_value=(
            {"type": "message", "content": "Let us solve this together."},
            "reflection",
            "context"
        ))
        orch.store.update_spirit_memory_atomic.return_value = ((1.0, "ok", {}, {}, 0.0, []), 1)
        orch._finalize_draft = AsyncMock(return_value={
            "verdict": "approve", "stage": "audit", "draft": "Let us solve this.", "finalOutput": "Let us solve this.",
            "willDecision": "approve", "ledger": [], "reason": None,
        })

        await orch.process_prompt(
            user_prompt="Help me with quadratic equations",
            user_id="user_123",
            conversation_id="conv_456",
        )

        orch.conscience.evaluate_prompt_scope.assert_awaited_once()
        orch.intellect_engine.generate.assert_awaited_once()

    async def test_cli_execution_agent_defaults_to_preflight_without_explicit_policy_flag(self):
        orch = SAFi.__new__(SAFi)
        orch.log = MagicMock()
        orch.store = MagicMock()
        orch.config = MagicMock()
        orch.intellect_engine = MagicMock()
        orch.will_gate = MagicMock()
        orch.spirit = MagicMock()
        orch.phase_zero = MagicMock()
        orch.conscience = MagicMock()
        orch.active_profile_name = "software_engineer"
        orch.intellect_model = "test-model"
        orch.conscience_model = "test-conscience"
        orch.model_attribution = None
        orch.review_alert_callback = None
        orch._append_log = MagicMock()
        orch.background_task_callback = None
        orch.values = []
        orch._spirit_state_lock = MagicMock()
        orch.mu_history = []
        orch.last_drift = 0.0
        orch.mcp_manager = None
        orch.profile = {
            "name": "software_engineer",
            "title": "Software Engineer",
            "scope_statement": "Software engineering and repository development.",
            "allowed_tools": ["bash", "read", "write"],
            "will_rules": {},
        }
        orch.context_budgeter = MagicMock(return_value="{}")
        orch._resolve_history_window = MagicMock(return_value=(5, 4000))
        orch.phase_zero.evaluate_prompt = MagicMock(return_value=(True, "Prompt safe"))
        orch._pii_enabled = MagicMock(return_value=False)
        orch.activate_org = MagicMock()
        orch.activate_agent = MagicMock()
        orch.max_context_chars = 12000
        orch._is_cancelled = MagicMock(return_value=False)

        orch.conscience.evaluate_prompt_scope = AsyncMock(return_value=[
            {"value": "Domain Scope Adherence", "score": 1.0, "confidence": 0.95, "reason": "In-scope."}
        ])
        orch.intellect_engine.generate = AsyncMock(return_value=(
            {"type": "message", "content": "Done."},
            "reflection",
            "context"
        ))
        orch.store.update_spirit_memory_atomic.return_value = ((1.0, "ok", {}, {}, 0.0, []), 1)
        orch._finalize_draft = AsyncMock(return_value={
            "verdict": "approve", "stage": "audit", "draft": "Done.", "finalOutput": "Done.",
            "willDecision": "approve", "ledger": [], "reason": None,
        })

        await orch.process_prompt(
            user_prompt="Refactor the auth middleware",
            user_id="user_123",
            conversation_id="conv_456",
            client_owned_tools=[{"name": "bash"}],
        )

        orch.conscience.evaluate_prompt_scope.assert_awaited_once()
        orch.intellect_engine.generate.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
