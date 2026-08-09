"""
Written rules only govern once they are compiled into hard gates.

WHY. `WillGate` is deterministic — it reads `will_rules.structural_requirements`,
hard-gate values in the Conscience ledger, and tool allow-lists. It never reads a
prose rule list. So a policy's written rules constrain nothing on their own; the
only runtime consumer is the post-block suggestion engine.

Two behaviours protect that, and both are easy to regress:

1. `assemble_agent` must not DROP prose rules when the two sides of the merge use
   different shapes. A persona with dict-shaped `will_rules` used to force the
   policy's legacy list to `{}`, discarding it silently — invisible until a block
   produced unhelpful suggestions.

2. A compiled gate must be scoreable. Every hard gate must appear in the
   Conscience ledger or the Will fails closed on EVERY request
   (`hard_gate_unscored`), so a gate whose rubric the Conscience cannot use takes
   the agent down rather than degrading it. `/policies/ai/generate` sets
   `hard_gate`/`weight` itself and drops rubric-less gates for that reason; this
   asserts the resulting shape survives `_validate_value_rubrics`.

Run:  venv/bin/python tests/test_rule_compilation.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.synderesis import assemble_agent, _validate_value_rubrics
from safi_app.core.faculties.will import WillGate

SCORED_RUBRIC = {"description": "r", "scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}

# The shape /policies/ai/generate emits for gen_type == 'compile_rules'.
COMPILED_GATE = {
    "name": "Compensation Confidentiality",
    "description": "The response must never disclose another employee's pay.",
    "hard_gate": True,
    "weight": 0.0,
    "rubric": {
        "description": "Checks whether the response reveals compensation data.",
        "scoring_guide": [
            {"score": 1.0, "criteria": "Does not disclose any individual compensation figure."},
            {"score": -1.0, "criteria": "States or estimates a specific person's pay."},
        ],
    },
}


class TestProseRuleMergePreservesBothShapes(unittest.TestCase):
    """assemble_agent must never silently discard written rules."""

    def test_dict_persona_keeps_policy_prose_list(self):
        # The regression: persona dict + policy list -> policy list vanished.
        persona = {
            "name": "A",
            "values": [],
            "will_rules": {"structural_requirements": {"require_disclaimer": True}},
        }
        governance = {
            "global_values": [],
            "global_will_rules": ["The response must not promise specific outcomes."],
        }
        merged = assemble_agent(persona, governance)["will_rules"]
        self.assertIsInstance(merged, dict)
        self.assertIn("The response must not promise specific outcomes.", merged.get("rules", []))
        # The structured side must survive the fix untouched.
        self.assertTrue(merged["structural_requirements"]["require_disclaimer"])

    def test_list_persona_keeps_policy_dict_prose(self):
        persona = {"name": "A", "values": [], "will_rules": ["Persona rule."]}
        governance = {
            "global_values": [],
            "global_will_rules": {"rules": ["Policy rule."], "structural_requirements": {}},
        }
        merged = assemble_agent(persona, governance)["will_rules"]
        self.assertEqual(merged.get("rules"), ["Policy rule.", "Persona rule."])

    def test_governance_prose_precedes_persona_prose(self):
        # Same ordering as the pure-list branch: governance first.
        persona = {"name": "A", "values": [], "will_rules": ["P."]}
        governance = {"global_values": [], "global_will_rules": ["G."]}
        self.assertEqual(assemble_agent(persona, governance)["will_rules"], ["G.", "P."])

    def test_duplicate_rule_appears_once(self):
        persona = {"name": "A", "values": [], "will_rules": {"rules": ["Same rule."]}}
        governance = {"global_values": [], "global_will_rules": ["Same rule."]}
        merged = assemble_agent(persona, governance)["will_rules"]
        self.assertEqual(merged.get("rules"), ["Same rule."])

    def test_no_prose_anywhere_adds_no_rules_key(self):
        persona = {"name": "A", "values": [], "will_rules": {"structural_requirements": {}}}
        governance = {"global_values": [], "global_will_rules": []}
        self.assertNotIn("rules", assemble_agent(persona, governance)["will_rules"])


class TestCompiledGateIsEnforceable(unittest.TestCase):
    """A compiled gate must survive compile-time validation and actually block."""

    def test_compiled_gate_passes_rubric_validation(self):
        prof = {"name": "HR Agent", "values": [
            dict(COMPILED_GATE, value=COMPILED_GATE["name"]),
            {"value": "Helpfulness", "weight": 1.0, "rubric": SCORED_RUBRIC},
        ]}
        # Must not raise: a gate that fails here takes the whole agent down.
        _validate_value_rubrics(prof, "hr_agent")

    def test_compiled_gate_blocks_on_negative_score(self):
        gate = dict(COMPILED_GATE, value=COMPILED_GATE["name"])
        will = WillGate(None, values=[gate], profile={})
        decision, _ = will.evaluate_hard_gates(
            [{"value": "Compensation Confidentiality", "score": -1.0}]
        )
        self.assertEqual(decision, "violation")

    def test_compiled_gate_approves_when_prohibited_act_absent(self):
        # The +1.0 criteria must be satisfiable by a response that never touches
        # the topic, otherwise every unrelated turn is blocked.
        gate = dict(COMPILED_GATE, value=COMPILED_GATE["name"])
        will = WillGate(None, values=[gate], profile={})
        decision, _ = will.evaluate_hard_gates(
            [{"value": "Compensation Confidentiality", "score": 1.0}]
        )
        self.assertEqual(decision, "approve")

    def test_unscored_compiled_gate_fails_closed(self):
        # Documents the cost of adding gates: one missing ledger entry blocks.
        gate = dict(COMPILED_GATE, value=COMPILED_GATE["name"])
        will = WillGate(None, values=[gate], profile={})
        decision, reason = will.evaluate_hard_gates([{"value": "Something Else", "score": 1.0}])
        self.assertEqual(decision, "violation")
        self.assertEqual(reason, "hard_gate_unscored")

    def test_gate_weight_is_zero_so_spirit_is_unaffected(self):
        self.assertEqual(COMPILED_GATE["weight"], 0.0)
        self.assertTrue(COMPILED_GATE["hard_gate"])


class TestWillIgnoresProseRules(unittest.TestCase):
    """The premise of the whole item: prose alone enforces nothing.

    If this test ever fails, prose rules gained an enforcement path and the
    wizard's 'these do not block on their own' copy has become a lie.
    """

    def test_prose_rule_does_not_block_a_draft(self):
        will = WillGate(None, values=[], profile={
            "will_rules": {"rules": ["The response must not mention competitors."]}
        })
        ok, _ = will.evaluate_draft_structure("Our competitor Acme is cheaper.")
        self.assertTrue(ok)

    def test_prose_rule_creates_no_hard_gate(self):
        will = WillGate(None, values=[], profile={
            "will_rules": {"rules": ["The response must not mention competitors."]}
        })
        decision, reason = will.evaluate_hard_gates([])
        self.assertEqual(decision, "approve")
        self.assertEqual(reason, "no_hard_gates_defined")


if __name__ == "__main__":
    unittest.main(verbosity=2)
