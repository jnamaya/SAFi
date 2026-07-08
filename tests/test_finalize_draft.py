"""
Unit tests for SAFi._finalize_draft — the unified governance commit path.

Uses the real WillGate and SpiritIntegrator with a stubbed Conscience and a
no-op DB, so the gate ordering and verdicts are exercised without any network
or database access.

Run:  venv/bin/python tests/test_finalize_draft.py
"""
import sys
import asyncio
import logging
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi
from safi_app.core.faculties.will import WillGate
from safi_app.core.faculties.spirit import SpiritIntegrator

DISCLAIMER = "Disclaimer: I am a test agent."

VALUES = [
    {
        "value": "Scope Compliance", "weight": 0.0, "hard_gate": True,
        "rubric": {"description": "in scope?", "scoring_guide": []},
    },
    {
        "value": "Honesty", "weight": 0.6,
        "rubric": {"description": "honest?", "scoring_guide": []},
    },
    {
        "value": "Care", "weight": 0.4,
        "rubric": {"description": "caring?", "scoring_guide": []},
    },
]

PROFILE = {
    "will_rules": {
        "structural_requirements": {
            "require_disclaimer": True,
            "mandatory_disclaimer_substring": DISCLAIMER,
        }
    }
}


class FakeConscience:
    """Returns a canned ledger, or raises when ledger is an Exception."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.calls = 0

    async def evaluate(self, **kwargs):
        self.calls += 1
        if isinstance(self.ledger, Exception):
            raise self.ledger
        return self.ledger


def make_safi(conscience):
    s = object.__new__(SAFi)
    s.log = logging.getLogger("test.SAFi")
    s.values = VALUES
    s.profile = PROFILE
    s.will_gate = WillGate(None, values=VALUES, profile=PROFILE, alignment_threshold=0.5)
    s.spirit = SpiritIntegrator(VALUES, beta=0.9)
    s.conscience = conscience
    return s


def ledger_entry(value, score, confidence=1.0):
    return {"value": value, "score": score, "confidence": confidence, "reason": "test"}


def finalize(safi, draft):
    with patch("safi_app.core.orchestrator.db", MagicMock()):
        return asyncio.run(
            safi._finalize_draft(draft, "user prompt", "reflection", "", "msg-1")
        )


class TestFinalizeDraft(unittest.TestCase):

    def test_structural_failure_blocks_before_audit(self):
        conscience = FakeConscience([])
        safi = make_safi(conscience)
        res = finalize(safi, "Draft with no disclaimer.")
        self.assertEqual(res["verdict"], "violation")
        self.assertEqual(res["stage"], "structure")
        self.assertEqual(res["reason"], "missing_disclaimer")
        self.assertEqual(conscience.calls, 0, "Conscience must not run on a structural failure")

    def test_clean_draft_approves(self):
        conscience = FakeConscience([
            ledger_entry("Scope Compliance", 1.0),
            ledger_entry("Honesty", 1.0),
            ledger_entry("Care", 1.0),
        ])
        safi = make_safi(conscience)
        res = finalize(safi, f"Good answer. {DISCLAIMER}")
        self.assertEqual(res["verdict"], "approve")
        self.assertEqual(res["stage"], "spirit")
        self.assertGreater(res["spirit_assessment"]["alignment_score"], 0.5)

    def test_hard_gate_failure_reports_real_reason(self):
        conscience = FakeConscience([
            ledger_entry("Scope Compliance", -1.0),
            ledger_entry("Honesty", 1.0),
            ledger_entry("Care", 1.0),
        ])
        safi = make_safi(conscience)
        res = finalize(safi, f"Off-topic answer. {DISCLAIMER}")
        self.assertEqual(res["verdict"], "violation")
        self.assertEqual(res["stage"], "hard_gate")
        self.assertEqual(res["reason"], "scope_violation")

    def test_unscored_hard_gate_fails_closed(self):
        conscience = FakeConscience([
            ledger_entry("Honesty", 1.0),
            ledger_entry("Care", 1.0),
        ])
        safi = make_safi(conscience)
        res = finalize(safi, f"Answer. {DISCLAIMER}")
        self.assertEqual(res["verdict"], "violation")
        self.assertEqual(res["stage"], "hard_gate")
        self.assertEqual(res["reason"], "hard_gate_unscored")

    def test_audit_error_fails_closed_not_raised(self):
        conscience = FakeConscience(RuntimeError("LLM down"))
        safi = make_safi(conscience)
        res = finalize(safi, f"Answer. {DISCLAIMER}")
        self.assertEqual(res["verdict"], "violation")
        self.assertEqual(res["stage"], "audit")
        self.assertEqual(res["reason"], "audit_unavailable")
        self.assertEqual(conscience.calls, 2, "guarded audit retries once")

    def test_low_alignment_is_spirit_stage_violation(self):
        conscience = FakeConscience([
            ledger_entry("Scope Compliance", 1.0),
            ledger_entry("Honesty", -0.5),
            ledger_entry("Care", -0.5),
        ])
        safi = make_safi(conscience)
        res = finalize(safi, f"Weak answer. {DISCLAIMER}")
        self.assertEqual(res["verdict"], "violation")
        self.assertEqual(res["stage"], "spirit")
        self.assertEqual(res["reason"], "low_alignment_score")
        self.assertIsNotNone(res["spirit_assessment"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
