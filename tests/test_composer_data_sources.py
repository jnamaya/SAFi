import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "public" / "js" / "ui" / "ui-data-sources.js").read_text(encoding="utf-8")
GOV = (ROOT / "safi_app" / "core" / "services" / "connector_governance.py").read_text(
    encoding="utf-8")


class TheMenuIsDrivenByThePolicy(unittest.TestCase):

    def test_no_hardcoded_catalogue_remains(self):
        self.assertNotIn("authUrl", JS,
                         "connector definitions must come from /auth/status, not the client")
        body = JS[JS.index("function renderMenu"):]
        self.assertNotIn("'Google Drive'", body)
        self.assertNotIn("'GitHub'", body)

    def test_it_filters_on_both_flags(self):
        self.assertIn("c.allowed !== false && c.usable !== false", JS)

    def test_a_connected_but_now_blocked_source_still_shows(self):
        self.assertIn("|| connectedList.includes(c.key)", JS)
        self.assertIn("no longer permitted", JS)

    def test_a_blocked_source_is_not_clickable(self):
        self.assertIn("item.href = connectable ? `/api/auth/${source.key}/login` : '#'", JS)

    def test_an_unusable_source_is_hidden_not_offered(self):
        self.assertIn("source.usable === false", JS)
        self.assertIn("no agent here uses it", JS)

    def test_only_a_fully_clear_source_carries_a_login_link(self):
        self.assertIn("const connectable = !isConnected && !blocked && !unused;", JS)
        self.assertIn("item.href = connectable ?", JS)
        self.assertIn("if (!connectable) {", JS)

    def test_the_empty_state_considers_both_kinds(self):
        self.assertIn("!visible.length && !visibleMcp.length", JS)
        self.assertLess(JS.index("const visibleMcp"), JS.index("nothing to set up here"))

    def test_a_failed_status_call_offers_nothing(self):
        i = JS.index("catch (e)")
        self.assertIn("renderMenu([], [])", JS[i:i + 400])


class ItAgreesWithTheServer(unittest.TestCase):

    def test_the_delegated_catalog_is_empty(self):
        keys = set(re.findall(r'^\s{4}"(\w+)":\s*\{', GOV, re.M))
        self.assertEqual(set(), keys,
                         f"unexpected connector keys in metadata: {keys}")

    def test_the_guard_survives_for_any_future_catalog(self):
        self.assertIn("assert_connector_allowed", GOV)
        self.assertIn("raise ConnectorNotAllowedError", GOV)


if __name__ == "__main__":
    unittest.main(verbosity=2)
