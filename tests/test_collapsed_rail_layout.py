import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import re

CSS = re.sub(r"/\*.*?\*/", "",
             (ROOT / "public" / "css" / "styles.css").read_text(encoding="utf-8"),
             flags=re.S)
SIDEBAR_JS = (ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js").read_text(
    encoding="utf-8")

PANEL_OPEN = 'html:has(#control-panel-view:not(.hidden))'
PANEL_TARGETS = ('#sidebar', '#sidebar-rail', '#main-layout-wrapper')


def _block(selector):
    i = CSS.find(selector)
    if i == -1:
        return None
    return CSS[CSS.index("{", i) + 1:CSS.index("}", i)]


class TheGutterFollowsTheRail(unittest.TestCase):

    def test_the_rail_is_hidden_when_the_panel_opens(self):
        self.assertIsNotNone(_block(f"{PANEL_OPEN} #sidebar-rail"))
        self.assertIn("display: none", _block(f"{PANEL_OPEN} #sidebar-rail"))

    def test_the_wrapper_indent_is_removed_too(self):
        block = _block(f"{PANEL_OPEN} #main-layout-wrapper")
        self.assertIsNotNone(block, "no rule drops the gutter when the panel opens")
        self.assertRegex(block, r"margin-left:\s*0")

    def test_all_of_them_use_the_same_condition(self):
        self.assertEqual(CSS.count(PANEL_OPEN), len(PANEL_TARGETS))
        for target in PANEL_TARGETS:
            with self.subTest(target=target):
                self.assertIsNotNone(_block(f"{PANEL_OPEN} {target}"))

    def test_the_sidebar_itself_goes_too(self):
        self.assertIn("display: none", _block(f"{PANEL_OPEN} #sidebar"))

    def test_the_indent_matches_the_rail_width(self):
        gutter = _block("html.sidebar-collapsed #main-layout-wrapper")
        self.assertRegex(gutter, r"margin-left:\s*3\.5rem")
        i = SIDEBAR_JS.index('id="sidebar-rail"')
        self.assertIn("w-14", SIDEBAR_JS[i:i + 400],
                      "rail is not 3.5rem (w-14) wide; the gutter no longer matches")


class ItStaysOverrideSafe(unittest.TestCase):

    def test_the_override_beats_the_base_rule_on_specificity(self):
        base = _block("html.sidebar-collapsed #main-layout-wrapper")
        override = _block(f"{PANEL_OPEN} #main-layout-wrapper")
        self.assertEqual("!important" in base, "!important" in override,
                         "the base gutter and the panel override must agree on !important")

    def test_the_rules_live_in_the_desktop_media_query(self):
        for target in PANEL_TARGETS:
            sel = f"{PANEL_OPEN} {target}"
            before = CSS[:CSS.index(sel)]
            queries = re.findall(r"@media\s*\(([^)]*)\)", before)
            with self.subTest(selector=sel):
                self.assertTrue(queries, f"{sel} sits outside any media query")
                self.assertEqual(queries[-1].replace(" ", ""), "min-width:768px",
                                 f"{sel} escaped the desktop media query")


if __name__ == "__main__":
    unittest.main(verbosity=2)
