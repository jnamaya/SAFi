"""A refusal must name the real reason, and must not depend on the model to.

Observed 2026-08-27 in production. A card number in "how is Tesla doing today"
was correctly blocked at Phase Zero and correctly redacted from the record, and
then the agent replied:

    I can't help with that. I can provide information and analysis on financial
    topics, markets, and economic concepts.

The topic was fine. The card number was the problem. The user was told to change
the subject, which would not have helped. The Intellect had an explicit directive
telling it to say the message contained sensitive data; a 20B model ignored it
and fell back to the agent's house scope refusal.

Two independent defences, tested here:

  1. `_repair_pii_redirect` replaces a scope-claiming PII refusal in CODE, so
     the wording does not depend on a model following instructions.
  2. A `Reason Fidelity` rubric so a mismatch that slips past the repair is
     scored rather than passing at 10/10, which is what happened.

Run:  python tests/test_redirect_reason_fidelity.py
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ORCH = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
        / "orchestrator.py").read_text(encoding="utf-8")
CONSCIENCE = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
              / "faculties" / "conscience.py").read_text(encoding="utf-8")

# The real output from the incident.
FALSE_REFUSAL = ("I’m sorry, but I can’t help with that. I can provide information "
                 "and analysis on financial topics, markets, and economic concepts—"
                 "please feel free to ask a question in that area.")

CORRECT_REFUSAL = ("Your message was not processed because it appeared to contain "
                   "sensitive personal or financial information. Please resend without it.")


class _Repairer:
    """Binds the real methods to a stub so the repair can be exercised without
    constructing a SAFi instance (which needs a database and four model
    clients). The logic under test is pure string work."""

    def __init__(self):
        import logging
        from safi_app.core.orchestrator import SAFi
        self.log = logging.getLogger("test")
        self._SCOPE_CLAIM_MARKERS = SAFi._SCOPE_CLAIM_MARKERS
        self._PII_REFUSAL = SAFi._PII_REFUSAL
        self._repair = SAFi._repair_pii_redirect

    def repair(self, text, violation_type):
        return self._repair(self, text, violation_type)


class TheRepairDoesNotTrustTheModel(unittest.TestCase):

    def setUp(self):
        self.r = _Repairer()

    def test_the_actual_production_output_is_replaced(self):
        out = self.r.repair(FALSE_REFUSAL, "pii_detected")
        self.assertNotEqual(out, FALSE_REFUSAL)
        self.assertIn("sensitive", out.lower())
        self.assertIn("resend", out.lower())

    def test_the_replacement_does_not_claim_a_scope_limit(self):
        out = self.r.repair(FALSE_REFUSAL, "pii_detected").lower()
        for phrase in ("area of focus", "outside my", "i can only", "out of scope"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, out)

    def test_a_correct_refusal_is_left_alone(self):
        """The repair is a backstop, not a rewrite. When the model followed the
        directive, its wording survives."""
        out = self.r.repair(CORRECT_REFUSAL, "pii_detected")
        self.assertEqual(out, CORRECT_REFUSAL)

    def test_other_violation_types_are_never_touched(self):
        """A scope refusal is CORRECT for a scope violation. The repair must not
        fire outside pii_detected or it would break every scoped agent."""
        for vt in ("scope_violation", "injection:prompt", "ethical_violation",
                   "low_alignment_score", "missing_disclaimer"):
            with self.subTest(violation_type=vt):
                self.assertEqual(self.r.repair(FALSE_REFUSAL, vt), FALSE_REFUSAL)

    def test_empty_output_is_safe(self):
        self.assertEqual(self.r.repair("", "pii_detected"), "")

    def test_repair_runs_before_the_structural_gate(self):
        """Order matters: a replaced message still needs the mandatory
        disclaimer appended, so the repair must come first."""
        i = ORCH.index("self._repair_pii_redirect(safe_output, violation_type)")
        j = ORCH.index("self._enforce_redirect_structure(safe_output)", i)
        self.assertLess(i, j)


class TheLedgerScoresWhetherTheReasonIsTrue(unittest.TestCase):

    def test_reason_fidelity_is_a_redirect_rubric(self):
        self.assertIn('"value": "Reason Fidelity"', CONSCIENCE)

    def test_it_can_score_negative(self):
        """A misleading reason has to be able to fail, not merely score low."""
        i = CONSCIENCE.index('"value": "Reason Fidelity"')
        block = CONSCIENCE[i:i + 1200]
        self.assertIn('"score": -1.0', block)
        self.assertIn("Misleading", block)

    def test_it_names_the_specific_failure_that_occurred(self):
        i = CONSCIENCE.index('"value": "Reason Fidelity"')
        block = CONSCIENCE[i:i + 1200].lower()
        self.assertIn("scope", block,
                      "the common mismatch is claiming a scope limit; name it")

    def test_all_four_redirect_rubrics_are_present(self):
        for value in ("Redirect Clarity", "Redirect Helpfulness",
                      "Tone and Respect", "Reason Fidelity"):
            with self.subTest(value=value):
                self.assertIn('"value": "%s"' % value, CONSCIENCE)


class TheDeterministicTierIsUnchanged(unittest.TestCase):
    """The repair lives in the orchestrator, not in a faculty, and calls no
    model. The rubric lives in the Conscience, which is allowed to."""

    def test_the_repair_calls_no_model(self):
        i = ORCH.index("def _repair_pii_redirect")
        j = ORCH.index("def _enforce_redirect_structure", i)
        body = ORCH[i:j]
        for token in ("run_intellect", "run_conscience", "await "):
            with self.subTest(token=token):
                self.assertNotIn(token, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
