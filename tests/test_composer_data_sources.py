"""
The composer's data-source menu must reflect what the org actually permits.

WHY. `/auth/status` already returns every connector with two flags —
`allowed` (org policy permits linking it) and `usable` (some agent this member
can reach is authorized to call its tools). The composer menu ignored both: it
rendered a hardcoded catalogue of Google Drive, OneDrive/SharePoint and GitHub
and used the response only to mark which were connected.

So an organization whose allow-list contains GitHub alone still advertised
OneDrive/SharePoint in the chat composer, and clicking it failed — the login
route enforces the allow-list even when the menu does not. Not a security hole,
which is why it survived: `_connector_guard` runs on both the login route and
the callback. It is a trust bug. A governance product that offers a member a
data source their organization has forbidden is wrong in the place users look.

Run:  venv/bin/python tests/test_composer_data_sources.py
"""
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
        """The old list was three object literals with authUrl fields. Any
        catalogue defined in the client drifts from the server's."""
        self.assertNotIn("authUrl", JS,
                         "connector definitions must come from /auth/status, not the client")
        body = JS[JS.index("function renderMenu"):]
        self.assertNotIn("'Google Drive'", body)
        self.assertNotIn("'GitHub'", body)

    def test_it_filters_on_the_allowed_flag(self):
        self.assertIn("c.allowed !== false", JS)

    def test_a_connected_but_now_blocked_source_still_shows(self):
        """An admin can revoke after the fact. The member still needs to see a
        live token to disconnect it — hiding a granted token is worse than
        showing a blocked one, and the server says so in auth_status."""
        self.assertIn("|| connectedList.includes(c.key)", JS)
        self.assertIn("no longer permitted", JS)

    def test_a_blocked_source_is_not_clickable(self):
        """Offering a link the login route will refuse is worse than not
        offering it: the member gets an error instead of an explanation."""
        self.assertIn("(isConnected || blocked) ? '#'", JS)

    def test_an_unusable_source_says_so_rather_than_inviting_a_grant(self):
        """Org-allowed is not enough. If no agent the member can reach is
        authorized to call its tools, linking it hands SAFi a live OAuth grant
        nothing will ever read."""
        self.assertIn("source.usable === false", JS)
        self.assertIn("No agent here uses it", JS)

    def test_a_failed_status_call_offers_nothing(self):
        """It used to render the full catalogue regardless of the response."""
        i = JS.index("catch (e)")
        self.assertIn("renderMenu([], [])", JS[i:i + 400])


class ItAgreesWithTheServer(unittest.TestCase):

    def test_icon_keys_match_the_connector_keys(self):
        """Icons are looked up as ICONS[source.key], so they must be keyed the
        same way CONNECTOR_METADATA is — not by product name."""
        keys = set(re.findall(r'^\s{4}"(\w+)":\s*\{', GOV, re.M))
        self.assertTrue({"google", "microsoft", "github"} <= keys,
                        f"unexpected connector keys in metadata: {keys}")
        icons = JS[JS.index("const ICONS"):JS.index("export function initDataSources")]
        for key in ("google", "microsoft", "github"):
            self.assertRegex(icons, rf"\b{key}:\s*`", f"no icon keyed '{key}'")

    def test_the_login_route_remains_the_actual_control(self):
        """The menu is presentation. If this guard ever goes, filtering in the
        client becomes the only thing standing between a member and a
        forbidden connector."""
        self.assertIn("assert_connector_allowed", GOV)


if __name__ == "__main__":
    unittest.main(verbosity=2)
