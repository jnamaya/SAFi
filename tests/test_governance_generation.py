"""
The two endpoints that GENERATE governance config must not degenerate quietly.

WHY. `/policies/ai/generate` drafts most of the wizard's prose, which is
harmless to get wrong — an author reads it in a text box. Two of its tasks are
different: `compile_rules` turns written rules into scored standards, and
`ai_standards` proposes organization-wide ones. Their output becomes
enforcement, so a bad answer blocks real traffic and an empty one reads as
"there is nothing to enforce here".

Three properties, each of which failed in production on 2026-08-09:

  * Not the light model. Measured on a real 15-page AI policy, gpt-oss-20b
    returned a bare "{}" — two characters — where the Conscience model returned
    a full analysis. "{}" PARSES, so it surfaced as an empty finding rather than
    a failure.
  * Temperature 0 and a real token budget. `compile_rules` inherited the
    drafting defaults (0.7, 4096) while being asked for strict JSON carrying a
    rubric per standard; it returned unparseable output, and the import died on
    a bare 422 that named neither cause.
  * No omission-based failure criteria. A standard whose -1.0 reads "does not
    include X" fires on every response that never raised the topic. One such
    standard — compiled from "disclose that AI was used" — blocked every answer
    a live agent gave.

The document-import path these guards were first written for was withdrawn (see
backlog 23d); the guards stay because the same failure shapes apply to anything
writing governance config.

Run:  venv/bin/python tests/test_governance_generation.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api import policy_api_routes as pr

SRC = Path(pr.__file__).read_text(encoding="utf-8")

# The shapes a model actually produced when asked to compile an
# obligation-to-include into a standard.
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
        """Asserted by membership, not by the literal tuple: the set grows, and
        pinning its exact text made adding a task fail here for no reason."""
        line = next(l for l in SRC.splitlines() if "_DOCUMENT_TASKS = " in l)
        for task in ("compile_rules", "ai_standards"):
            self.assertIn(task, line,
                          f"'{task}' writes governance config and must not run on the light model")


class StructuredTasksPinTheirSampling(unittest.TestCase):

    def test_compile_rules_sets_its_own_temperature_and_budget(self):
        """It asks for strict JSON with a full rubric per standard. Latitude
        produces malformed output; too small a budget truncates it mid-object,
        and both surface to the caller identically."""
        self.assertIn("gen_temperature = 0.0", SRC)
        self.assertIn("gen_max_tokens = 8192", SRC)

    def test_truncation_is_reported_distinctly_from_malformation(self):
        """Different advice: convert fewer at once, versus just retry. One
        generic message sent an operator hunting through a 15-page document for
        a clause that was never the problem."""
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
        """The guard is a phrase list, so it is only as good as its coverage."""
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
        """`ai_standards` generates standards directly, with no compile step
        between it and the author — so the rule has to be in its prompt too."""
        flat = " ".join(SRC.split())
        self.assertIn("act of commission", flat)
        self.assertIn("Do NOT suggest standards that require the response to INCLUDE", flat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
