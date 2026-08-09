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

  * A standard is BLOCKING or SCORED, chosen per standard. Blocking ones are
    hard gates at weight 0, outside the split. Scored ones join the
    ORGANIZATION's share alongside the charter's values — not a third tier, so
    the two-way split and $A_t$'s definition are untouched.

    Scored is the default, and that is a safety property rather than a taste:
    every blocking standard must appear in the Conscience ledger on EVERY turn
    or the Will fails closed, so a tier where each addition is a gate becomes
    more fragile the more it is used.
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
    "values": [{"name": "Compensation Confidentiality", "hard_gate": True, "rubric": RUBRIC}],
    "structural_requirements": {"require_disclaimer": True,
                                "mandatory_disclaimer_substring": "AI-assisted."},
    "early_prompt_blacklist": ["insider trading tips"],
}


def base(will_rules=None):
    return {"name": "Agent", "values": [], "will_rules": will_rules or {}}


class StandardsAreGatesOnly(unittest.TestCase):

    def test_a_scored_standard_joins_the_organization_share(self):
        """Not a third tier: a scored standard shares the org's slice with the
        charter's values, so the split stays two-way and A_t is untouched."""
        mixed = {"values": [{"name": "Accuracy", "weight": 1.0, "hard_gate": False, "rubric": RUBRIC}]}
        policy = [{"name": "Helpfulness", "weight": 1.0,
                   "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}}]
        out = apply_charter(base(), CHARTER, policy_values=policy,
                            charter_weight=0.40, ai_standards=mixed)
        scored = {v["value"]: v["weight"] for v in out["values"] if not v.get("hard_gate")}
        self.assertEqual(set(scored), {"Integrity", "Accuracy", "Helpfulness"})
        # Charter value + scored standard divide the org's 40%; policy keeps 60%.
        self.assertAlmostEqual(scored["Integrity"] + scored["Accuracy"], 0.40, places=6)
        self.assertAlmostEqual(scored["Helpfulness"], 0.60, places=6)
        self.assertAlmostEqual(sum(scored.values()), 1.0, places=6)

    def test_a_blocking_standard_stays_outside_the_split(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        gate = next(v for v in out["values"] if v.get("value") == "Compensation Confidentiality")
        self.assertTrue(gate["hard_gate"])
        self.assertEqual(gate["weight"], 0.0)

    def test_scored_values_still_come_only_from_charter_and_policy(self):
        policy = [{"name": "Helpfulness", "weight": 1.0,
                   "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}}]
        out = apply_charter(base(), CHARTER, policy_values=policy,
                            charter_weight=0.40, ai_standards=STANDARDS)
        scored = {v["value"]: v["weight"] for v in out["values"] if not v.get("hard_gate")}
        self.assertEqual(set(scored), {"Integrity", "Helpfulness"})
        self.assertAlmostEqual(scored["Integrity"], 0.40, places=6)
        self.assertAlmostEqual(scored["Helpfulness"], 0.60, places=6)

    def test_adopting_BLOCKING_standards_does_not_move_the_scored_weights(self):
        """A blocking standard sits outside the split, so switching one on must
        not change what any existing agent scores. (A SCORED standard is meant
        to change them — that is what choosing 'scored' asks for.)"""
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



class OmissionBasedStandardsAreRefused(unittest.TestCase):
    """Item 27, guarded server-side rather than by asking the model nicely.

    A rule that requires the response to INCLUDE something can only be broken by
    omission, so as a hard gate it fires on every answer that never raised the
    topic. That is not hypothetical: a "GenAI Disclosure" standard compiled this
    way blocked every response an agent gave. The obligation belongs to the
    disclaimer check, which APPENDS the missing text and re-audits.
    """

    OMISSION_PHRASES = [
        "The response does not include a statement about GenAI use.",
        "Fails to mention the source of the claim.",
        "Omits the required disclosure.",
        "The answer does not disclose that AI was used.",
        "No statement about human oversight is present.",
    ]

    def test_endpoint_rejects_omission_criteria(self):
        src = Path(__file__).resolve().parent.parent / "safi_app" / "api" / "policy_api_routes.py"
        code = src.read_text(encoding="utf-8")
        for probe in ("does not include", "fails to mention", "omits", "no statement"):
            self.assertIn(probe, code,
                          f"the omission guard must catch '{probe}' phrasing")
        self.assertIn("required disclaimer instead", code,
                      "the rejection must point at the mechanism that DOES enforce it")

    def test_every_sample_phrase_is_matched_by_the_guard(self):
        """The guard is a phrase list, so it is only as good as its coverage.
        These are the shapes a model actually produced."""
        patterns = ("does not include", "does not contain", "does not disclose", "does not state",
                    "fails to include", "fails to mention", "fails to disclose", "fails to state",
                    "omits", "without disclosing", "lacks a", "no statement")
        for phrase in self.OMISSION_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(any(p in phrase.lower() for p in patterns),
                                f"no pattern catches: {phrase}")

    def test_commission_criteria_still_pass(self):
        """The guard must not reject legitimate prohibitions."""
        patterns = ("does not include", "does not contain", "does not disclose", "does not state",
                    "fails to include", "fails to mention", "fails to disclose", "fails to state",
                    "omits", "without disclosing", "lacks a", "no statement")
        for phrase in ["States or estimates a specific person's pay.",
                       "Provides a medical diagnosis.",
                       "Reveals another employee's compensation.",
                       "Cites a source that does not exist."]:
            with self.subTest(phrase=phrase):
                self.assertFalse(any(p in phrase.lower() for p in patterns),
                                 f"a valid prohibition was caught: {phrase}")

if __name__ == "__main__":
    unittest.main(verbosity=2)
