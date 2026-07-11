"""
Unit tests for SAFi._ship_system_failure_notice — the deterministic notice
shipped when governance itself fails (audit unavailable, structural failure).

Regression guard for the 2026-07-11 incident: an audit_unavailable intercept
was voiced through trigger_persona_redirect, which generates in a vacuum
(the user's question is withheld), so the persona's scope rules produced a
false "outside my area of focus" refusal for an in-scope question. System
faults must ship an honest, fixed notice with NO LLM calls.

Run:  venv/bin/python tests/test_system_failure_notice.py
"""
import sys
import logging
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi

VALUES = [
    {"value": "Honesty", "weight": 0.6, "rubric": {"description": "honest?", "scoring_guide": []}},
    {"value": "Care", "weight": 0.4, "rubric": {"description": "caring?", "scoring_guide": []}},
]


def make_safi():
    s = object.__new__(SAFi)
    s.log = logging.getLogger("test.SAFi")
    s.values = VALUES
    s.profile = {"policy_id": "pol-1", "policy_version": 1, "org_id": "org-1"}
    s.active_profile_name = "test_agent"
    s.intellect_model = "test-model"
    s.spirit = MagicMock(values=VALUES)
    # Deliberately NO intellect_engine / llm_provider / conscience attributes:
    # touching any of them (i.e. making an LLM call) raises AttributeError.
    return s


def ship(safi, violation_type="audit_unavailable", **kwargs):
    with patch("safi_app.core.orchestrator.db", MagicMock()) as db, \
         patch.object(SAFi, "_append_log") as append_log:
        res = safi._ship_system_failure_notice(
            original_prompt="What does Romans say about the law?",
            violation_type=violation_type,
            message_id="msg-1",
            new_title=None,
            user_id="user-1",
            org_id="org-1",
            failing_ledger=[{"value": "Honesty", "score": 0.0}],
            blocked_draft="blocked draft text",
            **kwargs,
        )
    return res, db, append_log


class TestSystemFailureNotice(unittest.TestCase):

    def test_makes_no_llm_calls(self):
        # make_safi() sets no LLM-capable attributes, so any generation attempt
        # would raise AttributeError instead of returning.
        res, _, _ = ship(make_safi())
        self.assertTrue(res["finalOutput"])

    def test_notice_never_claims_out_of_scope(self):
        res, _, _ = ship(make_safi())
        lowered = res["finalOutput"].lower()
        for phrase in ("outside", "area of focus", "scope", "designed to assist"):
            self.assertNotIn(phrase, lowered)
        self.assertIn("internal issue", lowered)
        self.assertIn("not a problem with your question", lowered)

    def test_commits_notice_and_preserves_block_reason(self):
        res, db, append_log = ship(make_safi(), violation_type="audit_unavailable")
        db.update_message_content.assert_called_once_with(
            "msg-1", res["finalOutput"], audit_status="complete")
        self.assertEqual(res["willDecision"], "redirected")
        self.assertEqual(res["willReason"], "audit_unavailable")
        self.assertEqual(res["audit_status"], "complete")
        entry = append_log.call_args[0][0]
        self.assertEqual(entry["willReason"], "audit_unavailable")
        self.assertTrue(entry["isRedirect"])
        self.assertEqual(entry["originalLedger"], [{"value": "Honesty", "score": 0.0}])
        self.assertEqual(entry["blockedDraft"], "blocked draft text")

    def test_custom_notice_overrides_default_text(self):
        # The exhausted content-gate terminal passes its own honest copy.
        res, db, _ = ship(make_safi(), violation_type="ethical_violation",
                          notice="Custom terminal copy.")
        self.assertEqual(res["finalOutput"], "Custom terminal copy.")
        db.update_message_content.assert_called_once_with(
            "msg-1", "Custom terminal copy.", audit_status="complete")

    def test_correctable_gate_predicate(self):
        ok = {"verdict": "violation", "stage": "hard_gate", "reason": "ethical_violation"}
        self.assertTrue(SAFi._is_correctable_gate(ok))
        # Scope gates, spirit dips, approvals, and system faults are NOT correctable.
        self.assertFalse(SAFi._is_correctable_gate({**ok, "reason": "scope_violation"}))
        self.assertFalse(SAFi._is_correctable_gate({**ok, "stage": "spirit"}))
        self.assertFalse(SAFi._is_correctable_gate({**ok, "verdict": "approve"}))
        self.assertFalse(SAFi._is_correctable_gate(
            {"verdict": "violation", "stage": "audit", "reason": "audit_unavailable"}))

    def test_no_fake_spirit_score(self):
        res, db, _ = ship(make_safi())
        self.assertIsNone(res["spirit_score"])
        # update_audit_results(msg_id, ledger, score, note, ...) — score must be
        # None (unaudited), not 0 (a real rock-bottom score).
        score_arg = db.update_audit_results.call_args[0][2]
        self.assertIsNone(score_arg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
