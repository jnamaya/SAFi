"""
The composer's + menu: two submenus that look like each other.

WHY. "Agents" and "AI Models" sit one click apart in the same menu and used to
disagree on nearly every detail — the agent list had a filled header bar and
edge-to-edge rows, the model list had no header at all, no two dropdowns shared
a width, and the active check was green-600 in one and green-500 in the other.
Two lists doing the same job should not look like two features.

Also removed: a paragraph of showcase copy inside the model dropdown
("SAFi governs whichever model you pick…"). It was demo-only framing in a menu
whose job is to switch a model.

`test_composer_data_sources.py` covers the third dropdown's policy filtering;
this file is about the menu's shape and behaviour.

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
MENU = (UI / "ui-composer-menu.js").read_text(encoding="utf-8")

AGENT_RENDER = SIDEBAR[SIDEBAR.index("function renderAgentSelectorOptions"):]
# It is the last function in the file and the file ends without a trailing
# newline, so slice to end rather than hunting for a following declaration.


class TheLabelsSayWhatTheyOpen(unittest.TestCase):

    def test_menu_entries_are_nouns(self):
        """They open lists, so they are named for the lists."""
        self.assertIn(">Agents</div>", INDEX)
        self.assertIn(">AI Models</div>", INDEX)

    def test_the_old_verb_labels_are_gone(self):
        self.assertNotIn("Switch Agent", INDEX)
        self.assertNotIn("Change AI Model", INDEX)

    def test_both_submenus_label_their_list(self):
        """The agent list had a header and the model list did not."""
        self.assertIn("Select agent", SIDEBAR)
        self.assertIn("Select model", MODEL)


class TheTwoListsMatch(unittest.TestCase):

    def test_same_width(self):
        widths = re.findall(r'id="(agent-selector-dropdown|model-selector-dropdown|data-sources-dropdown)"[^>]*?class="([^"]+)"',
                            INDEX, re.S)
        self.assertEqual(len(widths), 3, "a dropdown is missing")
        for name, cls in widths:
            with self.subTest(dropdown=name):
                self.assertIn("w-64", cls)

    def test_same_row_padding(self):
        for src, name in ((MODEL, "model"), (AGENT_RENDER, "agent")):
            with self.subTest(list=name):
                self.assertIn("px-3 py-2 rounded-lg", src)

    def test_same_active_treatment(self):
        for src, name in ((MODEL, "model"), (AGENT_RENDER, "agent")):
            with self.subTest(list=name):
                self.assertIn("text-green-600 dark:text-green-500", src)
                self.assertIn("text-green-600", src)

    def test_the_agent_list_is_inset_like_the_others(self):
        """It had no padding, so its rows ran to the border while the model and
        data lists were inset by p-1."""
        m = re.search(r'id="agent-selector-dropdown"[^>]*?class="([^"]+)"', INDEX, re.S)
        self.assertIn("p-1", m.group(1))
        self.assertNotIn("overflow-hidden", m.group(1),
                         "overflow-hidden fought the max-h scroll")


class TheDemoCopyIsGone(unittest.TestCase):

    def test_the_paragraph_is_removed(self):
        self.assertNotIn("SAFi governs whichever model you pick", MODEL)
        self.assertNotIn("fast, low-cost models", MODEL)

    def test_the_demo_flag_survives_for_its_other_consumer(self):
        """isPublicDemoUi still stamps the model name onto demo messages
        (ui-messages.js); only the dropdown copy went."""
        self.assertIn("export function isPublicDemoUi", MODEL)
        messages = (UI / "ui-messages.js").read_text(encoding="utf-8")
        self.assertIn("isPublicDemoUi()", messages)


class NamesAreEscaped(unittest.TestCase):

    def test_agent_names_and_avatars_are_escaped(self):
        """Both are org-authored free text, and both land in markup — the name
        in an attribute as well as in text."""
        self.assertIn("escapeHtml(profile.name", AGENT_RENDER)
        self.assertIn("escapeHtml(avatarUrl", AGENT_RENDER)

    def test_the_helper_is_imported(self):
        self.assertIn("escapeHtml", SIDEBAR[:SIDEBAR.index("\n\n")] + SIDEBAR[:400])


class ItCanBeClosedFromTheKeyboard(unittest.TestCase):

    def test_escape_is_handled(self):
        self.assertIn("'Escape'", MENU)

    def test_escape_unwinds_one_level_at_a_time(self):
        """A submenu returns you to the + menu; a second press closes it."""
        block = MENU[MENU.index("e.key !== 'Escape'"):]
        block = block[:block.index("document.addEventListener('click'")]
        self.assertIn("_openDropdown", block)
        self.assertIn("_toggleMenu(true)", block)
        self.assertLess(block.index("_openDropdown"), block.index("_isOpen"),
                        "the submenu must be checked before the menu")

    def test_aria_expanded_tracks_the_menu(self):
        """It is closed from several places; a stale 'true' tells a screen
        reader the opposite of what is on screen."""
        self.assertIn('aria-expanded="false"', INDEX)
        self.assertIn("_syncExpanded", MENU)
        for fn in ("function _toggleMenu", "function _closeMenu"):
            block = MENU[MENU.index(fn):]
            self.assertIn("_syncExpanded()", block[:block.index("\n}")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
