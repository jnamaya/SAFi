"""
AI Standards are a separate artifact from the Charter.

WHY. A charter is mission and core values — who the organization is, and
something every organization has. AI standards say how its AI must behave: they
are AI-specific, optional, and revised on a different cycle. Filing one as the
other is not untidy, it is a behaviour change, because **charter values are
SCORED**. That is exactly how this broke in production on 2026-08-09: importing
an AI policy wrote a "GenAI Disclosure" entry into `core_values`, the Conscience
scored it -1.0 on every response that did not carry a disclosure, and the Will
redirected every turn.

Two properties this pins:

  * AI Standards contribute HARD GATES ONLY. A scored value there would need a
    third share of the Charter/Policy weight split, changing $A_t$ for every
    existing organization and requiring a change to the published mathematical
    specification. Gates sit outside the split at weight 0, so adopting AI
    standards cannot move anybody's scores.
  * They are OPTIONAL and independent. An org with a charter and no standards,
    or standards and no charter, must compile cleanly — and dropping one must
    not disturb the other.

Run:  venv/bin/python tests/test_ai_standards_separation.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.synderesis import apply_charter
from safi_app.core.faculties.will import WillGate

RUBRIC = {"description": "r", "scoring_guide": [
    {"score": 1.0, "criteria": "does not disclose"},
    {"score": -1.0, "criteria": "discloses a specific person's pay"},
]}

CHARTER = {
    "mission": "Expand economic opportunity.",
    "core_values": [
        {"name": "Integrity", "weight": 1.0,
         "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}},
    ],
}

STANDARDS = {
    "values": [{"name": "Compensation Confidentiality", "rubric": RUBRIC}],
    "structural_requirements": {"require_disclaimer": True,
                                "mandatory_disclaimer_substring": "AI-assisted."},
    "early_prompt_blacklist": ["insider trading tips"],
}


def base(will_rules=None):
    return {"name": "Agent", "values": [], "will_rules": will_rules or {}}


class StandardsAreGatesOnly(unittest.TestCase):

    def test_standards_values_become_hard_gates_at_weight_zero(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        gate = next(v for v in out["values"] if v.get("value") == "Compensation Confidentiality")
        self.assertTrue(gate["hard_gate"])
        self.assertEqual(gate["weight"], 0.0)

    def test_a_weighted_standard_is_forced_to_a_gate(self):
        """Guards the decision itself. If a scored value ever survives from this
        tier, the two-way weight split silently becomes three-way."""
        greedy = {"values": [{"name": "X", "weight": 0.5, "hard_gate": False, "rubric": RUBRIC}]}
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=greedy)
        x = next(v for v in out["values"] if v.get("value") == "X")
        self.assertTrue(x["hard_gate"])
        self.assertEqual(x["weight"], 0.0)

    def test_scored_values_still_come_only_from_charter_and_policy(self):
        policy = [{"name": "Helpfulness", "weight": 1.0,
                   "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}}]
        out = apply_charter(base(), CHARTER, policy_values=policy,
                            charter_weight=0.40, ai_standards=STANDARDS)
        scored = {v["value"]: v["weight"] for v in out["values"] if not v.get("hard_gate")}
        self.assertEqual(set(scored), {"Integrity", "Helpfulness"})
        self.assertAlmostEqual(scored["Integrity"], 0.40, places=6)
        self.assertAlmostEqual(scored["Helpfulness"], 0.60, places=6)

    def test_adopting_standards_does_not_move_the_scored_weights(self):
        """The whole point of gates-only: turning AI standards on must not
        change what any existing agent scores."""
        without = apply_charter(base(), CHARTER, policy_values=[], ai_standards=None)
        with_ = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        pick = lambda p: {v["value"]: v["weight"] for v in p["values"] if not v.get("hard_gate")}
        self.assertEqual(pick(without), pick(with_))


class TheTwoAreIndependent(unittest.TestCase):

    def test_standards_without_a_charter_still_apply(self):
        out = apply_charter(base(), None, policy_values=[], ai_standards=STANDARDS)
        names = [v.get("value") for v in out["values"] if v.get("hard_gate")]
        self.assertIn("Compensation Confidentiality", names)
        self.assertTrue(out["will_rules"]["structural_requirements"]["require_disclaimer"])

    def test_charter_without_standards_is_unchanged(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=None)
        self.assertEqual([v["value"] for v in out["values"]], ["Integrity"])
        self.assertEqual(out["will_rules"], {})

    def test_neither_is_a_no_op(self):
        out = apply_charter(base({"structural_requirements": {"require_disclaimer": True}}),
                            None, policy_values=[], ai_standards=None)
        self.assertEqual(out["will_rules"], {"structural_requirements": {"require_disclaimer": True}})


class DeterministicChecksReachTheWill(unittest.TestCase):

    def test_disclaimer_and_blacklist_arrive_on_the_profile(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        wr = out["will_rules"]
        self.assertEqual(wr["structural_requirements"]["mandatory_disclaimer_substring"], "AI-assisted.")
        self.assertIn("insider trading tips", wr["early_prompt_blacklist"])

    def test_the_disclaimer_is_a_literal_check_not_a_scored_one(self):
        """Item 27's lesson. A mandated disclosure belongs to the structural
        tier, which APPENDS the missing text and re-audits. Routed to a gate
        instead, it blocks every response that omits it — and an obligation to
        include something can only ever be violated by omission."""
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        will = WillGate(None, values=out["values"], profile=out)
        ok, reason = will.evaluate_draft_structure("Here is the answer.")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_disclaimer")
        # missing_disclaimer is the repairable branch: the orchestrator appends
        # the text and re-audits rather than redirecting the turn.
        ok, _ = will.evaluate_draft_structure("Here is the answer.\n\nAI-assisted.")
        self.assertTrue(ok)

    def test_no_disclosure_gate_is_created_from_the_disclaimer(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        gate_names = [str(v.get("value") or "").lower() for v in out["values"] if v.get("hard_gate")]
        self.assertNotIn("genai disclosure", gate_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
