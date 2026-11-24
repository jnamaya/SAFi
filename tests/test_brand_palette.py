import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "public"
CSS = (PUBLIC / "css" / "styles.css").read_text(encoding="utf-8")

BANNED_HUES = ("blue", "indigo", "purple", "violet", "sky", "cyan", "teal",
               "pink", "fuchsia", "rose", "emerald", "orange")
BANNED_RE = re.compile(r"\b(" + "|".join(BANNED_HUES) + r")-(\d{2,3})\b")

BANNED_HEXES = ("7e22ce", "2563eb", "3b82f6", "8b5cf6", "a855f7", "6366f1",
                "0ea5e9", "06b6d4", "ec4899", "10b981", "34d399")

EXEMPT_FILES = {"ui-agent-mark.js"}


def ui_files():
    yield PUBLIC / "index.html"
    for p in (PUBLIC / "js").rglob("*.js"):
        if "node_modules" not in str(p) and p.name not in EXEMPT_FILES:
            yield p


class NoOffPaletteUtilities(unittest.TestCase):

    def test_no_banned_hue_classes_anywhere_in_the_ui(self):
        offenders = []
        for f in ui_files():
            for m in BANNED_RE.finditer(f.read_text(encoding="utf-8")):
                offenders.append(f"{f.relative_to(ROOT)}: {m.group(0)}")
        self.assertEqual(offenders[:20], [],
                         f"{len(offenders)} off-palette utilities — the accent is green, "
                         "the axis is neutral, red/amber are semantics. "
                         "See the palette block at the top of styles.css.")

    def test_no_banned_hexes_in_ui_or_stylesheet(self):
        offenders = []
        for f in list(ui_files()) + [PUBLIC / "css" / "styles.css"]:
            t = f.read_text(encoding="utf-8").lower()
            for h in BANNED_HEXES:
                if h in t:
                    offenders.append(f"{f.relative_to(ROOT)}: #{h}")
        self.assertEqual(offenders, [])


class TheBrandTokensExist(unittest.TestCase):

    def test_the_palette_block_is_declared(self):
        for token, value in (("--brand-400", "#4ade80"), ("--brand-500", "#22c55e"),
                             ("--brand-600", "#16a34a"), ("--brand-700", "#15803d")):
            self.assertIn(f"{token}: {value}", CSS)

    def test_the_accent_derives_from_the_tokens(self):
        self.assertIn("--accent: var(--brand-600)", CSS)
        self.assertIn("--accent: var(--brand-500)", CSS)

    def test_the_user_bubble_is_the_brand_green(self):
        self.assertRegex(CSS, r"--user-bg: #16a34a")

    def test_the_exemptions_are_documented_where_the_palette_is(self):
        block = CSS[:CSS.index(":root")]
        self.assertIn("MARK_FILLS", block)
        self.assertIn("third-party logos", block)


class TheExemptionIsRealNotForgotten(unittest.TestCase):

    def test_the_monogram_palette_is_still_categorical(self):
        mark = (PUBLIC / "js" / "ui" / "ui-agent-mark.js").read_text(encoding="utf-8")
        m = re.search(r"MARK_FILLS\s*=\s*\[([^\]]+)\]", mark)
        self.assertIsNotNone(m)
        fills = re.findall(r"#[0-9a-fA-F]{6}", m.group(1))
        self.assertEqual(len(set(fills)), 3,
                         "the monogram palette must stay three distinct fills")


class OnePrimaryButtonLanguage(unittest.TestCase):

    INVERTED = re.compile(
        r"bg-(?:gray|neutral)-9\d\d dark:bg-white text-white")

    def test_the_inverted_black_primary_is_retired(self):
        offenders = [f"{f.relative_to(ROOT)}"
                     for f in ui_files()
                     if self.INVERTED.search(f.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [],
                         "primary actions are green (see the BUTTON HIERARCHY "
                         "block in styles.css); these reintroduce the black primary")

    def test_the_hierarchy_is_documented_with_the_palette(self):
        self.assertIn("BUTTON HIERARCHY", CSS)
        self.assertIn("PRIMARY", CSS)
        self.assertIn("DESTRUCTIVE", CSS)


class NoCollapsedColorSwaps(unittest.TestCase):

    PAIR = re.compile(
        r"classList\.(add|remove)\(([^)]*green[^)]*)\)\s*;?\s*\n\s*"
        r"[\w.]*classList\.(add|remove)\(([^)]*green[^)]*)\)")

    def test_no_add_then_remove_of_identical_color_classes(self):
        offenders = []
        for f in ui_files():
            if f.suffix != ".js":
                continue
            for m in self.PAIR.finditer(f.read_text(encoding="utf-8")):
                verb1, args1, verb2, args2 = m.groups()
                if verb1 != verb2 and args1.strip() == args2.strip():
                    offenders.append(f"{f.relative_to(ROOT)}: "
                                     f"{verb1}+{verb2} of {args1.strip()[:60]}")
        self.assertEqual(offenders, [],
                         "adding then removing the same color classes is a collapsed "
                         "two-color swap — one of the two states has lost its color")


class NewConversationButtonIsTheReference(unittest.TestCase):

    def test_the_reference_button_uses_the_brand_green(self):
        sidebar = (PUBLIC / "js" / "ui" / "ui-auth-sidebar.js").read_text(encoding="utf-8")
        btn = sidebar[sidebar.index('id="new-chat-button"'):]
        btn = btn[:btn.index("</button>")]
        self.assertIn("bg-green-600", btn)
        self.assertIn("hover:bg-green-700", btn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
