"""
Unit tests for hard-gate violation reasons as compiled data (backlog 49b).

The Will must never derive a gate's failure reason from the value's NAME.
The reason is per-value data (gate_reason), stamped into the compiled
profile by synderesis:

- WillGate.evaluate_hard_gates reads gate_reason from the failing value and
  collapses anything outside ALLOWED_GATE_REASONS to hard_gate_violation.
- _stamp_gate_reasons gives every hard gate an explicit reason at compile
  time: explicit valid key wins, the legacy name map covers DB policies
  written before the key existed, everything else gets the generic reason.
- apply_charter's gate dedupe carries gate_reason across duplicates, so an
  agent-defined gate keeps its reason even when a stale policy row copy of
  the same gate is the one that survives (or vice versa).

Run:  venv/bin/python tests/test_hard_gate_reasons.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.will import WillGate, ALLOWED_GATE_REASONS
from safi_app.core.faculties.synderesis import _stamp_gate_reasons, apply_charter


def gate_with(values):
    return WillGate(None, values=values, profile={})


def failing_ledger(name):
    return [{"value": name, "score": -1.0}]


class ReasonComesFromTheValue(unittest.TestCase):
    def test_explicit_reason_is_reported(self):
        values = [{"value": "Answer Quality", "hard_gate": True,
                   "gate_reason": "ethical_violation"}]
        verdict, reason = gate_with(values).evaluate_hard_gates(
            failing_ledger("Answer Quality"))
        self.assertEqual(verdict, "violation")
        self.assertEqual(reason, "ethical_violation")

    def test_missing_reason_falls_back_to_generic(self):
        values = [{"value": "Answer Quality", "hard_gate": True}]
        verdict, reason = gate_with(values).evaluate_hard_gates(
            failing_ledger("Answer Quality"))
        self.assertEqual(verdict, "violation")
        self.assertEqual(reason, "hard_gate_violation")

    def test_invalid_reason_cannot_invent_a_routing_path(self):
        values = [{"value": "Answer Quality", "hard_gate": True,
                   "gate_reason": "reboot_the_server"}]
        verdict, reason = gate_with(values).evaluate_hard_gates(
            failing_ledger("Answer Quality"))
        self.assertEqual(verdict, "violation")
        self.assertEqual(reason, "hard_gate_violation")

    def test_the_name_alone_no_longer_maps(self):
        # The historical name-based mapping is gone from the Will: a gate
        # named like the old table entries but lacking gate_reason gets the
        # generic reason. Compile-time stamping is what preserves behavior
        # for real profiles.
        values = [{"value": "Grounding Fidelity", "hard_gate": True}]
        verdict, reason = gate_with(values).evaluate_hard_gates(
            failing_ledger("Grounding Fidelity"))
        self.assertEqual(verdict, "violation")
        self.assertEqual(reason, "hard_gate_violation")

    def test_passing_gates_still_approve(self):
        values = [{"value": "Answer Quality", "hard_gate": True,
                   "gate_reason": "ethical_violation"}]
        verdict, reason = gate_with(values).evaluate_hard_gates(
            [{"value": "Answer Quality", "score": 1.0}])
        self.assertEqual(verdict, "approve")
        self.assertEqual(reason, "hard_gates_passed")


class CompileTimeStamping(unittest.TestCase):
    def test_legacy_names_are_stamped(self):
        profile = {"values": [
            {"value": "Scope Compliance", "hard_gate": True},
            {"value": "Grounding Fidelity", "hard_gate": True},
        ]}
        out = _stamp_gate_reasons(profile)
        self.assertEqual(out["values"][0]["gate_reason"], "scope_violation")
        self.assertEqual(out["values"][1]["gate_reason"], "grounding_violation")

    def test_unknown_gate_gets_generic_reason(self):
        profile = {"values": [{"value": "House Style", "hard_gate": True}]}
        out = _stamp_gate_reasons(profile)
        self.assertEqual(out["values"][0]["gate_reason"], "hard_gate_violation")

    def test_explicit_valid_reason_is_preserved(self):
        profile = {"values": [{"value": "House Style", "hard_gate": True,
                               "gate_reason": "ethical_violation"}]}
        out = _stamp_gate_reasons(profile)
        self.assertEqual(out["values"][0]["gate_reason"], "ethical_violation")

    def test_invalid_explicit_reason_is_replaced(self):
        profile = {"values": [{"value": "Scope Compliance", "hard_gate": True,
                               "gate_reason": "not_a_reason"}]}
        out = _stamp_gate_reasons(profile)
        self.assertEqual(out["values"][0]["gate_reason"], "scope_violation")

    def test_scored_values_are_untouched(self):
        profile = {"values": [{"value": "Clarity", "weight": 1.0}]}
        out = _stamp_gate_reasons(profile)
        self.assertNotIn("gate_reason", out["values"][0])

    def test_every_stamped_reason_is_will_routable(self):
        profile = {"values": [
            {"value": "Scope Compliance", "hard_gate": True},
            {"value": "Grounding Fidelity", "hard_gate": True},
            {"value": "Anything Else", "hard_gate": True},
        ]}
        for v in _stamp_gate_reasons(profile)["values"]:
            self.assertIn(v["gate_reason"],
                          ALLOWED_GATE_REASONS | {"hard_gate_violation"})


class DedupeCarriesTheReason(unittest.TestCase):
    def _merge(self, profile_gate, policy_gate):
        profile = {"values": [profile_gate], "worldview": "w"}
        return apply_charter(profile, None, policy_values=[policy_gate])

    def test_agent_reason_survives_a_stale_policy_copy(self):
        # The agent's definition carries gate_reason; the policy row is a
        # copy seeded before the key existed. Exactly the shipped demo
        # policy situation observed in the dev database.
        out = self._merge(
            {"value": "Answer Quality", "hard_gate": True,
             "gate_reason": "ethical_violation"},
            {"value": "Answer Quality", "hard_gate": True, "weight": 0.0},
        )
        gates = [v for v in out["values"]
                 if (v.get("value") or v.get("name")) == "Answer Quality"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0].get("gate_reason"), "ethical_violation")

    def test_reason_flows_the_other_way_too(self):
        out = self._merge(
            {"value": "Answer Quality", "hard_gate": True},
            {"value": "Answer Quality", "hard_gate": True, "weight": 0.0,
             "gate_reason": "ethical_violation"},
        )
        gates = [v for v in out["values"]
                 if (v.get("value") or v.get("name")) == "Answer Quality"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0].get("gate_reason"), "ethical_violation")


if __name__ == "__main__":
    unittest.main()
