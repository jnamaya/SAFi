"""
Markdown type-scale invariants for public/css/styles.css.

Nothing else in the suite touches CSS, and a type scale is exactly the kind of
thing that regresses silently: someone nudges one heading a hair and the
hierarchy quietly collapses without any test going red. That is how the scale
this file guards got broken in the first place — h2 at 1.32rem and h3 at
1.25rem, a 1.056 step (1.1px at a 16px body) at identical weight, which read as
one size rather than two levels.

Parses the stylesheet rather than a browser, so it checks the declarations, not
the render. Layout still needs eyes.

Requires no database. Run:  venv/bin/python tests/test_type_scale.py
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
    out = {}
    for m in re.finditer(r"(?:^|\})([^{}]*)\{([^}]*)\}", css, re.MULTILINE):
        raw = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
        if selector not in [s.strip() for s in raw.split(",")]:
            continue
        for line in m.group(2).split(";"):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
