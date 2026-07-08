"""
Unit tests for partial-ledger reconciliation (Phase 3):

- SAFi._ledger_covers_values: every hard gate + a strict majority of scored
  values must be present, not "any one".
- SpiritIntegrator.compute: a partially-scored ledger is scored over what it
  covered (EMA holds for unobserved values) instead of the all-or-nothing
  "Ledger missing" 1/10 return.
- WillGate.evaluate_hard_gates: gate names match by normalized label, like
  Spirit and the coverage check.

Run:  venv/bin/python tests/test_partial_ledger.py
"""
import sys
import logging
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi
from safi_app.core.faculties.spirit import SpiritIntegrator
from safi_app.core.faculties.will import WillGate

RUBRIC = {"description": "r", "scoring_guide": []}

VALUES = [
    {"value": "Scope Compliance", "weight": 0.0, "hard_gate": True, "rubric": RUBRIC},
    {"value": "Honesty", "weight": 0.6, "rubric": RUBRIC},
    {"value": "Care", "weight": 0.4, "rubric": RUBRIC},
]


def make_safi(values):
    s = object.__new__(SAFi)
    s.log = logging.getLogger("test.SAFi")
    s.values = values
    return s


def entry(value, score=1.0, confidence=1.0):
    return {"value": value, "score": score, "confidence": confidence}


class TestLedgerCoverage(unittest.TestCase):

    def setUp(self):
        self.safi = make_safi(VALUES)

    def test_full_ledger_covers(self):
        ledger = [entry("Scope Compliance"), entry("Honesty"), entry("Care")]
        self.assertTrue(self.safi._ledger_covers_values(ledger))

    def test_missing_hard_gate_fails(self):
        ledger = [entry("Honesty"), entry("Care")]
        self.assertFalse(self.safi._ledger_covers_values(ledger))

    def test_minority_of_scored_values_fails(self):
        # 1 of 8 scored values used to count as a usable audit.
        many = [{"value": "Gate", "weight": 0.0, "hard_gate": True, "rubric": RUBRIC}] + [
            {"value": f"V{i}", "weight": 0.125, "rubric": RUBRIC} for i in range(8)
        ]
        safi = make_safi(many)
        ledger = [entry("Gate"), entry("V0")]
        self.assertFalse(safi._ledger_covers_values(ledger))
        # 5 of 8 is a strict majority.
        ledger = [entry("Gate")] + [entry(f"V{i}") for i in range(5)]
        self.assertTrue(safi._ledger_covers_values(ledger))

    def test_exactly_half_fails(self):
        ledger = [entry("Scope Compliance"), entry("Honesty")]  # 1 of 2 scored
        self.assertFalse(self.safi._ledger_covers_values(ledger))

    def test_empty_ledger_fails(self):
        self.assertFalse(self.safi._ledger_covers_values([]))

    def test_gates_only_agent_needs_only_gates(self):
        safi = make_safi([{"value": "Gate", "weight": 0.0, "hard_gate": True, "rubric": RUBRIC}])
        self.assertTrue(safi._ledger_covers_values([entry("Gate")]))

    def test_normalized_name_matching(self):
        ledger = [entry("scope  compliance"), entry("HONESTY"), entry("care")]
        self.assertTrue(self.safi._ledger_covers_values(ledger))


class TestComputePartialLedger(unittest.TestCase):

    def setUp(self):
        self.spirit = SpiritIntegrator(VALUES, beta=0.9)
        self.mu = {"scope compliance": 0.0, "honesty": 0.5, "care": 0.3}

    def test_full_ledger_baseline(self):
        ledger = [entry("Scope Compliance"), entry("Honesty"), entry("Care")]
        score, note, mu_new, p_t, drift, vec = self.spirit.compute(ledger, dict(self.mu))
        self.assertGreater(score, 5)
        self.assertNotIn("Unscored", note)
        self.assertAlmostEqual(mu_new["honesty"], 0.9 * 0.5 + 0.1 * 0.6, places=6)

    def test_partial_ledger_scores_matched_and_holds_missing(self):
        ledger = [entry("Scope Compliance"), entry("Honesty")]  # Care unscored
        score, note, mu_new, p_t, drift, vec = self.spirit.compute(ledger, dict(self.mu))
        # Not the old 1/10 "Ledger missing" return:
        self.assertGreater(score, 1)
        self.assertIn("Unscored: Care", note)
        # Honesty gets the EMA update; Care HOLDS its previous mu.
        self.assertAlmostEqual(mu_new["honesty"], 0.9 * 0.5 + 0.1 * 0.6, places=6)
        self.assertAlmostEqual(mu_new["care"], 0.3, places=6)
        # p_t contributes 0 for the unscored value (neutral).
        self.assertAlmostEqual(float(p_t[2]), 0.0, places=6)

    def test_fully_unmatched_ledger_keeps_safety_return(self):
        ledger = [entry("Totally Different Value")]
        score, note, mu_new, p_t, drift, vec = self.spirit.compute(ledger, dict(self.mu))
        self.assertEqual(score, 1)
        self.assertIn("Ledger missing", note)
        self.assertEqual(mu_new, self.mu, "memory must be unchanged on a failed audit")

    def test_partial_score_matches_integrate_neutrality(self):
        # integrate() treats a missing value as neutral (scaled 0.5 == score 0);
        # compute() must agree so the shipped verdict and recorded score align.
        ledger = [entry("Scope Compliance"), entry("Honesty")]
        assessment = self.spirit.integrate(ledger)
        self.assertGreater(assessment["alignment_score"], 0.5)
        score, note, *_ = self.spirit.compute(ledger, dict(self.mu))
        # weights: honesty 0.6*1.0 observed, care 0.4 neutral 0 -> raw 0.6 -> ~8/10
        self.assertGreaterEqual(score, 7)


class TestHardGateNormalization(unittest.TestCase):

    def _gate(self):
        return WillGate(None, values=VALUES, profile={})

    def test_case_variant_gate_name_matches(self):
        ledger = [entry("SCOPE COMPLIANCE", score=1.0), entry("Honesty"), entry("Care")]
        self.assertEqual(self._gate().evaluate_hard_gates(ledger),
                         ("approve", "hard_gates_passed"))

    def test_case_variant_gate_failure_keeps_mapped_reason(self):
        ledger = [entry("scope compliance", score=-1.0), entry("Honesty"), entry("Care")]
        self.assertEqual(self._gate().evaluate_hard_gates(ledger),
                         ("violation", "scope_violation"))

    def test_truly_missing_gate_still_fails_closed(self):
        ledger = [entry("Honesty"), entry("Care")]
        self.assertEqual(self._gate().evaluate_hard_gates(ledger),
                         ("violation", "hard_gate_unscored"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
