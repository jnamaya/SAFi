"""
The desktop sidebar's width, and the Control Panel collapsing to the edge.

WHY THIS FILE EXISTS, IN TWO PARTS.

**One number, one place.** `#sidebar` is `fixed`, so it takes no space in flow and
the chat needs a matching left offset. Spelled as Tailwind classes that was `w-64`
plus a `md:ml-64` toggled from JS — and the toggle got copy-pasted into every
handler that opens the Control Panel, four of them carrying the comment "Match
app.js Control Panel logic". Seven copies of one number across four files.
Widening the sidebar to 18rem updated two of the seven.

**The bug that found it.** The rules that strip the offset when the Control Panel
opens were qualified on `html.sidebar-collapsed`. With the sidebar *expanded* none
of them applied, so the panel kept a full sidebar's indent and the chat sidebar
stayed painted beside the panel's own nav. "The panel is on screen" has nothing to
do with whether the sidebar was collapsed, and the qualifier was the whole defect.

Both are now CSS's job: `--sidebar-w` for the number, and one
`:has(#control-panel-view:not(.hidden))` group for the panel. JS says only whether
a sidebar exists at all. These tests pin that arrangement, and — unlike the version
of this file that missed the regression — they scan **every** front-end file for a
resurrected margin utility, not just the sidebar module.

Run:  venv/bin/python tests/test_sidebar_width.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "public"
CSS_RAW = (PUBLIC / "css" / "styles.css").read_text(encoding="utf-8")
# Selector matching runs on a comment-free copy. The prose explaining this
# arrangement necessarily quotes the selectors it is warning about — including
# the `html.sidebar-collapsed` qualifier that WAS the bug — and a regex looking
# for a stray qualifier happily finds it inside the paragraph saying it is gone.
CSS = re.sub(r"/\*.*?\*/", "", CSS_RAW, flags=re.S)
INDEX = (PUBLIC / "index.html").read_text(encoding="utf-8")
SIDEBAR = (PUBLIC / "js" / "ui" / "ui-auth-sidebar.js").read_text(encoding="utf-8")

JS_FILES = sorted((PUBLIC / "js").rglob("*.js"))


def enclosing_media_query(haystack: str, needle: str) -> str:
    """The nearest @media above `needle`, so a rule's breakpoint can be asserted
    without depending on exact whitespace."""
    at = haystack.index(needle)
    opens = [m for m in re.finditer(r"@media\s*\(([^)]*)\)", haystack[:at])]
    return opens[-1].group(1).replace(" ", "") if opens else ""


class TheWidthLivesInOnePlace(unittest.TestCase):

    def test_the_custom_property_is_defined_once(self):
        self.assertEqual(len(re.findall(r"--sidebar-w\s*:", CSS)), 1,
                         "--sidebar-w should be declared exactly once, on :root")
        self.assertRegex(CSS, r":root\s*\{[^}]*--sidebar-w\s*:\s*[\d.]+rem")

    def test_the_sidebar_takes_its_width_from_the_property(self):
        self.assertRegex(CSS, r"#sidebar\s*\{\s*width:\s*var\(--sidebar-w\)")

    def test_the_wrapper_offset_takes_the_same_property(self):
        self.assertRegex(
            CSS, r"html\.has-sidebar\s+#main-layout-wrapper\s*\{\s*margin-left:\s*var\(--sidebar-w\)")

    def test_the_control_panel_nav_takes_the_same_property(self):
        """Same visual element in another view; widening one alone made the panel
        jump sideways on the way in."""
        self.assertRegex(
            CSS, r"#control-panel-view\s*>\s*aside\s*\{\s*width:\s*var\(--sidebar-w\)")

    def test_no_width_class_survives_on_either_aside(self):
        """A `w-*` class alongside the CSS rule is dead code that reads as the
        source of truth."""
        m = re.search(r'<aside id="sidebar" class="([^"]+)"', SIDEBAR)
        self.assertIsNotNone(m)
        self.assertNotRegex(m.group(1), r"\bw-\d+\b")

        m = re.search(r'<aside\s+[^>]*class="(hidden md:flex flex-col[^"]*)"', INDEX)
        self.assertIsNotNone(m, "could not find the Control Panel aside")
        self.assertNotRegex(m.group(1), r"\bw-\d+\b")


class NoHandlerOwnsTheLayout(unittest.TestCase):
    """The regression this file previously missed: it only read the sidebar
    module, so four stale copies in two other files sailed through."""

    def test_no_js_file_toggles_a_margin_utility(self):
        offenders = []
        for f in JS_FILES:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"classList\.(add|remove)\(\s*['\"]md:ml-", line):
                    offenders.append(f"{f.relative_to(ROOT)}:{n}")
        self.assertEqual(offenders, [],
                         "the chat's left offset belongs to CSS; these reintroduce it: "
                         + ", ".join(offenders))

    def test_no_js_file_toggles_the_sidebars_desktop_display(self):
        """`classList.remove('md:flex')` on #sidebar was copy-pasted into every
        opener, and the closer had to remember to put it back. One CSS rule
        replaces all of it, and a leftover toggle can strand the sidebar."""
        offenders = []
        for f in JS_FILES:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"classList\.(add|remove)\(\s*['\"]md:flex", line):
                    offenders.append(f"{f.relative_to(ROOT)}:{n}")
        self.assertEqual(offenders, [])

    def test_the_index_comment_does_not_name_a_margin_utility(self):
        comment = INDEX[INDEX.index("<!-- This wrapper's left offset"):]
        comment = comment[:comment.index("-->")]
        self.assertIn("has-sidebar", comment)
        self.assertNotRegex(comment, r"md:ml-\d+ is added")


class TheControlPanelReachesTheEdge(unittest.TestCase):
    """The reported bug. Each rule must fire whenever the panel is visible —
    NOT only when the sidebar happened to be collapsed."""

    RULES = ("#sidebar", "#sidebar-rail", "#main-layout-wrapper")

    def _selector_for(self, target):
        pattern = (r"(html[^{]*?:has\(#control-panel-view:not\(\.hidden\)\)[^{]*?"
                   + re.escape(target) + r")\s*\{")
        return [m.group(1) for m in re.finditer(pattern, CSS)]

    def test_each_target_has_a_panel_rule(self):
        for target in self.RULES:
            with self.subTest(target=target):
                self.assertTrue(self._selector_for(target),
                                f"no :has() panel rule for {target}")

    def test_no_panel_rule_is_gated_on_the_collapsed_state(self):
        """This exact qualifier was the bug: expanded + panel open matched
        nothing, so the panel sat a full sidebar's width from the edge with the
        chat sidebar still painted there."""
        for target in self.RULES:
            for selector in self._selector_for(target):
                with self.subTest(selector=selector):
                    self.assertNotIn("sidebar-collapsed", selector)

    def test_the_wrapper_margin_goes_to_zero(self):
        m = re.search(
            r"html:has\(#control-panel-view:not\(\.hidden\)\)\s+#main-layout-wrapper\s*\{([^}]*)\}",
            CSS)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"margin-left:\s*0")


class CascadeOrderAndScope(unittest.TestCase):

    def test_the_collapsed_rule_comes_after_the_expanded_one(self):
        """Equal specificity (1,1,1), so source order is the tiebreak. Reversed,
        collapsing the sidebar would leave the full-width offset."""
        expanded = CSS.index("html.has-sidebar #main-layout-wrapper")
        collapsed = CSS.index("html.sidebar-collapsed #main-layout-wrapper")
        self.assertLess(expanded, collapsed)

    def test_the_panel_rules_need_no_important(self):
        """:has() carries its argument's specificity, so these land at (2,1,1)
        against (1,1,1) above. An !important here would be hiding a real
        specificity bug."""
        block = CSS[CSS.index("html:has(#control-panel-view:not(.hidden)) #sidebar"):]
        block = block[:block.index("html:has(#control-panel-view:not(.hidden)) #main-layout-wrapper")
                      + 200]
        self.assertNotIn("!important", block)

    def test_the_layout_rules_are_desktop_only(self):
        """Below md the sidebar is a separate overlay drawer and none of this
        applies."""
        for rule in ("#sidebar {",
                     "html.has-sidebar #main-layout-wrapper",
                     "html:has(#control-panel-view:not(.hidden)) #main-layout-wrapper"):
            with self.subTest(rule=rule):
                self.assertEqual(enclosing_media_query(CSS, rule), "min-width:768px")

    def test_the_custom_property_is_not_trapped_in_the_media_query(self):
        """--sidebar-w on :root, outside the breakpoint: a custom property
        declared inside @media only exists above it, and every consumer here
        would silently fall back to nothing below md."""
        at = CSS.index("--sidebar-w:")
        self.assertNotIn("@media", CSS[:at].rsplit("}", 1)[-1])

    def test_the_mobile_drawer_keeps_its_own_width(self):
        """A different md:hidden element. It carries its own viewport-relative
        width (widened from w-64 on 2026-08-18 — w-64 read as thin), and must
        NOT follow --sidebar-w (18rem of a 375px phone is half the screen)."""
        m = re.search(r'id="mobile-menu"\s+class="([^"]+)"', INDEX)
        self.assertIsNotNone(m, "the mobile drawer went missing")
        cls = m.group(1)
        self.assertIn("md:hidden", cls)
        self.assertRegex(cls, r"w-\[\d+vw\]", "expected a viewport-relative width")
        self.assertNotIn("--sidebar-w", cls)

    def test_the_collapsed_rail_does_not_track_the_sidebar(self):
        """3.5rem by its own reasoning — content clears the rail rather than
        sliding under it. See test_collapsed_rail_layout.py."""
        m = re.search(r"html\.sidebar-collapsed\s+#main-layout-wrapper\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(m)
        self.assertIn("3.5rem", m.group(1))
        self.assertNotIn("--sidebar-w", m.group(1))


class TheStateClassIsSymmetric(unittest.TestCase):

    def test_has_sidebar_is_added_and_removed(self):
        self.assertIn("classList.add('has-sidebar')", SIDEBAR)
        self.assertIn("classList.remove('has-sidebar')", SIDEBAR)

    def test_it_is_set_on_the_root_element(self):
        """On <html>, so the :has() and .sidebar-collapsed rules compose with it
        — and so the pre-paint script in index.html can set the collapsed state
        before first paint without waiting for JS modules."""
        for verb in ("add", "remove"):
            self.assertRegex(SIDEBAR,
                             r"document\.documentElement\.classList\." + verb
                             + r"\('has-sidebar'\)")

    def test_only_the_sidebar_module_owns_it(self):
        offenders = [str(f.relative_to(ROOT)) for f in JS_FILES
                     if "has-sidebar" in f.read_text(encoding="utf-8")
                     and f.name != "ui-auth-sidebar.js"]
        self.assertEqual(offenders, [],
                         "has-sidebar is one module's business: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
