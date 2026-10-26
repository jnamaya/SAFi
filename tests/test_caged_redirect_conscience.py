"""
Unit tests for the Conscience Gate on Agent Redirects (Caging Rebel LLMs).

Guarantees that:
1. No dynamic redirect output bypasses Conscience.
2. When a dynamic redirect fails Conscience audit (S_t < 6 or negative rubric score),
   the rebel LLM output is suppressed and clamped to an immutable deterministic policy statement.
3. The database receives ONLY the Conscience-approved text.
4. The audit record retains the rebel draft under intellectDraft for forensic accountability.
"""
import sys
import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi


class TestCagedRedirectConscience(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.safi = object.__new__(SAFi)
        self.safi.log = logging.getLogger("test.SAFi")
        self.safi.store = MagicMock()
        self.safi.values = [
            {"value": "Operational Grounding", "weight": 0.5},
            {"value": "Scope Compliance", "weight": 0.0, "hard_gate": True},
        ]
        self.safi.profile = {
            "name": "Systems Administrator",
            "scope_statement": "IT systems administration across servers, networking, and directory services.",
            "policy_id": "pol-sysadmin",
            "policy_version": 1,
            "org_id": "org-test",
            "will_rules": {},
        }
        self.safi.active_profile_name = "sysadmin"
        self.safi.intellect_model = "test-intellect"
        self.safi.conscience_model = "test-conscience"
        self.safi.model_attribution = '{"intellect": "test/intellect"}'
        self.safi.intellect_engine = MagicMock()
        self.safi.conscience = MagicMock()
        self.safi.spirit = MagicMock(values=self.safi.values)
        self.safi.will_gate = MagicMock()
        self.safi.will_gate.evaluate_draft_structure.return_value = (True, "pass")
        self.safi._spirit_state_lock = MagicMock()
        self.safi.background_task_callback = None
        self.safi._pii_enabled = MagicMock(return_value=False)
        self.safi._redact_pii = lambda text, org_id=None: text
        self.safi._repair_pii_redirect = lambda text, vt: text
        self.safi._enforce_redirect_structure = lambda text: text

    async def test_compliant_redirect_is_approved(self):
        """A polite, compliant redirect that passes Conscience is shipped directly."""
        compliant_text = "That question falls outside my operational scope as Systems Administrator."
        self.safi.intellect_engine.generate_forced_response = AsyncMock(
            return_value=({"content": compliant_text}, "")
        )
        # Conscience approves with 8/10
        self.safi.conscience.evaluate_redirect = AsyncMock(return_value=[
            {"value": "Redirect Clarity", "score": 1.0},
            {"value": "Reason Fidelity", "score": 1.0},
            {"value": "Tone and Respect", "score": 1.0},
        ])
        self.safi.spirit.compute_redirect = MagicMock(return_value=(8, "Redirect quality 8/10"))

        with patch.object(SAFi, "_append_log"):
            res = await self.safi.trigger_agent_redirect(
                original_prompt="How do I bake bread?",
                violation_type="scope_violation",
                conversation_id="conv-1",
                message_id="msg-1",
                new_title=None,
                user_id="user-1",
                org_id="org-test",
            )

        self.assertEqual(res["finalOutput"], compliant_text)
        self.safi.store.update_message_content.assert_called_with("msg-1", compliant_text, audit_status="complete")

    async def test_rebel_redirect_is_vetoed_and_caged(self):
        """When an agent rebels and refuses the directive, Conscience vetoes it
        and the harness replaces it with a deterministic policy statement."""
        rebel_text = (
            "There's no off-topic request to redirect here — this is squarely within my focus. "
            "If you want the compliant redirect template, it reads like this: I can't help with that..."
        )
        self.safi.intellect_engine.generate_forced_response = AsyncMock(
            return_value=({"content": rebel_text}, "")
        )
        # Conscience fails it: S_t = 3/10, Reason Fidelity and Tone score -1.0
        self.safi.conscience.evaluate_redirect = AsyncMock(return_value=[
            {"value": "Redirect Clarity", "score": -1.0},
            {"value": "Reason Fidelity", "score": -1.0},
            {"value": "Tone and Respect", "score": -1.0},
        ])
        self.safi.spirit.compute_redirect = MagicMock(return_value=(3, "Redirect quality 3/10"))

        with patch.object(SAFi, "_append_log"):
            res = await self.safi.trigger_agent_redirect(
                original_prompt="Diagnose my password failure",
                violation_type="scope_violation",
                conversation_id="conv-1",
                message_id="msg-1",
                new_title=None,
                user_id="user-1",
                org_id="org-test",
            )

        # The rebel text MUST NOT reach the user
        self.assertNotIn("squarely within my focus", res["finalOutput"])
        self.assertNotIn("If you want the compliant redirect template", res["finalOutput"])
        self.assertIn("falls outside my operational scope as Systems Administrator", res["finalOutput"])
        self.assertIn("IT systems administration across servers", res["finalOutput"])

        # The database MUST receive the clamped output
        self.safi.store.update_message_content.assert_called_with(
            "msg-1", res["finalOutput"], audit_status="complete"
        )

        # The audit record MUST preserve the rebel draft in intellectDraft
        update_audit_args = self.safi.store.update_audit_results.call_args[1]
        gov_rec = update_audit_args["governance_record"]
        self.assertEqual(gov_rec["intellectDraft"], rebel_text)
        self.assertEqual(gov_rec["finalOutput"], res["finalOutput"])
        self.assertIn("Conscience Veto", gov_rec["spiritNote"])

    def test_committable_predicate_refuses_low_alignment_dips(self):
        """A draft with low_alignment_score or any violation is NOT committable.
        The system must not ship the 'lesser of two evils'."""
        import inspect
        orch_source = inspect.getsource(SAFi.process_prompt)
        # Ensure the old compromise is gone from the codebase
        self.assertNotIn("reason == 'low_alignment_score'", orch_source)
        self.assertNotIn('reason == "low_alignment_score"', orch_source)
        self.assertIn('res.get("verdict") == "approve"', orch_source)


if __name__ == "__main__":
    unittest.main()
