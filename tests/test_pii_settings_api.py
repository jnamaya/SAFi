"""The settings surface for PII checks: a fixed menu, and only a fixed menu.

GOVERNANCE_BACKLOG 83. The engine is tested in test_pii_validators.py and
test_pii_gate.py. What matters here is the boundary an admin can reach:

  * the catalogue the UI renders comes from the detectors themselves, so a
    check's precision note cannot drift from its implementation;
  * the save route accepts validator KEYS and nothing else. There is no
    free-text field anywhere in this path by design, and this file is what
    stops one being added by accident. A caller-supplied pattern would run on
    every turn inside the deterministic tier, where there is no timeout and no
    model to blame for a catastrophic backtrack.

Route-level checks are done against the module's validation logic rather than
by standing up Flask with a session: the rule being protected is "only known
keys survive", and that lives in pii_validators.normalize plus the route's
rejection branch.

Run:  python tests/test_pii_settings_api.py
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core import pii_validators as pv  # noqa: E402

ROUTES = (Path(__file__).resolve().parent.parent
          / "safi_app" / "api" / "organizations.py").read_text(encoding="utf-8")
ORG_UI = (Path(__file__).resolve().parent.parent
          / "public" / "js" / "ui" / "settings" / "ui-settings-org.js").read_text(encoding="utf-8")


class TheCatalogueIsServedFromTheDetectors(unittest.TestCase):

    def test_the_endpoint_exists_and_is_admin_only(self):
        self.assertIn("/organizations/<org_id>/pii-checks", ROUTES)
        i = ROUTES.index("/organizations/<org_id>/pii-checks")
        self.assertIn("@require_role('admin')", ROUTES[i:i + 200])

    def test_it_is_scoped_to_the_caller_s_own_org(self):
        i = ROUTES.index("def list_pii_checks")
        body = ROUTES[i:i + 600]
        self.assertIn("get_current_org_id()", body)
        self.assertIn("403", body)

    def test_it_returns_the_catalogue_not_a_hardcoded_list(self):
        i = ROUTES.index("def list_pii_checks")
        self.assertIn("pii_validators.catalogue()", ROUTES[i:i + 600])

    def test_every_catalogue_entry_can_be_rendered(self):
        for e in pv.catalogue():
            with self.subTest(key=e["key"]):
                self.assertTrue(e["key"] and e["label"] and e["note"])


class OnlyKnownKeysSurviveTheSaveRoute(unittest.TestCase):
    """The property that makes 'no user-supplied regex' true rather than
    merely intended."""

    def test_the_route_rejects_unknown_keys(self):
        i = ROUTES.index("pii = structural.get('pii_validators')")
        body = ROUTES[i:i + 1400]
        self.assertIn("VALIDATOR_KEYS", body, "the route must check against the catalogue")
        self.assertIn("400", body, "an unknown key must be rejected, not dropped")

    def test_the_route_rejects_a_non_list(self):
        i = ROUTES.index("pii = structural.get('pii_validators')")
        self.assertIn("must be an array", ROUTES[i:i + 400])

    def test_a_regex_is_not_a_valid_key(self):
        """The specific thing being prevented."""
        for attempt in (r"\d{3}-\d{2}-\d{4}", ".*", "(a+)+$", "ssn|custom"):
            with self.subTest(attempt=attempt):
                self.assertEqual(pv.normalize([attempt]), [],
                                 "a pattern must never normalize to a validator")

    def test_normalize_keeps_the_valid_ones_from_a_mixed_payload(self):
        self.assertEqual(pv.normalize(["ssn", r"\d+", "iban"]), ["ssn", "iban"])

    def test_an_empty_list_is_a_legitimate_value(self):
        """Unticking the master switch must actually turn the checks off, so []
        has to be storable and distinct from 'not supplied'."""
        self.assertEqual(pv.normalize([]), [])


class TheUiSendsOnlyCheckboxes(unittest.TestCase):

    def test_there_is_no_free_text_input_for_patterns(self):
        """A text box here would be the whole hazard. The panel must contain
        checkboxes and nothing that accepts typed input."""
        start = ORG_UI.index('charter-pii-panel')
        panel = ORG_UI[start:start + 900]
        self.assertNotIn('type="text"', panel)
        self.assertNotIn("type='text'", panel)

    def test_the_save_collects_ticked_boxes_only(self):
        self.assertIn(".pii-check:checked", ORG_UI)

    def test_unticking_the_master_switch_sends_an_empty_list(self):
        """Not 'omit the key'. Omitting would leave the previous value in place,
        so turning the feature off would silently fail."""
        i = ORG_UI.index("const piiOn")
        self.assertIn("[]", ORG_UI[i:i + 400])

    def test_the_copy_does_not_over_promise_coverage(self):
        """GOVERNANCE_BACKLOG 84. Org AI Standards reach agents in the org; the
        five agents SAFi ships have no org and are not covered. The label said
        "before it reaches a model", which reads as the whole deployment, and a
        compliance officer's first question about a PII control is which agents
        it covers. Until the floor is scoped to the acting user's org, the copy
        has to say so."""
        start = ORG_UI.index('charter-block-pii')
        card = ORG_UI[start:start + 2200]
        self.assertNotIn("Block sensitive data before it reaches a model", card,
                         "the old label over-promised deployment-wide coverage")
        self.assertIn("this organization", card)
        self.assertIn("not covered", card,
                      "the built-in exemption must be stated, not implied")

    def test_the_panel_renders_the_precision_note(self):
        """An admin should see that the routing-number check is the loosest one
        before enabling it, not after."""
        self.assertIn("c.note", ORG_UI)


class TheStoredKeyIsTheOneSynderesisReads(unittest.TestCase):
    """A rename on either side would silently disable the whole feature: the
    org list would save fine and never reach an agent."""

    def test_the_key_matches_end_to_end(self):
        syn = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
               / "faculties" / "synderesis.py").read_text(encoding="utf-8")
        will = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                / "faculties" / "will.py").read_text(encoding="utf-8")
        for name, src in (("synderesis", syn), ("will", will), ("routes", ROUTES)):
            with self.subTest(where=name):
                self.assertIn("pii_validators", src)
        self.assertIn('struct.get("pii_validators")', will)
        self.assertIn('struct_in.get("pii_validators")', syn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
