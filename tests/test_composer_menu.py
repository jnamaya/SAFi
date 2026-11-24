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
CSS = (ROOT / "public" / "css" / "styles.css").read_text(encoding="utf-8")
APP = (ROOT / "public" / "js" / "core" / "app.js").read_text(encoding="utf-8")

PANEL = INDEX[INDEX.index('id="composer-plus-menu"'):]
PANEL = PANEL[:PANEL.index("<!-- Text Area -->")]

AGENT_RENDER = SIDEBAR[SIDEBAR.index("function renderAgentSelectorOptions"):]


class CategoriesOpenFlyouts(unittest.TestCase):

    def test_each_category_is_a_trigger_with_a_flyout(self):
        self.assertEqual(PANEL.count("data-flyout"), 3)
        self.assertEqual(PANEL.count("submenu-trigger"), 3)
        self.assertEqual(PANEL.count("submenu-panel"), 3)

    def test_the_panel_does_not_clip_its_own_flyouts(self):
        m = re.search(r'id="composer-plus-menu"[^>]*?class="([^"]+)"', INDEX, re.S)
        cls = m.group(1)
        self.assertIn("overflow-y-auto", cls, "mobile accordion still needs to scroll")
        self.assertIn("md:overflow-visible", cls, "desktop flyouts would be clipped")
        self.assertIn("md:max-h-none", cls)

    def test_the_flyout_only_flies_out_on_desktop(self):
        m = re.search(r'class="submenu-panel([^"]+)"', PANEL)
        cls = m.group(1)
        self.assertIn("md:absolute", cls)
        self.assertIn("md:left-full", cls)
        self.assertNotIn(" absolute", cls, "absolute must be md-only")

    def test_hover_has_a_grace_period(self):
        self.assertIn("FLYOUT_CLOSE_DELAY", MENU)
        m = re.search(r"FLYOUT_CLOSE_DELAY\s*=\s*(\d+)", MENU)
        self.assertGreaterEqual(int(m.group(1)), 120)

    def test_click_works_too_because_touch_has_no_hover(self):
        block = MENU[MENU.index("function _initFlyouts"):]
        block = block[:block.index("\n/** Opens one flyout")]
        self.assertIn("addEventListener('click'", block)
        self.assertIn("addEventListener('mouseenter'", block)
        self.assertIn("DESKTOP.matches", block, "hover must be desktop-gated")

    def test_only_one_flyout_is_open_at_a_time(self):
        block = MENU[MENU.index("function _setFlyout"):]
        self.assertIn("querySelectorAll", block[:block.index("\n}")])

    def test_the_flyout_grows_upward(self):
        m = re.search(r'class="submenu-panel([^"]+)"', PANEL)
        self.assertIn("md:bottom-0", m.group(1))
        self.assertNotIn("md:top-0", m.group(1))

    def test_the_flyout_has_padding_of_its_own(self):
        m = re.search(r'class="submenu-panel([^"]+)"', PANEL)
        cls = m.group(1)
        self.assertIn("md:p-2", cls, "desktop flyout rows touched the border")
        self.assertIn("py-1", cls, "inline accordion had no vertical room")

    def test_the_flyout_is_tall_enough_to_show_a_list(self):
        m = re.search(r'class="submenu-panel([^"]+)"', PANEL)
        cap = re.search(r"md:max-h-\[(\d+)rem\]", m.group(1))
        self.assertIsNotNone(cap, "flyout needs an explicit desktop height cap")
        self.assertGreaterEqual(int(cap.group(1)), 24)

    def test_overflow_scrolls_instead_of_clipping(self):
        m = re.search(r'class="submenu-panel([^"]+)"', PANEL)
        self.assertIn("md:overflow-y-auto", m.group(1))
        self.assertIn("custom-scrollbar", m.group(1))

    def test_the_cap_and_its_overflow_are_both_cleared(self):
        block = MENU[MENU.index("function _keepOnScreen"):]
        block = block[:block.index("\nfunction _toggleMenu")]
        self.assertIn("panel.style.overflowY = ''", block)

    def test_the_height_is_capped_to_the_room_above(self):
        block = MENU[MENU.index("function _keepOnScreen"):]
        block = block[:block.index("\nfunction _toggleMenu")]
        self.assertIn("maxHeight", block)
        self.assertIn("FLYOUT_MIN_HEIGHT", block)
        self.assertIn("r.bottom", block, "room is measured from the anchored edge")

    def test_the_cap_is_cleared_before_remeasuring(self):
        block = MENU[MENU.index("function _keepOnScreen"):]
        block = block[:block.index("\nfunction _toggleMenu")]
        self.assertLess(block.index("panel.style.maxHeight = ''"),
                        block.index("getBoundingClientRect"))

    def test_a_flyout_near_the_edge_flips_sides(self):
        self.assertIn("_keepOnScreen", MENU)
        self.assertIn("flyout-left", MENU)
        self.assertIn(".submenu-panel.flyout-left", CSS)

    def test_escape_unwinds_the_flyout_before_the_panel(self):
        block = MENU[MENU.index("e.key !== 'Escape'"):]
        block = block[:block.index("document.addEventListener('click'")]
        self.assertIn("_openFlyout", block)
        self.assertLess(block.index("_openFlyout"), block.index("closeComposerMenu"))

    def test_closing_the_panel_closes_any_flyout(self):
        block = MENU[MENU.index("export function closeComposerMenu"):]
        self.assertIn("_setFlyout(null)", block[:block.index("\n}")])


class TheRowsShowCurrentState(unittest.TestCase):

    def test_each_category_has_a_subtitle_element(self):
        for el in ("plus-agent-current", "plus-model-current", "plus-data-current"):
            self.assertIn(f'id="{el}"', PANEL)

    def test_the_writers_target_them(self):
        self.assertIn("getElementById('plus-agent-current')", MENU)
        self.assertIn("getElementById('plus-model-current')", MENU)
        self.assertIn("getElementById('plus-data-current')", MENU)

    def test_data_sources_reports_its_connected_count(self):
        self.assertIn("updateDataSourcesLabel", DATA)
        self.assertIn("connected.length", DATA)


class OneSurface(unittest.TestCase):

    def test_the_three_lists_live_inside_the_panel(self):
        for el in ("agent-selector-dropdown", "model-selector-dropdown",
                   "data-sources-dropdown"):
            with self.subTest(section=el):
                self.assertIn(f'id="{el}"', PANEL,
                              f"{el} is outside the + panel again")

    def test_the_list_containers_are_still_plain(self):
        for el in ("agent-selector-dropdown", "model-selector-dropdown",
                   "data-sources-dropdown"):
            m = re.search(rf'id="{el}"[^>]*?class="([^"]+)"', PANEL, re.S)
            with self.subTest(section=el):
                self.assertNotIn("absolute", m.group(1))
                self.assertNotIn("hidden", m.group(1))

    def test_the_drill_down_machinery_is_gone(self):
        for gone in ("toggleDropdown", "_closeAllDropdowns", "_openDropdown"):
            self.assertNotIn(gone, MENU, f"{gone} survived")
        for gone in ("toggleAgentDropdown", "toggleModelDropdown", "toggleDataDropdown"):
            self.assertNotIn(gone, SIDEBAR + MODEL + DATA + APP + INDEX,
                             f"{gone} survived")


class SectionsAreLabelledOnce(unittest.TestCase):

    def test_the_panel_prints_the_category_names(self):
        for label in (">Agents</div>", ">AI Models</div>", ">Tools</div>"):
            self.assertIn(label, PANEL)

    def test_the_lists_do_not_print_their_own(self):
        self.assertNotIn("Select agent", SIDEBAR)
        self.assertNotIn("Select model", MODEL)

    def test_attach_is_still_a_button_not_a_section(self):
        self.assertIn('id="plus-attach-btn"', PANEL)
        self.assertIn("Attach File", PANEL)


class ChoosingSomethingDismissesThePanel(unittest.TestCase):

    def test_both_lists_close_the_panel(self):
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

    def test_the_label_writers_are_still_exported(self):
        self.assertIn("export function updateAgentLabel", MENU)
        self.assertIn("export function updateModelLabel", MENU)


if __name__ == "__main__":
    unittest.main(verbosity=2)
