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

import re  # noqa: E402  (kept beside the CSS it parses)

# Comments stripped: the prose around these rules quotes the selectors it
# discusses, so a bare `find()` can land inside a paragraph instead of on a rule.
CSS = re.sub(r"/\*.*?\*/", "",
             (ROOT / "public" / "css" / "styles.css").read_text(encoding="utf-8"),
             flags=re.S)
# The rail markup is injected by the sidebar module, not authored in index.html.
SIDEBAR_JS = (ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js").read_text(
    encoding="utf-8")

# Was `html.sidebar-collapsed:has(...)`. The collapsed qualifier was dropped
# 2026-08-11: with the sidebar EXPANDED it matched nothing, so opening the panel
# left it indented by a full sidebar with the chat sidebar still painted beside
# it. "The panel is on screen" was never a fact about the collapsed state.
# See test_sidebar_width.py, which pins that the qualifier stays gone.
PANEL_OPEN = 'html:has(#control-panel-view:not(.hidden))'
# The rail and the gutter, plus the sidebar itself, which the CSS took over from
# four hand-copied JS handlers in the same change.
PANEL_TARGETS = ('#sidebar', '#sidebar-rail', '#main-layout-wrapper')


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

    def test_all_of_them_use_the_same_condition(self):
        """One decision, one selector. Two different conditions would drift —
        which is exactly what happened when the sidebar's own hiding lived in
        four JS handlers and the rail's lived here."""
        self.assertEqual(CSS.count(PANEL_OPEN), len(PANEL_TARGETS))
        for target in PANEL_TARGETS:
            with self.subTest(target=target):
                self.assertIsNotNone(_block(f"{PANEL_OPEN} {target}"))

    def test_the_sidebar_itself_goes_too(self):
        """It used to be hidden by every opener in JS. If only the rail and the
        gutter were handled here, an expanded sidebar would stay painted over
        the panel."""
        self.assertIn("display: none", _block(f"{PANEL_OPEN} #sidebar"))

    def test_the_indent_matches_the_rail_width(self):
        """If the rail is ever resized, this pins that the gutter tracks it —
        the two numbers are the same measurement."""
        gutter = _block("html.sidebar-collapsed #main-layout-wrapper")
        self.assertRegex(gutter, r"margin-left:\s*3\.5rem")
        i = SIDEBAR_JS.index('id="sidebar-rail"')
        self.assertIn("w-14", SIDEBAR_JS[i:i + 400],
                      "rail is not 3.5rem (w-14) wide; the gutter no longer matches")


class ItStaysOverrideSafe(unittest.TestCase):

    def test_the_override_beats_the_base_rule_on_specificity(self):
        """It used to need !important, because the base gutter had it to beat a
        Tailwind margin utility. That utility is gone (the offset is a CSS var
        now), so both rules are clean and :has() wins on its own: it carries its
        argument's specificity, putting the override at (2,1,1) against (1,1,1).

        Asserted as a pair — if !important ever comes back to the base rule, the
        override needs it too or it silently loses."""
        base = _block("html.sidebar-collapsed #main-layout-wrapper")
        override = _block(f"{PANEL_OPEN} #main-layout-wrapper")
        self.assertEqual("!important" in base, "!important" in override,
                         "the base gutter and the panel override must agree on !important")

    def test_the_rules_live_in_the_desktop_media_query(self):
        """On mobile the sidebar is an overlay and the rail never displays;
        applying any of these there would move the panel for no reason.

        Checked by finding the nearest @media ABOVE each rule rather than by
        bracketing a region between two text markers — the old end marker was a
        CSS comment, and comments are stripped here now."""
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
