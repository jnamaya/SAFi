import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core import pii_validators as engine
from safi_app.security_policy import PII_CATALOGUE


class ConfiguredValidators:
    @staticmethod
    def catalogue():
        return engine.catalogue(PII_CATALOGUE)

    @staticmethod
    def normalize(keys):
        return engine.normalize(keys, PII_CATALOGUE)


pv = ConfiguredValidators()

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
        self.assertIn("pii_validators.catalogue(security_policy.PII_CATALOGUE)", ROUTES[i:i + 1000])

    def test_every_catalogue_entry_can_be_rendered(self):
        for e in pv.catalogue():
            with self.subTest(key=e["key"]):
                self.assertTrue(e["key"] and e["label"] and e["note"])


class OnlyKnownKeysSurviveTheSaveRoute(unittest.TestCase):

    def test_the_route_rejects_unknown_keys(self):
        i = ROUTES.index("pii = structural.get('pii_validators')")
        body = ROUTES[i:i + 1400]
        self.assertIn("security_policy.PII_CATALOGUE", body,
                      "the route must check against the host-owned catalogue")
        self.assertIn("400", body, "an unknown key must be rejected, not dropped")

    def test_the_route_rejects_a_non_list(self):
        i = ROUTES.index("pii = structural.get('pii_validators')")
        self.assertIn("must be an array", ROUTES[i:i + 400])

    def test_a_regex_is_not_a_valid_key(self):
        for attempt in (r"\d{3}-\d{2}-\d{4}", ".*", "(a+)+$", "ssn|custom"):
            with self.subTest(attempt=attempt):
                self.assertEqual(pv.normalize([attempt]), [],
                                 "a pattern must never normalize to a validator")

    def test_normalize_keeps_the_valid_ones_from_a_mixed_payload(self):
        self.assertEqual(pv.normalize(["ssn", r"\d+", "iban"]), ["ssn", "iban"])

    def test_an_empty_list_is_a_legitimate_value(self):
        self.assertEqual(pv.normalize([]), [])


class TheUiSendsOnlyCheckboxes(unittest.TestCase):

    def test_there_is_no_free_text_input_for_patterns(self):
        start = ORG_UI.index('charter-pii-panel')
        panel = ORG_UI[start:start + 900]
        self.assertNotIn('type="text"', panel)
        self.assertNotIn("type='text'", panel)

    def test_the_save_collects_ticked_boxes_only(self):
        self.assertIn(".pii-check:checked", ORG_UI)

    def test_unticking_the_master_switch_sends_an_empty_list(self):
        i = ORG_UI.index("const piiOn")
        self.assertIn("[]", ORG_UI[i:i + 400])

    def test_the_copy_states_the_real_coverage(self):
        start = ORG_UI.index('charter-block-pii')
        card = ORG_UI[start:start + 2200]
        self.assertIn("including the ones SAFi ships with", card)
        self.assertIn("follow the person typing", card,
                      "the reason has to be stated or the scope is a surprise")
        self.assertNotIn("are not covered", card,
                         "the exemption warning is now false")

    def test_the_panel_renders_the_precision_note(self):
        self.assertIn("c.note", ORG_UI)


class TheStoredKeyIsTheOneSynderesisReads(unittest.TestCase):

    def test_the_key_matches_end_to_end(self):
        syn = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
               / "faculties" / "synderesis.py").read_text(encoding="utf-8")
        will = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                / "faculties" / "will.py").read_text(encoding="utf-8")
        for name, src in (("synderesis", syn), ("will", will), ("routes", ROUTES)):
            with self.subTest(where=name):
                self.assertIn("pii_validators", src)
        self.assertIn('struct.get("pii_validators")', will)
        self.assertIn('("banned_markdown_syntaxes", "pii_validators")', syn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
