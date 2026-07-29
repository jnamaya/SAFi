"""
CSS invariants for public/css/styles.css that regress silently.

Nothing else in the suite touches CSS, and these are exactly the properties
that break without any test going red — someone nudges one heading a hair, or
drops a flex-wrap while tidying, and the result only shows up on a particular
screen width in front of a user.

Two groups so far, both from real defects:

- **Type scale.** h2 was 1.32rem and h3 1.25rem — a 1.056 step, 1.1px at a 16px
  body, at identical weight. Two levels that differ by one pixel are one level.
- **Action bar overflow.** The message action bar is `inline-flex` and
  `.score-seg` is `white-space: nowrap`, so before `flex-wrap` it could not
  reflow: adding the conflict segment pushed it out of the bubble on a phone.
  Wrapping is what makes overflow impossible at any content width, so that is
  the property worth pinning, not the individual pixel widths.

Parses the stylesheet rather than a browser, so it checks declarations, not the
render. Actual layout still needs eyes.

Requires no database. Run:  venv/bin/python tests/test_css_invariants.py
"""
import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "public" / "css" / "styles.css"

# Below roughly this, two adjacent levels stop reading as a hierarchy. GitHub's
# markdown scale steps 1.33/1.20/1.25 for comparison; we run calmer at 1.15.
MIN_STEP = 1.15

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _decls(css, selector):
    """Every declaration that applies to `selector`, merged in source order.

    Two things a naive parser gets wrong here, both of which would make these
    tests pass for the wrong reason:

    - Grouped selectors. `.chat-bubble h5, .chat-bubble h6 { … }` is a normal
      way to write this, so the selector has to be matched anywhere in a
      comma-separated list, not compared to the whole list.
    - The same selector appearing in more than one rule. `.chat-bubble h1` is
      in both the shared line-height rule and its own block; returning the
      first match reported h1 as having no font-size at all. Later declarations
      overwrite earlier ones, which is what the cascade does for equal
      specificity.

    Returns {} when nothing matches, so callers can tell "no rule" from
    "rule without this property".
    """
    strip_comments = lambda s: re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    out = {}
    for m in re.finditer(r"(?:^|\})([^{}]*)\{([^}]*)\}", css, re.MULTILINE):
        if selector not in [s.strip() for s in strip_comments(m.group(1)).split(",")]:
            continue
        # Comments must come out of the BODY too, not just the selector: a
        # comment mentioning `min-width:auto` above a `min-width: 0` line got
        # parsed as the declaration itself and the real one was never seen.
        for line in strip_comments(m.group(2)).split(";"):
            if ":" in line:
                prop, _, val = line.partition(":")
                out[prop.strip()] = val.strip()
    return out


def _decl(css, selector, prop):
    return _decls(css, selector).get(prop)


class TestMarkdownTypeScale(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.sizes, cls.weights = {}, {}
        for h in HEADINGS:
            d = _decls(cls.css, f".chat-bubble {h}")
            size = d.get("font-size")
            weight = d.get("font-weight")
            if size:
                num = re.match(r"([\d.]+)", size)
                if num:
                    cls.sizes[h] = (float(num.group(1)), size)
            if weight and weight.isdigit():
                cls.weights[h] = int(weight)

    def test_01_every_heading_level_is_styled(self):
        """h4-h6 are the trap: Tailwind's preflight sets every heading to
        `font-size: inherit; font-weight: inherit`, so an unstyled h4 does NOT
        fall back to a browser default — it renders as a plain paragraph."""
        missing = [h for h in HEADINGS if h not in self.sizes]
        self.assertEqual(missing, [], f"unstyled heading levels: {missing}")

    def test_02_sizes_are_em_not_rem(self):
        """em so the scale tracks its container. The saved-content modal renders
        this markdown at text-sm (14px); rem would pin headings to the 16px root
        and produce a different hierarchy from the same stylesheet."""
        for h, (_, raw) in self.sizes.items():
            self.assertTrue(raw.endswith("em") and not raw.endswith("rem"),
                            f"{h} font-size is {raw!r}; expected an em value")

    def test_03_sizes_descend(self):
        vals = [self.sizes[h][0] for h in HEADINGS]
        for a, b, ha, hb in zip(vals, vals[1:], HEADINGS, HEADINGS[1:]):
            self.assertGreaterEqual(a, b, f"{ha} ({a}em) must not be smaller than {hb} ({b}em)")

    def test_04_adjacent_steps_clear_the_perceptual_floor(self):
        """The actual regression guard. h3->h4 is a real size step even though h4
        equals body size, and h4->h5 is checked too — h5 was briefly 0.94em, a
        1px difference from h4 at the same weight, i.e. the very defect this
        file exists to catch. h5 and h6 are intentionally one level, so no step
        is asserted between them."""
        for a, b in (("h1", "h2"), ("h2", "h3"), ("h3", "h4"), ("h4", "h5")):
            step = self.sizes[a][0] / self.sizes[b][0]
            self.assertGreaterEqual(
                round(step, 4), MIN_STEP,
                f"{a}/{b} step is {step:.3f}, below the {MIN_STEP} floor — "
                f"{a}={self.sizes[a][1]}, {b}={self.sizes[b][1]}")

    def test_05_h4_is_body_sized_and_h1_stays_calm(self):
        self.assertEqual(self.sizes["h4"][0], 1.0,
                         "h4 is the same-size-but-bold level by convention")
        # The chat surface is deliberately calmer than an article: a model that
        # opens with '#' should not shout. GitHub uses 2em.
        self.assertLessEqual(self.sizes["h1"][0], 1.7,
                             "h1 too loud for a chat bubble")

    def test_06_weight_is_a_second_signal_and_descends(self):
        """Size alone was the only differentiator before, and it was 1.1px.
        Every level must also be bolder than body text (400), or h4-h6 vanish."""
        missing = [h for h in HEADINGS if h not in self.weights]
        self.assertEqual(missing, [], f"headings with no explicit weight: {missing}")
        vals = [self.weights[h] for h in HEADINGS]
        for a, b, ha, hb in zip(vals, vals[1:], HEADINGS, HEADINGS[1:]):
            self.assertGreaterEqual(a, b, f"{ha} weight {a} < {hb} weight {b}")
        for h, w in self.weights.items():
            self.assertGreater(w, 400, f"{h} at weight {w} would not read as a heading")
        self.assertGreater(self.weights["h3"], self.weights["h4"],
                           "h4 shares h3's size, so weight must separate them")

    def test_07_variable_font_covers_the_declared_weights(self):
        """The graded weights (670, 640, 620) are only real because Inter is
        loaded as a variable font. If that @font-face ever becomes static
        instances, these snap and the second signal silently disappears."""
        self.assertRegex(self.css, r"InterVariable\.woff2",
                         "graded heading weights assume the variable Inter face")
        m = re.search(r"font-weight:\s*(\d+)\s+(\d+)", self.css)
        self.assertIsNotNone(m, "no variable font-weight range found in @font-face")
        lo, hi = int(m.group(1)), int(m.group(2))
        for h, w in self.weights.items():
            self.assertTrue(lo <= w <= hi,
                            f"{h} weight {w} outside the loaded range {lo}-{hi}")

    def test_08_h1_rule_is_visible_in_both_themes(self):
        """h1's border is one of the cues separating it from h2; at
        rgba(0,0,0,.1) it was invisible on the dark surface."""
        self.assertIsNotNone(_decl(self.css, ".chat-bubble h1", "border-bottom"))
        dark = _decls(self.css, ".dark .chat-bubble h1")
        self.assertTrue(dark, "no dark-mode override for the h1 rule")
        self.assertIn("255", dark.get("border-bottom-color", ""),
                      "dark h1 rule must be a light colour")

    def test_09_no_dead_prose_classes_remain(self):
        """@tailwindcss/typography is not installed (tailwind.config.js has
        plugins: []), so `prose` classes generate nothing. They read as styling
        that exists."""
        cfg = (CSS.parent.parent / "tailwind.config.js").read_text(encoding="utf-8")
        if "@tailwindcss/typography" in cfg:
            self.skipTest("typography plugin now installed; prose classes are real")
        offenders = []
        for js in (CSS.parent.parent / "js").rglob("*.js"):
            if js.name.endswith(".min.js"):
                continue
            for i, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'class="[^"]*\bprose\b', line):
                    offenders.append(f"{js.name}:{i}")
        self.assertEqual(offenders, [], f"inert prose classes: {offenders}")


def _media_block(css, query_fragment):
    """The body of the first @media block whose condition contains the fragment.
    Brace-counts rather than regexing, because media blocks nest rules."""
    i = css.find(f"@media {query_fragment}")
    if i < 0:
        return None
    start = css.find("{", i)
    if start < 0:
        return None
    depth, j = 0, start
    while j < len(css):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1:j]
        j += 1
    return None


class TestActionBarFitsNarrowScreens(unittest.TestCase):
    """The audit pill overflowed the bubble on a phone as soon as a turn carried
    a conflict. Pins the properties that make that impossible, not the widths."""

    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.mobile = _media_block(cls.css, "(max-width: 639px)")

    def test_01_action_bar_can_wrap_on_narrow_screens(self):
        """The load-bearing assertion. Without wrap the bar is a single
        non-shrinkable row — `inline-flex` plus `white-space: nowrap` on
        .score-seg — so it pushes out of the bubble instead of reflowing."""
        self.assertIsNotNone(self.mobile, "no max-width:639px block; the mobile fix is gone")
        bar = _decls(self.mobile, ".msg-actionbar")
        self.assertTrue(bar, ".msg-actionbar has no narrow-screen rule")
        self.assertEqual(bar.get("flex-wrap"), "wrap",
                         "without flex-wrap the action bar can overflow the bubble again")
        self.assertEqual(bar.get("max-width"), "100%",
                         "max-width bounds the wrap to the bubble")

    def test_02_wrapped_bar_is_not_a_broken_stadium(self):
        """A 999px radius wrapped onto two rows reads as a rendering fault."""
        base_radius = _decl(self.css, ".msg-actionbar", "border-radius")
        self.assertEqual(base_radius, "999px", "desktop pill should stay a stadium")
        mobile_radius = _decls(self.mobile, ".msg-actionbar").get("border-radius")
        self.assertIsNotNone(mobile_radius, "wrapped bar needs a smaller radius")
        self.assertNotEqual(mobile_radius, "999px")

    def test_03_conflict_wording_shortens_rather_than_the_count(self):
        """"2 conflicts" -> "2" on narrow screens. The word is hidden, never the
        number: the count is the information, the noun is decoration."""
        self.assertIn(".conflict-word", self.mobile)
        self.assertEqual(_decls(self.mobile, ".score-seg .conflict-word").get("display"), "none")
        self.assertIsNone(_decls(self.mobile, ".score-seg .conflict-n").get("display"),
                          "the count itself must never be hidden")

    def test_04_tier_word_is_dropped_only_when_a_conflict_is_present(self):
        """A clean turn's bar is ~89px narrower and has room for the tier word,
        so hiding it unconditionally would remove information for no gain."""
        narrow = _media_block(self.css, "(max-width: 419px)")
        self.assertIsNotNone(narrow)
        self.assertEqual(_decls(narrow, ".score-seg.has-conflicts .score-label").get("display"), "none")
        self.assertFalse(_decls(narrow, ".score-seg .score-label"),
                         "must be scoped to .has-conflicts, not all score chips")

    def test_05_conflict_note_can_wrap_instead_of_pushing_out(self):
        """flex-basis:100% with the default min-width:auto floors the item at its
        min-content width, so a long value name would overflow the bubble."""
        note = _decls(self.css, ".conflict-note")
        self.assertEqual(note.get("flex"), "0 0 100%")
        self.assertEqual(note.get("min-width"), "0",
                         "without min-width:0 a long value name can overflow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
