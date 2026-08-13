"""
The branding palette: green, black->white, and semantics — nothing else.

WHY. Standardized 2026-08-13 ("green as the New Conversation button should be
the main color... green, black, and white, and whatever shades come up").
Before the sweep the UI carried 383 off-palette utilities — blue info boxes,
purple wizard steps, a teal/pink/indigo rainbow in the help center, a purple
avatar placeholder — each one a local decision that read as a different
product. The palette is now:

    green-*                the one brand accent
    neutral-*/gray-*       the black->white axis (canvas #f9f9f9 / #000)
    red-* / amber-* /      MEANING only: error/destructive, warning/caution,
    yellow-* / green-*     approved. Never decoration.

EXEMPT, deliberately — function, not chrome (see the styles.css palette block):
    ui-agent-mark.js  — MARK_FILLS is a categorical palette for telling agents
                        apart, contrast-verified, engineered NOT to collide
                        with the outcome ring hues. One green would destroy
                        both properties.
    connector logos   — Google/Microsoft/GitHub SVG fills are their marks.

This test is the enforcement half: a banned hue anywhere in the UI fails CI,
so the palette cannot drift back one "quick blue info box" at a time.

Run:  docker compose -f docker-compose.test.yml run --rm tests -k brand
"""
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

# Off-palette hexes that were swept and must not return. The old purple
# avatar placeholder is the canary: it was the most-copied single value.
BANNED_HEXES = ("7e22ce", "2563eb", "3b82f6", "8b5cf6", "a855f7", "6366f1",
                "0ea5e9", "06b6d4", "ec4899", "10b981", "34d399")

EXEMPT_FILES = {"ui-agent-mark.js"}  # categorical monogram palette, see docstring


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
        """--accent hardcoded to a hex is how the palette forks: one edit to
        the token must move everything that claims to be brand-colored."""
        self.assertIn("--accent: var(--brand-600)", CSS)
        self.assertIn("--accent: var(--brand-500)", CSS)

    def test_the_user_bubble_is_the_brand_green(self):
        self.assertRegex(CSS, r"--user-bg: #16a34a")

    def test_the_exemptions_are_documented_where_the_palette_is(self):
        """An exemption that isn't written down reads as a violation to the
        next person, who then 'fixes' the monogram palette."""
        block = CSS[:CSS.index(":root")]
        self.assertIn("MARK_FILLS", block)
        self.assertIn("third-party logos", block)


class TheExemptionIsRealNotForgotten(unittest.TestCase):

    def test_the_monogram_palette_is_still_categorical(self):
        """Three distinct hues, on purpose. If someone sweeps this file too,
        agents become indistinguishable AND the fills start colliding with the
        green/amber/red outcome rings — the exact blend its comment warns of."""
        mark = (PUBLIC / "js" / "ui" / "ui-agent-mark.js").read_text(encoding="utf-8")
        m = re.search(r"MARK_FILLS\s*=\s*\[([^\]]+)\]", mark)
        self.assertIsNotNone(m)
        fills = re.findall(r"#[0-9a-fA-F]{6}", m.group(1))
        self.assertEqual(len(set(fills)), 3,
                         "the monogram palette must stay three distinct fills")


class NewConversationButtonIsTheReference(unittest.TestCase):

    def test_the_reference_button_uses_the_brand_green(self):
        """The user named this button as the standard; if it drifts, the
        'standard' is whatever it drifted to."""
        sidebar = (PUBLIC / "js" / "ui" / "ui-auth-sidebar.js").read_text(encoding="utf-8")
        btn = sidebar[sidebar.index('id="new-chat-button"'):]
        btn = btn[:btn.index("</button>")]
        self.assertIn("bg-green-600", btn)
        self.assertIn("hover:bg-green-700", btn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
