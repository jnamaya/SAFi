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
        safi = make_safi(self._profile(substring="   "))
        text = "A refusal."
        self.assertEqual(safi._enforce_redirect_structure(text), text)

    def test_list_will_rules_redirect_is_noop(self):
        safi = make_safi({"will_rules": [], "style": ""})
        text = "A refusal."
        self.assertEqual(safi._enforce_redirect_structure(text), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
