"""
The composer's + panel: one popover, sections inside it.

WHY. The menu was four entries that each CLOSED the menu and opened a sibling
dropdown anchored to the same corner. Drilling in destroyed the thing you were
navigating — no title, no back, no indication of where you were. That is what
made it feel primitive; the styling was a symptom.

Now the three lists are sections of one panel that stays put. Considered and
rejected: a tab strip. One of the four entries (Attach File) is a one-shot
action with nothing to display, so it would have been a tab with no panel, and
tabs want horizontal room a composer popover does not have on mobile. Tabs
start earning their keep when a single section is too big to show at once.

The section containers deliberately KEEP their original ids, so ui-auth-sidebar,
ui-model-selector and ui-data-sources render into exactly what they always did.
That is why this refactor did not touch their row markup.

Run:  venv/bin/python tests/test_composer_menu.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UI = ROOT / "public" / "js" / "ui"
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
MODEL = (UI / "ui-model-selector.js").read_text(encoding="utf-8")
SIDEBAR = (UI / "ui-auth-sidebar.js").read_text(encoding="utf-8")
DATA = (UI / "ui-data-sources.js").read_text(encoding="utf-8")
MENU = (UI / "ui-composer-menu.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "js" / "core" / "app.js").read_text(encoding="utf-8")

PANEL = INDEX[INDEX.index('id="composer-plus-menu"'):]
PANEL = PANEL[:PANEL.index("<!-- Text Area -->")]

AGENT_RENDER = SIDEBAR[SIDEBAR.index("function renderAgentSelectorOptions"):]


class OneSurface(unittest.TestCase):

    def test_the_three_lists_live_inside_the_panel(self):
        for el in ("agent-selector-dropdown", "model-selector-dropdown",
                   "data-sources-dropdown"):
            with self.subTest(section=el):
                self.assertIn(f'id="{el}"', PANEL,
                              f"{el} is outside the + panel again")

    def test_the_sections_are_not_popovers_any_more(self):
        """They were absolutely positioned and self-hiding. In flow now, or
        the panel is a popover containing three popovers."""
        for el in ("agent-selector-dropdown", "model-selector-dropdown",
                   "data-sources-dropdown"):
            m = re.search(rf'id="{el}"[^>]*?class="([^"]+)"', PANEL, re.S)
            with self.subTest(section=el):
                self.assertNotIn("absolute", m.group(1))
                self.assertNotIn("hidden", m.group(1))

    def test_the_panel_scrolls_rather_than_growing(self):
        m = re.search(r'id="composer-plus-menu"[^>]*?class="([^"]+)"', INDEX, re.S)
        self.assertIn("overflow-y-auto", m.group(1))
        self.assertRegex(m.group(1), r"max-h-\[\d+vh\]")

    def test_the_drill_down_machinery_is_gone(self):
        """The whole point: nothing opens a sibling dropdown any more."""
        for gone in ("toggleDropdown", "_closeAllDropdowns", "_openDropdown"):
            self.assertNotIn(gone, MENU, f"{gone} survived")
        for gone in ("toggleAgentDropdown", "toggleModelDropdown", "toggleDataDropdown"):
            self.assertNotIn(gone, SIDEBAR + MODEL + DATA + APP + INDEX,
                             f"{gone} survived")


class SectionsAreLabelledOnce(unittest.TestCase):

    def test_the_panel_prints_the_section_names(self):
        for label in (">Agents</div>", ">AI Models</div>", ">Data Sources</div>"):
            self.assertIn(label, PANEL)

    def test_the_lists_do_not_print_their_own(self):
        """Two labels for one list read as two lists."""
        self.assertNotIn("Select agent", SIDEBAR)
        self.assertNotIn("Select model", MODEL)

    def test_attach_is_still_a_button_not_a_section(self):
        """It opens the OS file picker; there is no list to show."""
        self.assertIn('id="plus-attach-btn"', PANEL)
        self.assertIn("Attach File", PANEL)


class ChoosingSomethingDismissesThePanel(unittest.TestCase):

    def test_both_lists_close_the_panel(self):
        """They used to hide their own container, which is no longer a
        container that hides."""
        self.assertIn("closeComposerMenu", SIDEBAR)
        self.assertIn("closeComposerMenu", MODEL)

    def test_the_close_helper_is_exported_once(self):
        self.assertIn("export function closeComposerMenu", MENU)

    def test_no_list_hides_itself(self):
        for src, name in ((AGENT_RENDER, "agent"), (MODEL, "model")):
            with self.subTest(list=name):
                self.assertNotIn("classList.add('hidden')", src)


class KeyboardAndAria(unittest.TestCase):

    def test_escape_closes_the_panel(self):
        self.assertIn("'Escape'", MENU)

    def test_aria_expanded_tracks_the_panel(self):
        self.assertIn('aria-expanded="false"', INDEX)
        for fn in ("function _toggleMenu", "export function closeComposerMenu"):
            block = MENU[MENU.index(fn):]
            self.assertIn("_syncExpanded()", block[:block.index("\n}")])

    def test_the_panel_and_its_sections_are_labelled(self):
        self.assertIn('role="menu"', PANEL)
        self.assertEqual(PANEL.count('role="group"'), 3)


class ThingsThatMustNotRegress(unittest.TestCase):

    def test_agent_names_and_avatars_are_escaped(self):
        self.assertIn("escapeHtml(profile.name", AGENT_RENDER)
        self.assertIn("escapeHtml(avatarUrl", AGENT_RENDER)

    def test_the_demo_copy_stays_gone(self):
        self.assertNotIn("SAFi governs whichever model you pick", MODEL)

    def test_the_label_writers_survive_as_no_ops(self):
        """app.js calls both on every profile/model change; deleting them
        would ReferenceError at runtime, which `node --check` does not catch."""
        self.assertIn("export function updateAgentLabel", MENU)
        self.assertIn("export function updateModelLabel", MENU)


if __name__ == "__main__":
    unittest.main(verbosity=2)
