"""
Invariants for the generated agent marks (`public/js/ui/ui-agent-mark.js`).

The agent avatars used to be illustrated cartoon portraits of four young men.
They were replaced with initials on a flat fill because a human face is the
wrong affordance for a compliance product, because four near-identical
portraits could not signal *which* governed agent answered at 20–42px, and
because the lineup read as one demographic. See backlog item 17.

The palette is a **computed** result, not a chosen one. Every fill is pinned to
a narrow lightness band by three simultaneous contrast gates, which is also why
there are only three of them. The failure mode this file exists to catch is
somebody later "brightening" a fill or adding a fourth, silently breaking a
gate that no other test measures and that looks fine on the author's monitor.

Contrast is recomputed here from the WCAG definition rather than trusted from a
comment, so the numbers in the module's docstring cannot drift away from the
hexes they describe.

Parses the module rather than executing it — there is no JS runtime in the test
image (`Dockerfile` is `python:3.11-slim`). So this pins the palette, the
structural rules and the absence of the old assets; the glyph geometry still
needs eyes.

Requires no database. Run:  venv/bin/python tests/test_agent_mark.py
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "public" / "js" / "ui" / "ui-agent-mark.js"
SIDEBAR = ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js"
ASSETS = ROOT / "public" / "assets"
CSS = ROOT / "public" / "css" / "styles.css"

# The surfaces the mark actually renders against, from styles.css:
#   .ai-avatar img       { background-color: #ffffff }
#   .dark .ai-avatar img { background-color: #1a1a1a }
LIGHT_SURFACE = "#ffffff"
DARK_SURFACE = "#1a1a1a"

GLYPH = "#ffffff"

# A letterform is read as text, so it takes the WCAG text floor. The 3:1
# non-text/graphic floor is NOT enough here — that was the trap.
GLYPH_MIN = 4.5
# The mark itself is a graphic object against the surface: 3:1.
SURFACE_MIN = 3.0

# The illustrated portraits. Deleted, and they must stay deleted — an
# unreferenced-but-present file gets re-wired by the next person who greps for
# an avatar and finds one.
REMOVED_FACES = (
    "fiduciary.svg",
    "tutor.svg",
    "health_navigator.svg",
    "the_health_navigator.svg",
    "bible_scholar.svg",
)

# Survives because it is not a agent portrait: safi.svg is the product
# wordmark, which The SAFi Guide is entitled to wear.
KEPT_MARKS = ("safi.svg",)


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def _contrast(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class AgentMarkPalette(unittest.TestCase):
    """The three fills, and the gates that produced them."""

    @classmethod
    def setUpClass(cls):
        cls.src = MODULE.read_text(encoding="utf-8")
        m = re.search(r"const\s+MARK_FILLS\s*=\s*\[(.*?)\]", cls.src, re.S)
        assert m, "MARK_FILLS array not found — did the module get restructured?"
        cls.fills = re.findall(r"#[0-9a-fA-F]{6}", m.group(1))

    def test_01_palette_is_three_valid_hexes(self):
        # Three is not arbitrary: a fourth hue satisfying all three contrast
        # gates and staying >=15 normal-vision dE from the others does not
        # exist in sRGB. If someone adds one, the pair gates below will fail,
        # but fail here first with a clearer message.
        self.assertEqual(len(self.fills), 3,
                         f"expected 3 fills, found {len(self.fills)}: {self.fills}. "
                         f"A fourth slot was searched for and does not exist — see the "
                         f"module docstring before adding one.")
        for hx in self.fills:
            self.assertRegex(hx, r"^#[0-9a-f]{6}$",
                             f"{hx}: keep fills lowercase 6-digit hex so the parser "
                             f"and the eye agree")
        self.assertEqual(len(set(self.fills)), 3, "two fills are identical")

    def test_02_white_glyph_is_readable_on_every_fill(self):
        """The gate most likely to be broken by a well-meaning tweak."""
        for hx in self.fills:
            with self.subTest(fill=hx):
                ratio = _contrast(hx, GLYPH)
                self.assertGreaterEqual(
                    round(ratio, 2), GLYPH_MIN,
                    f"{hx}: white glyph contrast {ratio:.2f}:1 is below {GLYPH_MIN}:1. "
                    f"The initials ARE the identity channel here — colour only groups. "
                    f"Darken the fill rather than dropping this bound.")

    def test_03_fill_stands_off_both_surfaces(self):
        """One asset serves light and dark. A `data:` URI cannot see the app's
        `.dark` class, so `prefers-color-scheme` inside the SVG would track the
        OS rather than the app — there is no per-theme variant to fall back on,
        which is why both gates apply to the same hex."""
        for hx in self.fills:
            for surface, label in ((LIGHT_SURFACE, "light"), (DARK_SURFACE, "dark")):
                with self.subTest(fill=hx, surface=label):
                    ratio = _contrast(hx, surface)
                    self.assertGreaterEqual(
                        round(ratio, 2), SURFACE_MIN,
                        f"{hx}: {ratio:.2f}:1 against the {label} surface {surface}, "
                        f"below {SURFACE_MIN}:1 — the mark's edge disappears.")

    def test_04_fills_are_mutually_distinguishable(self):
        """Not a CVD simulation — that needs the dataviz validator, which is not
        vendored. This is the plain-vision floor, which is the hard gate the
        skill says secondary encoding cannot excuse, and it is the one that
        collapses if someone nudges two fills toward each other."""
        import itertools
        for a, b in itertools.combinations(self.fills, 2):
            with self.subTest(pair=(a, b)):
                # Luminance alone is a weak proxy for OKLab dE, so compare the
                # channel vectors too: identical-luminance different-hue pairs
                # are fine, near-identical-channel pairs are not.
                da = sum(abs(int(a.lstrip('#')[i:i+2], 16) - int(b.lstrip('#')[i:i+2], 16))
                         for i in (0, 2, 4))
                self.assertGreater(
                    da, 90,
                    f"{a} and {b} differ by only {da} across RGB channels — too close "
                    f"to read as different agents. Re-derive with the dataviz "
                    f"validator rather than eyeballing a replacement.")


class GlyphIsAlwaysPresent(unittest.TestCase):
    """Colour is secondary encoding here; the letters are primary. Three fills
    for an unbounded number of agents is only defensible while that holds."""

    @classmethod
    def setUpClass(cls):
        cls.src = MODULE.read_text(encoding="utf-8")

    def test_05_svg_emits_a_text_element(self):
        self.assertIn("<text", self.src,
                      "the mark must render initials — colour alone cannot carry "
                      "identity when agents share a fill")

    def test_06_initials_are_alphanumeric_only(self):
        """This is what makes embedding the name in SVG markup safe by
        construction rather than by escaping: no character survives that could
        close a tag or an attribute."""
        self.assertRegex(self.src, r"replace\(/\[\^a-z0-9\\s\]/g",
                         "normalizeAgentName must strip to [a-z0-9 ] — otherwise a "
                         "quote or an angle bracket in an org-authored agent name "
                         "reaches the SVG source")

    def test_07_url_is_percent_encoded_not_base64(self):
        # btoa throws on non-Latin1, and an org can name an agent anything.
        # encodeURIComponent also escapes " and #, which is what keeps the
        # result safe to interpolate into an HTML src attribute.
        self.assertIn("encodeURIComponent", self.src)
        self.assertNotIn("btoa(", self.src,
                         "btoa throws on non-Latin1 agent names")

    def test_08_slot_is_keyed_on_the_name_not_a_roster_index(self):
        """An agent's identity colour must not change when somebody adds an
        agent. This is the dataviz rule that colour follows the entity, never
        its rank."""
        self.assertIn("normalizeAgentName", self.src)
        self.assertNotRegex(
            self.src, r"MARK_FILLS\[\s*(?:i|idx|index|position)\s*[%\]]",
            "slot must derive from the name, not from an iteration index")


class TheFacesAreGone(unittest.TestCase):
    """The point of the change. An unreferenced file left on disk is an
    invitation, so this asserts absence, not just non-use."""

    def test_09_face_assets_are_deleted(self):
        present = [f for f in REMOVED_FACES if (ASSETS / f).exists()]
        self.assertEqual(present, [],
                         f"cartoon portrait(s) back on disk: {present}. These were "
                         f"removed deliberately — see backlog item 17.")

    def test_10_kept_marks_still_exist(self):
        """The inverse guard: deleting this would leave the SAFi Guide with a
        broken image, since getAvatarForProfile returns its path directly."""
        for f in KEPT_MARKS:
            with self.subTest(asset=f):
                self.assertTrue((ASSETS / f).exists(),
                                f"assets/{f} is referenced by getAvatarForProfile")

    def test_11_no_code_path_references_a_face(self):
        js_root = ROOT / "public" / "js"
        offenders = []
        for path in js_root.rglob("*.js"):
            if "lib" in path.parts:      # vendored bundles
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for face in REMOVED_FACES:
                # The module docstring names them while explaining the removal;
                # that is prose, not a reference. Only count a real asset path.
                if f"assets/{face}" in text:
                    offenders.append(f"{path.relative_to(ROOT)} -> {face}")
        self.assertEqual(offenders, [], f"live references to deleted assets: {offenders}")

    def test_12_avatar_image_has_no_crop_transform(self):
        """`.ai-avatar img` carried `transform: scale(1.2)` with
        `transform-origin: center 35%` to crop the old portraits to head and
        shoulders, plus a scale(1.3) hover zoom. Both slice the edges off a
        letterform. The parent `.ai-avatar:hover` keeps the hover feedback."""
        css = CSS.read_text(encoding="utf-8")
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)   # comments describe the removal
        for selector in (r"\.ai-avatar\s+img", r"\.ai-avatar:hover\s+img"):
            for m in re.finditer(selector + r"\s*\{([^}]*)\}", css_nc):
                with self.subTest(selector=selector):
                    self.assertNotIn(
                        "transform", m.group(1),
                        f"a transform on {selector} crops the monogram's letterform")


class ResolverWiring(unittest.TestCase):
    """getAvatarForProfile is the single entry point all 10 call sites use."""

    @classmethod
    def setUpClass(cls):
        cls.src = SIDEBAR.read_text(encoding="utf-8")

    def test_13_resolver_falls_back_to_a_generated_mark(self):
        self.assertIn("agentMark(", self.src,
                      "getAvatarForProfile must generate a mark for unlisted agents")

    def test_14_custom_avatar_still_wins(self):
        """An org that supplies artwork for its own agent must keep getting it —
        the monogram is a fallback, not an override."""
        body = self.src[self.src.index("export function getAvatarForProfile"):]
        body = body[:body.index("\n}")]
        custom = body.find("customProfile.avatar")
        generated = body.find("agentMark(")
        # find(), not index() — a missing call should fail this assertion with a
        # readable message rather than raise ValueError out of the test body.
        self.assertNotEqual(custom, -1, "the org-supplied avatar check is gone")
        self.assertNotEqual(generated, -1, "the generated-mark fallback is gone")
        self.assertLess(custom, generated,
                        "the org-supplied avatar check must come before the generated "
                        "mark, or custom artwork is ignored")

    def test_15_unknown_agents_do_not_get_the_vendor_logo(self):
        """The old default returned safi.svg for anything unrecognized, so an
        org's custom agent appeared wearing the SAFi wordmark. Only an
        empty/missing name may fall back to it now."""
        body = self.src[self.src.index("export function getAvatarForProfile"):]
        body = body[:body.index("\n}")]
        self.assertNotRegex(
            body, r"default:\s*\n\s*return 'assets/safi\.svg'",
            "safi.svg must not be the catch-all default — unknown agents get a monogram")
        self.assertIn("!key", body,
                      "an empty name should still fall back to the product mark")


if __name__ == "__main__":
    unittest.main(verbosity=2)
