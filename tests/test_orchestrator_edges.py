"""
Unit tests for the second-pass edge fixes:

- #1: process_prompt's Phase-0 blacklist read tolerates a legacy list-shaped
  will_rules instead of crashing on list.get().
- #2: a redirect that fails the structural gate on a missing disclaimer is
  repaired deterministically (the mandatory substring is appended) since the
  redirect path is terminal and cannot recurse.

Run:  venv/bin/python tests/test_orchestrator_edges.py
"""
import sys
import logging
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi
from safi_app.core.faculties.will import WillGate

DISCLAIMER = "Disclaimer: I am an AI guide, not a doctor."


def make_safi(profile):
    s = object.__new__(SAFi)
    s.log = logging.getLogger("test.SAFi")
    s.profile = profile
    s.values = []
    s.will_gate = WillGate(None, values=[], profile=profile)
    return s


class TestListWillRulesGuard(unittest.TestCase):
    """#1 — the read pattern (self.profile or {}).get('will_rules', {}) must not
    crash when will_rules is a list. Mirrors orchestrator.py Phase 0."""

    def _blacklist(self, profile):
        wr = (profile or {}).get("will_rules", {})
        return wr.get("early_prompt_blacklist", []) if isinstance(wr, dict) else []

    def test_list_will_rules_yields_empty_blacklist(self):
        self.assertEqual(self._blacklist({"will_rules": []}), [])

    def test_dict_will_rules_yields_blacklist(self):
        profile = {"will_rules": {"early_prompt_blacklist": ["forbidden"]}}
        self.assertEqual(self._blacklist(profile), ["forbidden"])

    def test_missing_will_rules_yields_empty(self):
        self.assertEqual(self._blacklist({}), [])


class TestRedirectStructureRepair(unittest.TestCase):
    """#2 — _enforce_redirect_structure repairs a missing disclaimer."""

    def _profile(self, require=True, substring=DISCLAIMER):
        return {"will_rules": {"structural_requirements": {
            "require_disclaimer": require,
            "mandatory_disclaimer_substring": substring,
        }}}

    def test_missing_disclaimer_is_appended(self):
        safi = make_safi(self._profile())
        out = safi._enforce_redirect_structure("That's outside what I can help with.")
        self.assertIn(DISCLAIMER, out)
        self.assertTrue(out.rstrip().endswith(DISCLAIMER))

    def test_present_disclaimer_is_untouched(self):
        safi = make_safi(self._profile())
        original = f"Outside my area. {DISCLAIMER}"
        self.assertEqual(safi._enforce_redirect_structure(original), original)

    def test_no_disclaimer_rule_is_noop(self):
        safi = make_safi({"will_rules": {"structural_requirements": {}}})
        text = "A plain refusal with no disclaimer requirement."
        self.assertEqual(safi._enforce_redirect_structure(text), text)

    def test_rule_on_but_blank_substring_ships_as_is(self):
        # will.py skips the check when the substring is blank; nothing to append.
        safi = make_safi(self._profile(substring="   "))
        text = "A refusal."
        self.assertEqual(safi._enforce_redirect_structure(text), text)

    def test_list_will_rules_redirect_is_noop(self):
        # Legacy list shape with no disclaimer style text — must not crash.
        safi = make_safi({"will_rules": [], "style": ""})
        text = "A refusal."
        self.assertEqual(safi._enforce_redirect_structure(text), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
