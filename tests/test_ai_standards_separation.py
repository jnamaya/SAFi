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
        mixed = {"values": [{"name": "Accuracy", "weight": 1.0, "hard_gate": False, "rubric": RUBRIC}]}
        policy = [{"name": "Helpfulness", "weight": 1.0,
                   "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}}]
        out = apply_charter(base(), CHARTER, policy_values=policy,
                            charter_weight=0.40, ai_standards=mixed)
        scored = {v["value"]: v["weight"] for v in out["values"] if not v.get("hard_gate")}
        self.assertEqual(set(scored), {"Integrity", "Accuracy", "Helpfulness"})
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
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        will = WillGate(None, values=out["values"], profile=out)
        ok, reason = will.evaluate_draft_structure("Here is the answer.")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_disclaimer")
        ok, _ = will.evaluate_draft_structure("Here is the answer.\n\nAI-assisted.")
        self.assertTrue(ok)

    def test_no_disclosure_gate_is_created_from_the_disclaimer(self):
        out = apply_charter(base(), CHARTER, policy_values=[], ai_standards=STANDARDS)
        gate_names = [str(v.get("value") or "").lower() for v in out["values"] if v.get("hard_gate")]
        self.assertNotIn("genai disclosure", gate_names)


class OmissionBasedStandardsAreRefused(unittest.TestCase):

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
        patterns = ("does not include", "does not contain", "does not disclose", "does not state",
                    "fails to include", "fails to mention", "fails to disclose", "fails to state",
                    "omits", "without disclosing", "lacks a", "no statement")
        for phrase in self.OMISSION_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(any(p in phrase.lower() for p in patterns),
                                f"no pattern catches: {phrase}")

    def test_commission_criteria_still_pass(self):
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
