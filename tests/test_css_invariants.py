import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "public" / "css" / "styles.css"

MIN_STEP = 1.15

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _decls(css, selector):
    strip_comments = lambda s: re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    out = {}
    for m in re.finditer(r"(?:^|\})([^{}]*)\{([^}]*)\}", css, re.MULTILINE):
        if selector not in [s.strip() for s in strip_comments(m.group(1)).split(",")]:
            continue
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
        missing = [h for h in HEADINGS if h not in self.sizes]
        self.assertEqual(missing, [], f"unstyled heading levels: {missing}")

    def test_02_sizes_are_em_not_rem(self):
        for h, (_, raw) in self.sizes.items():
            self.assertTrue(raw.endswith("em") and not raw.endswith("rem"),
                            f"{h} font-size is {raw!r}; expected an em value")

    def test_03_sizes_descend(self):
        vals = [self.sizes[h][0] for h in HEADINGS]
        for a, b, ha, hb in zip(vals, vals[1:], HEADINGS, HEADINGS[1:]):
            self.assertGreaterEqual(a, b, f"{ha} ({a}em) must not be smaller than {hb} ({b}em)")

    def test_04_adjacent_steps_clear_the_perceptual_floor(self):
        for a, b in (("h1", "h2"), ("h2", "h3"), ("h3", "h4"), ("h4", "h5")):
            step = self.sizes[a][0] / self.sizes[b][0]
            self.assertGreaterEqual(
                round(step, 4), MIN_STEP,
                f"{a}/{b} step is {step:.3f}, below the {MIN_STEP} floor — "
                f"{a}={self.sizes[a][1]}, {b}={self.sizes[b][1]}")

    def test_05_h4_is_body_sized_and_h1_stays_calm(self):
        self.assertEqual(self.sizes["h4"][0], 1.0,
                         "h4 is the same-size-but-bold level by convention")
        self.assertLessEqual(self.sizes["h1"][0], 1.7,
                             "h1 too loud for a chat bubble")

    def test_06_weight_is_a_second_signal_and_descends(self):
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
        self.assertRegex(self.css, r"InterVariable\.woff2",
                         "graded heading weights assume the variable Inter face")
        m = re.search(r"font-weight:\s*(\d+)\s+(\d+)", self.css)
        self.assertIsNotNone(m, "no variable font-weight range found in @font-face")
        lo, hi = int(m.group(1)), int(m.group(2))
        for h, w in self.weights.items():
            self.assertTrue(lo <= w <= hi,
                            f"{h} weight {w} outside the loaded range {lo}-{hi}")

    def test_08_h1_rule_is_visible_in_both_themes(self):
        self.assertIsNotNone(_decl(self.css, ".chat-bubble h1", "border-bottom"))
        dark = _decls(self.css, ".dark .chat-bubble h1")
        self.assertTrue(dark, "no dark-mode override for the h1 rule")
        self.assertIn("255", dark.get("border-bottom-color", ""),
                      "dark h1 rule must be a light colour")

    def test_09_no_dead_prose_classes_remain(self):
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

    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.mobile = _media_block(cls.css, "(max-width: 639px)")

    def test_01_action_bar_can_wrap_on_narrow_screens(self):
        self.assertIsNotNone(self.mobile, "no max-width:639px block; the mobile fix is gone")
        bar = _decls(self.mobile, ".msg-actionbar")
        self.assertTrue(bar, ".msg-actionbar has no narrow-screen rule")
        self.assertEqual(bar.get("flex-wrap"), "wrap",
                         "without flex-wrap the action bar can overflow the bubble again")
        self.assertEqual(bar.get("max-width"), "100%",
                         "max-width bounds the wrap to the bubble")

    def test_02_wrapped_bar_is_not_a_broken_stadium(self):
        base_radius = _decl(self.css, ".msg-actionbar", "border-radius")
        self.assertEqual(base_radius, "999px", "desktop pill should stay a stadium")
        mobile_radius = _decls(self.mobile, ".msg-actionbar").get("border-radius")
        self.assertIsNotNone(mobile_radius, "wrapped bar needs a smaller radius")
        self.assertNotEqual(mobile_radius, "999px")

    def test_03_conflict_wording_shortens_rather_than_the_count(self):
        self.assertIn(".conflict-word", self.mobile)
        self.assertEqual(_decls(self.mobile, ".score-seg .conflict-word").get("display"), "none")
        self.assertIsNone(_decls(self.mobile, ".score-seg .conflict-n").get("display"),
                          "the count itself must never be hidden")

    def test_04_tier_word_is_dropped_only_when_a_conflict_is_present(self):
        narrow = _media_block(self.css, "(max-width: 419px)")
        self.assertIsNotNone(narrow)
        self.assertEqual(_decls(narrow, ".score-seg.has-conflicts .score-label").get("display"), "none")
        self.assertFalse(_decls(narrow, ".score-seg .score-label"),
                         "must be scoped to .has-conflicts, not all score chips")

    def test_05_conflict_note_can_wrap_instead_of_pushing_out(self):
        note = _decls(self.css, ".conflict-note")
        self.assertEqual(note.get("flex"), "0 0 100%")
        self.assertEqual(note.get("min-width"), "0",
                         "without min-width:0 a long value name can overflow")


class TestThinkingRingSweep(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.before = _decls(cls.css, ".ai-avatar.is-thinking::before")

    def test_01_the_sweep_exists(self):
        self.assertTrue(self.before,
                        ".ai-avatar.is-thinking::before is gone — the ring no longer "
                        "animates while the agent is thinking")
        self.assertIn("animation", self.before)
        self.assertIn("conic-gradient", self.before.get("background", ""),
                      "the sweep needs a conic gradient; a linear-gradient angle is "
                      "not interpolatable without @property")

    def test_02_the_pseudo_element_is_absolutely_positioned(self):
        self.assertEqual(self.before.get("position"), "absolute",
                         "a pseudo-element on a flex container must be absolutely "
                         "positioned or it becomes a flex item")

    def test_03_the_rotating_box_overhangs_the_circle(self):
        inset = self.before.get("inset", "")
        self.assertTrue(inset.startswith("-"),
                        f"inset must be negative so the rotating box always covers "
                        f"the circle; got {inset!r}")

    def test_04_the_mark_sits_above_the_sweep(self):
        img = _decls(self.css, ".ai-avatar img")
        self.assertEqual(img.get("position"), "relative")
        self.assertEqual(img.get("z-index"), "1")

    def test_05_the_ring_thickens_enough_to_read(self):
        rest = _decls(self.css, ".ai-avatar").get("padding", "")
        think = _decls(self.css, ".ai-avatar.is-thinking").get("padding", "")
        to_px = lambda v: float(re.match(r"([\d.]+)", v).group(1)) if re.match(r"([\d.]+)", v) else 0.0
        self.assertGreater(to_px(think), to_px(rest),
                           f"thinking ring ({think}) must be thicker than at rest "
                           f"({rest}) or the motion does not read at 32px")

    def test_06_reduced_motion_is_honoured(self):
        block = _media_block(self.css, "(prefers-reduced-motion: reduce)")
        self.assertIsNotNone(block,
                             "no prefers-reduced-motion block — a spinning ring must "
                             "be suppressible")
        override = _decls(block, ".ai-avatar.is-thinking::before")
        self.assertIn("animation", override,
                      "the reduced-motion block must override the sweep animation")
        self.assertNotIn("safi-ring-sweep", override.get("animation", ""),
                         "reduced motion must not simply restate the rotation")

    def test_07_both_themes_get_a_visible_comet(self):
        dark = _decls(self.css, ".dark .ai-avatar.is-thinking::before")
        self.assertIn("conic-gradient", dark.get("background", ""),
                      "dark mode needs its own comet colours, not the light ones")
        self.assertNotEqual(self.before.get("background"), dark.get("background"),
                            "light and dark must differ or one of them is invisible")

    def test_08_the_class_is_actually_applied(self):
        js = (CSS.parent.parent / "js" / "ui" / "ui-messages.js").read_text(
            encoding="utf-8", errors="replace")
        i = js.index("export function showLoadingIndicator")
        body = js[i:i + 2000]
        self.assertIn("ai-avatar is-thinking", body,
                      "showLoadingIndicator must put is-thinking on the avatar")


    OUTCOME_HUES = {
        "light": {"green": "34, 197, 94", "amber": "234, 179, 8", "red": "239, 68, 68"},
        "dark":  {"green": "74, 222, 128", "amber": "250, 204, 21", "red": "248, 113, 113"},
    }

    def test_09_the_sweep_carries_all_three_outcomes(self):
        for theme, sel in (("light", ".ai-avatar.is-thinking::before"),
                           ("dark", ".dark .ai-avatar.is-thinking::before")):
            bg = _decls(self.css, sel).get("background", "")
            for name, rgb in self.OUTCOME_HUES[theme].items():
                with self.subTest(theme=theme, hue=name):
                    self.assertIn(rgb, bg,
                                  f"{theme} sweep is missing the {name} outcome "
                                  f"({rgb}) — an in-flight ring showing fewer than "
                                  f"three outcomes asserts a verdict it does not have")

    def test_10_the_thinking_base_is_not_green(self):
        for sel in (".ai-avatar.is-thinking", ".dark .ai-avatar.is-thinking"):
            bg = _decls(self.css, sel).get("background", "")
            with self.subTest(sel=sel):
                for green in ("#22c55e", "#86efac", "#4ade80", "#15803d"):
                    self.assertNotIn(green, bg,
                                     "the in-flight base must be neutral — green "
                                     "here asserts alignment nothing has verified")

    def test_11_the_wheel_is_seamless(self):
        for theme, sel in (("light", ".ai-avatar.is-thinking::before"),
                           ("dark", ".dark .ai-avatar.is-thinking::before")):
            bg = _decls(self.css, sel).get("background", "")
            stops = re.findall(r"rgba?\(([^)]*)\)\s*([\d.]+)turn", bg)
            with self.subTest(theme=theme):
                self.assertGreaterEqual(len(stops), 4,
                                        "expected at least four stops for a "
                                        "three-hue wheel plus the wrap")
                first_rgb = stops[0][0].rsplit(",", 1)[0].strip()
                last_rgb = stops[-1][0].rsplit(",", 1)[0].strip()
                self.assertEqual(first_rgb, last_rgb,
                                 f"{theme} wheel starts on {first_rgb} and ends on "
                                 f"{last_rgb} — the wrap will show a seam")
                self.assertEqual(stops[-1][1], "1",
                                 "the final stop must land exactly on 1turn")


class TestOutcomeRing(unittest.TestCase):

    CHIP_DOT = {
        "green": "#22c55e",
        "yellow": "#eab308",
        "red": "#ef4444",
        "pending": "#a3a3a3",
    }

    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.js = (CSS.parent.parent / "js" / "ui" / "ui-messages.js").read_text(
            encoding="utf-8", errors="replace")

    def _ring(self, state, dark=False):
        sel = f"{'.dark ' if dark else ''}.ai-avatar.ring-{state}:not(.is-thinking)"
        return _decls(self.css, sel)

    def test_01_all_four_states_exist_in_both_themes(self):
        for state in ("pending", "green", "yellow", "red"):
            for dark in (False, True):
                with self.subTest(state=state, dark=dark):
                    d = self._ring(state, dark)
                    self.assertTrue(d, f"ring-{state} missing for "
                                       f"{'dark' if dark else 'light'} mode")
                    self.assertIn("background", d)

    def test_02_colours_come_from_the_chip_palette(self):
        for state in ("green", "yellow", "red", "pending"):
            with self.subTest(state=state):
                bg = self._ring(state).get("background", "")
                self.assertIn(self.CHIP_DOT[state], bg,
                              f"ring-{state} must use the chip's {state} "
                              f"{self.CHIP_DOT[state]}, not a new hue")

    def test_03_pending_is_neutral_never_green(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                bg = self._ring("pending", dark).get("background", "")
                for green in ("#22c55e", "#86efac", "#4ade80", "#15803d"):
                    self.assertNotIn(green, bg,
                                     "audit-pending must not be green — that "
                                     "asserts alignment nothing has verified")
                self.assertIn("a3a3a3", bg.replace("#", "").lower() + bg.lower(),
                              "pending should use the chip's neutral grey")

    def test_04_state_rules_yield_to_the_thinking_sweep(self):
        for state in ("pending", "green", "yellow", "red"):
            for dark in (False, True):
                with self.subTest(state=state, dark=dark):
                    self.assertTrue(
                        self._ring(state, dark),
                        f"ring-{state} must be scoped :not(.is-thinking)")

    def test_05_a_surface_gap_separates_ring_from_mark(self):
        light = _decls(self.css, ".ai-avatar img").get("box-shadow", "")
        dark = _decls(self.css, ".dark .ai-avatar img").get("box-shadow", "")
        self.assertIn("#ffffff", light,
                      "light mode needs a white hairline between ring and mark")
        self.assertIn("#1a1a1a", dark,
                      "dark mode needs a dark-surface hairline")

    def test_06_ring_is_wide_enough_to_read_a_colour(self):
        to_px = lambda v: float(re.match(r"([\d.]+)", v).group(1)) if v and re.match(r"([\d.]+)", v) else 0.0
        rest = to_px(_decls(self.css, ".ai-avatar").get("padding", ""))
        think = to_px(_decls(self.css, ".ai-avatar.is-thinking").get("padding", ""))
        self.assertGreaterEqual(rest, 3.0,
                                f"resting ring {rest}px is too thin to carry an "
                                f"outcome colour at 32px")
        self.assertGreater(think, rest,
                           "the thinking sweep still needs to be the thicker of "
                           "the two, allowing for the surface gap")

    def test_07_the_tier_thresholds_are_defined_exactly_once(self):
        self.assertIn("export function _scoreTier", self.js,
                      "the shared tier function is gone")
        self.assertEqual(self.js.count("'seg-yellow'"), 1,
                         "seg-yellow is assigned in more than one place — the "
                         "thresholds have been duplicated")
        self.assertEqual(self.js.count("< 5.0"), 1, "the red threshold is duplicated")
        self.assertEqual(self.js.count("< 8.0"), 1, "the yellow threshold is duplicated")

    def test_08_the_ring_is_painted_at_both_render_paths(self):
        self.assertGreaterEqual(
            self.js.count("_applyRingState("), 3,
            "expected the definition plus both call sites (initial render and "
            "updateMessageWithAudit)")
        i = self.js.index("export function updateMessageWithAudit")
        self.assertIn("_applyRingState(", self.js[i:i + 2600],
                      "updateMessageWithAudit must repaint the ring, or a live "
                      "turn never leaves audit-pending grey")

    def test_09_the_repaint_is_gated_on_the_payload_carrying_audit_info(self):
        i = self.js.index("export function updateMessageWithAudit")
        seg = self.js[i:i + 2600]
        self.assertIn("'spirit_score' in payload", seg,
                      "the repaint must be gated on the spirit_score KEY being "
                      "present, not on its value")
        self.assertIn("'ledger' in payload", seg,
                      "accept a ledger-bearing payload too, so the gate does not "
                      "depend on one field name")
        ring_at = seg.index("_applyRingState(")
        guard_at = seg.index("if (hasScore)")
        self.assertLess(ring_at, guard_at,
                        "the gated repaint must still run before the hasScore "
                        "branch, so a null-score audit leaves pending grey")

    def test_10_a_partial_payload_cannot_reset_the_ring(self):
        msgs = (CSS.parent.parent / "js" / "ui" / "ui-messages.js").read_text(
            encoding="utf-8", errors="replace")
        i = msgs.index("export function updateMessageWithAudit")
        seg = msgs[i:i + 2500]
        self.assertTrue(
            "spirit_score" in seg and "ledger" in seg,
            "updateMessageWithAudit must still gate its repaint on an audit key; "
            "without it any partial update resets the outcome ring to grey",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
