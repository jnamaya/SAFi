"""
Unit tests for compile-time governance validation (Phase 2):

- synderesis._validate_value_rubrics: hard gates without a usable rubric raise;
  ordinary values without one are stripped and remaining weights renormalized.
- WillGate.evaluate_draft_structure: require_disclaimer with a missing/blank
  mandatory_disclaimer_substring is a config warning, not a KeyError.

Run:  venv/bin/python tests/test_governance_config.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.synderesis import _validate_value_rubrics
from safi_app.core.faculties.will import WillGate

RUBRIC = {"description": "test rubric", "scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}


def profile_with(values):
    return {"name": "Test Agent", "values": values}


class TestValidateValueRubrics(unittest.TestCase):

    def test_hard_gate_without_rubric_raises(self):
        prof = profile_with([
            {"value": "Scope Compliance", "weight": 0.0, "hard_gate": True},
            {"value": "Honesty", "weight": 1.0, "rubric": RUBRIC},
        ])
        with self.assertRaises(ValueError) as ctx:
            _validate_value_rubrics(prof, "test_agent")
        self.assertIn("Scope Compliance", str(ctx.exception))
        self.assertIn("test_agent", str(ctx.exception))

    def test_hard_gate_with_empty_rubric_raises(self):
        prof = profile_with([
            {"value": "Grounding Fidelity", "weight": 0.0, "hard_gate": True, "rubric": {}},
        ])
        with self.assertRaises(ValueError):
            _validate_value_rubrics(prof, "test_agent")

    def test_ordinary_value_without_rubric_is_stripped_and_renormalized(self):
        prof = profile_with([
            {"value": "Scope Compliance", "weight": 0.0, "hard_gate": True, "rubric": RUBRIC},
            {"value": "Honesty", "weight": 0.5, "rubric": RUBRIC},
            {"value": "Care", "weight": 0.5},  # no rubric — must be stripped
        ])
        out = _validate_value_rubrics(prof, "test_agent")
        names = [v["value"] for v in out["values"]]
        self.assertEqual(names, ["Scope Compliance", "Honesty"])
        scored = [v for v in out["values"] if not v.get("hard_gate")]
        self.assertAlmostEqual(sum(v["weight"] for v in scored), 1.0, places=3)

    def test_fully_rubriced_profile_is_unchanged(self):
        values = [
            {"value": "Scope Compliance", "weight": 0.0, "hard_gate": True, "rubric": RUBRIC},
            {"value": "Honesty", "weight": 0.6, "rubric": RUBRIC},
            {"value": "Care", "weight": 0.4, "rubric": [{"score": 1.0}]},  # legacy list shape
        ]
        prof = profile_with(values)
        out = _validate_value_rubrics(prof, "test_agent")
        self.assertIs(out, prof, "no-op validation must not copy the profile")
        self.assertEqual(out["values"], values)

    def test_empty_values_is_noop(self):
        prof = profile_with([])
        self.assertIs(_validate_value_rubrics(prof, "test_agent"), prof)


class TestDisclaimerGuard(unittest.TestCase):

    def _gate(self, struct):
        return WillGate(None, values=[], profile={"will_rules": {"structural_requirements": struct}})

    def test_missing_substring_skips_check_instead_of_keyerror(self):
        gate = self._gate({"require_disclaimer": True})  # no substring key at all
        ok, reason = gate.evaluate_draft_structure("Any draft text.")
        self.assertTrue(ok)
        self.assertEqual(reason, "pass")

    def test_blank_substring_skips_check(self):
        gate = self._gate({"require_disclaimer": True, "mandatory_disclaimer_substring": "   "})
        ok, reason = gate.evaluate_draft_structure("Any draft text.")
        self.assertTrue(ok)

    def test_configured_disclaimer_still_enforced(self):
        gate = self._gate({"require_disclaimer": True, "mandatory_disclaimer_substring": "Disclaimer: test"})
        ok, reason = gate.evaluate_draft_structure("Draft without it.")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_disclaimer")
        ok, _ = gate.evaluate_draft_structure("Draft with it. Disclaimer: test")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
