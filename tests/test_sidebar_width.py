"""
The desktop sidebar's width, and the margin that has to match it.

WHY THIS IS A TEST AND NOT JUST A NUMBER. `#sidebar` is `fixed`, so it occupies
no space in flow: the only thing keeping the chat out from under it is the
`md:ml-*` class that `updateUIForAuthState()` puts on `#main-layout-wrapper`.
Those two values live in different places — one in a template literal, one in a
classList call two hundred lines away, plus a third copy in an index.html
comment — and nothing but attention keeps them equal.

Get it wrong in one direction and there is a dead gutter beside the sidebar; get
it wrong in the other and the first ~30px of every message sits underneath it.
Neither fails a build, and neither is obvious in a screenshot unless you already
suspect it.

The collapsed rail is deliberately NOT part of this: it is 3.5rem/`w-14` by its
own reasoning (content clears the rail rather than sliding under it) and does not
track the sidebar's width. See test_collapsed_rail_layout.py.

Run:  venv/bin/python tests/test_sidebar_width.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIDEBAR = (ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

# Tailwind's default spacing scale, for the classes this layout uses.
REMS = {"14": 3.5, "64": 16.0, "72": 18.0, "80": 20.0, "96": 24.0}


def _sidebar_width_class():
    m = re.search(r'<aside id="sidebar" class="([^"]+)"', SIDEBAR)
    assert m, "could not find the #sidebar aside"
    return re.search(r"\bw-(\d+)\b", m.group(1)).group(1)


def _wrapper_margin_classes():
    """Every md:ml-* the sidebar module adds to or removes from the wrapper."""
    return set(re.findall(r"classList\.(?:add|remove)\('md:ml-(\d+)'\)", SIDEBAR))


class TheWidthAndTheMarginMatch(unittest.TestCase):

    def test_the_margin_equals_the_sidebar_width(self):
        width = _sidebar_width_class()
        margins = _wrapper_margin_classes()
        self.assertTrue(margins, "no md:ml-* found — the wrapper offset went missing")
        self.assertEqual(margins, {width},
                         f"#sidebar is w-{width} but the wrapper uses md:ml-{sorted(margins)}; "
                         "a fixed sidebar means this gap is either dead space or an overlap")

    def test_add_and_remove_use_the_same_class(self):
        """Adding md:ml-72 and removing md:ml-64 leaves the margin stuck on the
        login view, which is what the logged-out branch exists to undo."""
        added = set(re.findall(r"classList\.add\('md:ml-(\d+)'\)", SIDEBAR))
        removed = set(re.findall(r"classList\.remove\('md:ml-(\d+)'\)", SIDEBAR))
        self.assertEqual(added, removed)

    def test_the_index_comment_names_the_class_actually_used(self):
        """The comment above #main-layout-wrapper documents this coupling, so a
        stale number there is worse than none — it is the first thing read."""
        width = _sidebar_width_class()
        comment = INDEX[INDEX.index("<!-- md:ml-"):]
        comment = comment[:comment.index("-->")]
        self.assertIn(f"md:ml-{width}", comment)
        for other in REMS:
            if other != width:
                self.assertNotIn(f"md:ml-{other}", comment)


class TheTwoDesktopSidebarsAgree(unittest.TestCase):
    """The chat sidebar and the Control Panel's nav are the same visual element
    in two views — same background, same border treatment. Widening one alone
    makes the panel jump sideways when you switch to it."""

    def test_the_control_panel_nav_is_the_same_width(self):
        m = re.search(r'<aside\s+[^>]*class="(hidden md:flex flex-col w-\d+[^"]*)"', INDEX)
        self.assertIsNotNone(m, "could not find the Control Panel aside")
        panel_width = re.search(r"\bw-(\d+)\b", m.group(1)).group(1)
        self.assertEqual(panel_width, _sidebar_width_class())


class ItStaysDesktopOnly(unittest.TestCase):

    def test_the_desktop_sidebar_is_hidden_below_md(self):
        """Widening it must not touch the phone layout, where the sidebar is a
        separate overlay drawer."""
        m = re.search(r'<aside id="sidebar" class="([^"]+)"', SIDEBAR)
        self.assertIn("hidden", m.group(1))
        self.assertIn("md:flex", m.group(1))

    def test_the_mobile_drawer_keeps_its_own_width(self):
        """index.html carries a md:hidden drawer at w-64. It is a different
        element on a viewport the sidebar never occupies, so it does not follow
        the desktop width — 18rem of a 375px phone is half the screen."""
        m = re.search(r'class="fixed inset-y-0 left-0 w-(\d+)[^"]*md:hidden', INDEX)
        self.assertIsNotNone(m, "the mobile drawer went missing")
        self.assertEqual(m.group(1), "64")

    def test_the_collapsed_rail_does_not_track_the_sidebar(self):
        rail = re.search(r'id="sidebar-rail"[\s\S]{0,400}?class="([^"]+)"', SIDEBAR)
        self.assertIsNotNone(rail)
        self.assertIn("w-14", rail.group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
