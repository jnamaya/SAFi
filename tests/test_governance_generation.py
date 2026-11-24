import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api import policy_api_routes as pr

SRC = Path(pr.__file__).read_text(encoding="utf-8")

OMISSION_PHRASES = [
    "The response does not include a statement about GenAI use.",
    "Fails to mention the source of the claim.",
    "Omits the required disclosure.",
    "The answer does not disclose that AI was used.",
    "No statement about human oversight is present.",
]
GUARD_PATTERNS = ("does not include", "does not contain", "does not disclose",
                  "does not state", "fails to include", "fails to mention",
                  "fails to disclose", "fails to state", "omits",
                  "without disclosing", "lacks a", "no statement")


class GovernanceTasksUseTheAuditingModel(unittest.TestCase):

    def test_the_task_set_is_routed_away_from_the_light_model(self):
        self.assertIn("Config.CONSCIENCE_MODEL if gen_type in _DOCUMENT_TASKS", SRC)

    def test_every_governance_writing_task_is_in_that_set(self):
        line = next(l for l in SRC.splitlines() if "_DOCUMENT_TASKS = " in l)
        for task in ("compile_rules", "ai_standards"):
            self.assertIn(task, line,
                          f"'{task}' writes governance config and must not run on the light model")


class StructuredTasksPinTheirSampling(unittest.TestCase):

    def test_compile_rules_sets_its_own_temperature_and_budget(self):
        self.assertIn("gen_temperature = 0.0", SRC)
        self.assertIn("gen_max_tokens = 8192", SRC)

    def test_truncation_is_reported_distinctly_from_malformation(self):
        self.assertIn("cut off before it finished", SRC)
        self.assertIn("in batches", SRC)
        self.assertIn('truncated = not cleaned.rstrip().endswith("}")', SRC)


class OmissionBasedStandardsAreRefused(unittest.TestCase):

    def test_the_guard_exists_and_names_the_alternative(self):
        for probe in ("does not include", "fails to mention", "omits", "no statement"):
            self.assertIn(probe, SRC, f"the omission guard must catch '{probe}' phrasing")
        self.assertIn("required disclaimer instead", SRC,
                      "the rejection must point at the mechanism that DOES enforce it")

    def test_every_observed_phrase_is_matched(self):
        for phrase in OMISSION_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(any(p in phrase.lower() for p in GUARD_PATTERNS),
                                f"no pattern catches: {phrase}")

    def test_legitimate_prohibitions_are_not_caught(self):
        for phrase in ["States or estimates a specific person's pay.",
                       "Provides a medical diagnosis.",
                       "Reveals another employee's compensation.",
                       "Cites a source that does not exist."]:
            with self.subTest(phrase=phrase):
                self.assertFalse(any(p in phrase.lower() for p in GUARD_PATTERNS),
                                 f"a valid prohibition was caught: {phrase}")

    def test_the_suggestion_prompt_carries_the_same_rule(self):
        flat = " ".join(SRC.split())
        self.assertIn("act of commission", flat)
        self.assertIn("Do NOT suggest standards that require the response to INCLUDE", flat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
