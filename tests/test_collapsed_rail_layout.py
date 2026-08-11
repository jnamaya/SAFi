"""
The collapsed sidebar's gutter disappears with the rail.

WHY. Collapsing the sidebar leaves a 3.5rem icon rail, and #main-layout-wrapper
is indented by exactly that much so the chat clears it rather than sliding
underneath. Opening the Control Panel hides the rail — the panel replaces the
whole chat chrome — but the indent stayed, so the panel sat 56px right of where
it sits when the sidebar is expanded. The panel is a child of that wrapper, so
it inherited an offset that was only ever meant for the chat view.

The rule these two share is the point of this file: "the rail is not on screen"
is ONE decision with two consequences, and it is expressed with one :has()
condition rather than an inline style set by a handler. The panel is opened in
three places and closed in four across three files; a handler-based toggle only
needs one of those paths forgotten to strand either the rail or the gutter.

Source-level, like the other CSS guards. Run:
    venv/bin/python tests/test_collapsed_rail_layout.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CSS = (ROOT / "public" / "css" / "styles.css").read_text(encoding="utf-8")
# The rail markup is injected by the sidebar module, not authored in index.html.
SIDEBAR_JS = (ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js").read_text(
    encoding="utf-8")

PANEL_OPEN = 'html.sidebar-collapsed:has(#control-panel-view:not(.hidden))'


def _block(selector):
    """The declarations for a selector, or None."""
    i = CSS.find(selector)
    if i == -1:
        return None
    return CSS[CSS.index("{", i) + 1:CSS.index("}", i)]


class TheGutterFollowsTheRail(unittest.TestCase):

    def test_the_rail_is_hidden_when_the_panel_opens(self):
        self.assertIsNotNone(_block(f"{PANEL_OPEN} #sidebar-rail"))
        self.assertIn("display: none", _block(f"{PANEL_OPEN} #sidebar-rail"))

    def test_the_wrapper_indent_is_removed_too(self):
        """Regression 2026-08-11: the rail was hidden but its 3.5rem gutter
        remained, offsetting the panel by 56px."""
        block = _block(f"{PANEL_OPEN} #main-layout-wrapper")
        self.assertIsNotNone(block, "no rule drops the gutter when the panel opens")
        self.assertRegex(block, r"margin-left:\s*0")

    def test_both_use_the_same_condition(self):
        """One decision, one selector. Two different conditions would drift."""
        self.assertEqual(CSS.count(PANEL_OPEN), 2)

    def test_the_indent_matches_the_rail_width(self):
        """If the rail is ever resized, this pins that the gutter tracks it —
        the two numbers are the same measurement."""
        gutter = _block("html.sidebar-collapsed #main-layout-wrapper")
        self.assertRegex(gutter, r"margin-left:\s*3\.5rem")
        i = SIDEBAR_JS.index('id="sidebar-rail"')
        self.assertIn("w-14", SIDEBAR_JS[i:i + 400],
                      "rail is not 3.5rem (w-14) wide; the gutter no longer matches")


class ItStaysOverrideSafe(unittest.TestCase):

    def test_the_override_beats_the_base_rule(self):
        """The base gutter uses !important (it overrides a Tailwind utility),
        so the panel override needs it too or it silently loses."""
        base = _block("html.sidebar-collapsed #main-layout-wrapper")
        override = _block(f"{PANEL_OPEN} #main-layout-wrapper")
        if "!important" in base:
            self.assertIn("!important", override)

    def test_both_rules_live_in_the_desktop_media_query(self):
        """On mobile the sidebar is an overlay and the rail never displays;
        applying either rule there would move the panel for no reason."""
        mq = CSS.index("@media (min-width: 768px)")
        end = CSS.index("/* --- Scroll-to-bottom button --- */")
        for sel in (f"{PANEL_OPEN} #sidebar-rail", f"{PANEL_OPEN} #main-layout-wrapper"):
            self.assertTrue(mq < CSS.index(sel) < end, f"{sel} escaped the media query")


if __name__ == "__main__":
    unittest.main(verbosity=2)
