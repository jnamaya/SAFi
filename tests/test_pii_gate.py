"""PII blocking end to end: Phase Zero, the Will, and the Synderesis floor.

GOVERNANCE_BACKLOG 83. The unit tests in test_pii_validators.py cover the
detectors. These cover the three things that make them a governance control:

  1. Phase Zero refuses the prompt BEFORE the Intellect is called, so the value
     never reaches the drafting model.
  2. The Will refuses a DRAFT containing an identifier, which is the half that
     matters once agents hold tools and can read an account number out of a
     document and repeat it.
  3. The org's list is a FLOOR: Synderesis unions it, so an agent can add a
     validator and cannot remove one.

Plus the invariant the whole feature rests on: with nothing configured, every
one of these is inert.

No model is involved in any path tested here.

Run:  python tests/test_pii_gate.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.phase_zero import PhaseZeroGate  # noqa: E402
from safi_app.core.faculties.will import WillGate  # noqa: E402
from safi_app.core.faculties import synderesis  # noqa: E402

SSN = "123-45-6789"
CARD = "4111111111111111"


class PhaseZeroStopsItBeforeTheModel(unittest.TestCase):

    def setUp(self):
        self.gate = PhaseZeroGate()

    def test_a_prompt_with_an_ssn_is_blocked(self):
        ok, reason = self.gate.evaluate_prompt("my ssn is %s" % SSN, None, ["ssn"])
        self.assertFalse(ok)
        self.assertEqual(reason, "pii_detected")

    def test_the_reason_never_carries_the_value(self):
        """The reason string is written to the governance record and the log."""
        _, reason = self.gate.evaluate_prompt("ssn %s" % SSN, None, ["ssn"])
        self.assertNotIn(SSN, reason)
        self.assertNotIn("6789", reason)

    def test_nothing_enabled_means_the_prompt_passes(self):
        """The default. An org that never opens the settings tab is unaffected."""
        for cfg in (None, []):
            with self.subTest(cfg=cfg):
                ok, reason = self.gate.evaluate_prompt("my ssn is %s" % SSN, None, cfg)
                self.assertTrue(ok, "a PII prompt must pass when nothing is enabled")
                self.assertEqual(reason, "pass")

    def test_a_validator_that_is_not_enabled_does_not_fire(self):
        ok, _ = self.gate.evaluate_prompt("card %s" % CARD, None, ["ssn"])
        self.assertTrue(ok, "only ticked validators may block")

    def test_ordinary_text_still_passes_with_everything_on(self):
        ok, _ = self.gate.evaluate_prompt(
            "Call me on 555-123-4567 about invoice 8841-22.", None,
            ["ssn", "credit_card", "iban", "aba"])
        self.assertTrue(ok)


class TheWillStopsItLeavingInADraft(unittest.TestCase):

    def _gate(self, validators=None):
        # llm_provider is positional and deliberately unused inside WillGate
        # (see its constructor comment), so None is the honest value here.
        return WillGate(
            None,
            values=[],
            profile={"will_rules": {"structural_requirements":
                     ({"pii_validators": validators} if validators is not None else {})}},
        )

    def test_a_draft_containing_a_card_number_is_refused(self):
        ok, reason = self._gate(["credit_card"]).evaluate_draft_structure(
            "Your card on file is %s." % CARD)
        self.assertFalse(ok)
        self.assertEqual(reason, "pii_detected")

    def test_a_clean_draft_passes(self):
        ok, _ = self._gate(["credit_card", "ssn"]).evaluate_draft_structure(
            "Your card on file ends in the last four digits shown in your account.")
        self.assertTrue(ok)

    def test_nothing_configured_means_no_check(self):
        """A draft full of identifiers passes when the org enabled nothing.
        This is the default state and must stay inert."""
        for cfg in (None, []):
            with self.subTest(cfg=cfg):
                ok, _ = self._gate(cfg).evaluate_draft_structure(
                    "ssn %s card %s" % (SSN, CARD))
                self.assertTrue(ok)


class TheOrgListIsAFloor(unittest.TestCase):
    """Synderesis unions the org's AI Standards into will_rules. A union cannot
    subtract, which is what makes the floor structural rather than something the
    settings UI has to police."""

    def _merge(self, org_list, agent_list):
        profile = {"will_rules": {"structural_requirements":
                                  {"pii_validators": list(agent_list)}}}
        standards = {"structural_requirements": {"pii_validators": list(org_list)}}
        out = synderesis._apply_ai_standards(profile, standards)
        return out["will_rules"]["structural_requirements"].get("pii_validators", [])

    def test_an_agent_cannot_remove_what_the_org_enabled(self):
        merged = self._merge(org_list=["ssn"], agent_list=[])
        self.assertIn("ssn", merged, "the org floor must survive an empty agent list")

    def test_an_agent_can_add(self):
        merged = self._merge(org_list=["ssn"], agent_list=["credit_card"])
        self.assertIn("ssn", merged)
        self.assertIn("credit_card", merged)

    def test_the_union_does_not_duplicate(self):
        merged = self._merge(org_list=["ssn"], agent_list=["ssn"])
        self.assertEqual(merged.count("ssn"), 1)

    def test_no_org_standards_leaves_the_agent_alone(self):
        profile = {"will_rules": {"structural_requirements": {"pii_validators": ["ssn"]}}}
        out = synderesis._apply_ai_standards(profile, {})
        self.assertEqual(
            out["will_rules"]["structural_requirements"]["pii_validators"], ["ssn"])


class TheFloorFollowsTheActingUser(unittest.TestCase):
    """GOVERNANCE_BACKLOG 84. _pii_enabled unions the compiled profile with the
    ACTING USER'S org standards, so the five agents SAFi ships stop being exempt.

    Source-level: the union itself is exercised by TheOrgListIsAFloor above, and
    constructing a real SAFi instance needs a database, four model clients and a
    vector store. What can regress here is the wiring — a call site that forgets
    to pass org_id silently reverts every built-in agent to uncovered, which is
    exactly the failure this item was opened for.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                   / "orchestrator.py").read_text(encoding="utf-8")

    def test_the_helper_accepts_the_acting_org(self):
        self.assertIn("def _pii_enabled(self, org_id=None)", self.src)
        self.assertIn("def _redact_pii(self, text, org_id=None)", self.src)

    def test_it_reads_the_org_standards_not_only_the_profile(self):
        i = self.src.index("def _pii_enabled")
        body = self.src[i:i + 3000]
        self.assertIn("db.get_ai_standards(org_id)", body,
                      "the acting user's org floor must be looked up per turn")

    def test_every_call_site_passes_org_id(self):
        """A bare _pii_enabled() or _redact_pii(x) is the regression: it compiles,
        it passes every other test, and it quietly un-covers the built-ins."""
        self.assertNotIn("self._pii_enabled()", self.src)
        self.assertNotIn("self._redact_pii(original_prompt)", self.src)
        self.assertNotIn('self._redact_pii(blocked_draft or "")', self.src)
        self.assertGreaterEqual(self.src.count("self._pii_enabled(org_id)"), 2)

    def test_a_failed_lookup_does_not_take_down_the_turn(self):
        """Opposite of the Will's outbound check, deliberately. There a control
        IS configured and cannot be evaluated, so it fails closed. Here we are
        still asking whether one is configured, and an unreachable org row must
        not block every request."""
        i = self.src.index("def _pii_enabled")
        body = self.src[i:i + 3000]
        self.assertIn("except Exception", body)
        self.assertIn("self.log.warning", body,
                      "a skipped floor must be visible, not silent")


class TheDeterministicTierStaysDeterministic(unittest.TestCase):
    """CLAUDE.md's load-bearing invariant. This feature adds enforcement, and
    enforcement may never acquire a model call."""

    # An actual model CALL, not the word "llm_provider". will.py deliberately
    # retains an unused llm_provider parameter for interface symmetry with the
    # other faculties, and CLAUDE.md documents that: "will.py holds an unused
    # llm_provider for interface symmetry and its one async def awaits nothing."
    # Asserting the identifier's absence would fail on intended design and
    # tempt someone to delete a parameter the docs say to keep. What must never
    # appear is an invocation.
    FACULTIES = ("phase_zero", "will", "synderesis")
    FORBIDDEN_CALLS = ("run_intellect", "run_conscience", "AsyncOpenAI",
                       "AsyncAnthropic", "chat.completions",
                       "await self.llm_provider", "self.llm_provider.")

    def test_no_model_call_entered_the_deterministic_faculties(self):
        root = Path(__file__).resolve().parent.parent / "safi_app" / "core" / "faculties"
        for name in self.FACULTIES:
            src = (root / ("%s.py" % name)).read_text(encoding="utf-8")
            for token in self.FORBIDDEN_CALLS:
                with self.subTest(faculty=name, token=token):
                    self.assertNotIn(token, src,
                                     "%s.py must never invoke a model" % name)

    def test_phase_zero_and_synderesis_hold_no_provider_at_all(self):
        """Stricter than will.py, and correct: neither has an interface reason
        to carry the parameter, so the identifier should not appear either."""
        root = Path(__file__).resolve().parent.parent / "safi_app" / "core" / "faculties"
        for name in ("phase_zero", "synderesis"):
            src = (root / ("%s.py" % name)).read_text(encoding="utf-8")
            with self.subTest(faculty=name):
                self.assertNotIn("llm_provider", src)

    def test_the_validators_live_outside_the_faculties(self):
        """Same boundary as threat_intel.py: adding a detector must never
        require editing a faculty."""
        core = Path(__file__).resolve().parent.parent / "safi_app" / "core"
        self.assertTrue((core / "pii_validators.py").exists())
        self.assertFalse((core / "faculties" / "pii_validators.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
