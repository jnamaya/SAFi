"""
The message meta bar: flat on the canvas, redo on the answer, copy on the prompt.

WHY. Three requests from 2026-08-13, pinned so they survive the next restyle:

FLAT, NOT A PILL. The AI bubble is transparent over the canvas (--ai-bg), so the
action bar's rgba tint + border made it the one piece of chrome floating on the
reading surface. "Same color as the canvas" is implemented as TRANSPARENT, not a
hardcoded canvas hex — it stays correct if the canvas color ever changes, in
either theme. The buttons keep their own hover states, so affordance survives.

REDO IS "ASK AGAIN", NEVER "REPLACE". A governed answer's audit record stays on
the trail; redo produces a NEW turn with a new record. The renderer receives a
callback because regenerating means re-entering sendMessage with the PRECEDING
user prompt — which the renderer doesn't know. Both suppliers (live send and
history replay) must pass the clean/stripped prompt so a redo never re-injects a
stale document-context block.

COPY-PROMPT IS UNCONDITIONAL AND COPIES RAW TEXT. Unlike retry it needs no send
machinery, and unlike the AI copy it needs no server id — so it must not be
gated on either. It copies what was typed, not rendered HTML.

Run:  docker compose -f docker-compose.test.yml run --rm tests -k actionbar
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CSS = (ROOT / "public" / "css" / "styles.css").read_text(encoding="utf-8")
MSGS = (ROOT / "public" / "js" / "ui" / "ui-messages.js").read_text(encoding="utf-8")
CHAT = (ROOT / "public" / "js" / "core" / "chat.js").read_text(encoding="utf-8")


def _block(selector):
    """First rule block for a selector, comments stripped."""
    src = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    i = src.find(selector + " {")
    if i == -1:
        return None
    return src[src.index("{", i) + 1:src.index("}", i)]


class TheBarIsFlatOnTheCanvas(unittest.TestCase):

    def test_no_resting_background_in_light_mode(self):
        b = _block(".msg-actionbar")
        self.assertIsNotNone(b)
        self.assertIn("background: transparent", b)
        self.assertNotIn("rgba", b.split("border-radius")[0].replace(" ", "")
                         .replace("background:transparent", ""),
                         "a tinted resting background is the pill this removed")

    def test_no_resting_background_in_dark_mode(self):
        b = _block(".dark .msg-actionbar")
        self.assertIsNotNone(b)
        self.assertIn("background: transparent", b)
        self.assertNotIn("rgba(255", b)

    def test_transparent_not_a_hardcoded_canvas_color(self):
        """#f9f9f9 here would match the canvas today and diverge the day the
        canvas changes. Transparent IS the canvas color, permanently."""
        for sel in (".msg-actionbar", ".dark .msg-actionbar"):
            self.assertNotIn("#f9f9f9", _block(sel) or "")

    def test_the_buttons_keep_their_hover_affordance(self):
        """Removing the resting chrome is fine only because hover still shows
        the buttons are buttons."""
        self.assertRegex(CSS, r"\.redo-btn:hover")


class RedoOnTheAnswer(unittest.TestCase):

    def test_the_renderer_builds_it_only_when_a_handler_is_supplied(self):
        self.assertIn("if (options.onRedo)", MSGS)
        self.assertIn("redoBtn.onclick = () => options.onRedo()", MSGS)

    def test_it_sits_in_the_action_bar_and_is_sized_like_its_neighbours(self):
        self.assertIn("if (redoBtn) bar.appendChild(redoBtn)", MSGS)
        self.assertRegex(CSS, r"\.msg-actionbar \.redo-btn")

    def test_the_live_turn_redoes_the_clean_prompt(self):
        """userMessage is the typed text; the outgoing prompt may carry an
        appended document-context block that must not be re-sent verbatim."""
        self.assertIn("onRedo: () => retryHandler(userMessage)", CHAT)

    def test_replayed_history_redoes_the_stripped_prompt(self):
        """The replay walks turns in order; each AI turn re-asks the most
        recent USER prompt, in its document-context-stripped form."""
        self.assertIn("_lastReplayedUserPrompt = displayContent", CHAT)
        self.assertIn("options.onRedo = () => resend(promptForRedo)", CHAT)
        # set on the stripped variable, which is only assigned for user turns
        set_at = CHAT.index("_lastReplayedUserPrompt = displayContent")
        strip_at = CHAT.index("_stripDocumentContext(turn.content)")
        self.assertGreater(set_at, strip_at)

    def test_redo_is_labelled_as_ask_again_not_replace(self):
        """The wording is load-bearing: a redo that read as 'replace' would
        imply the audited answer can be swapped out from under its record."""
        self.assertIn("ask this again", MSGS.lower())

    def test_accessible_name_exists(self):
        self.assertIn("redoBtn.setAttribute('aria-label'", MSGS)


class CopyOnThePrompt(unittest.TestCase):

    def test_it_is_unconditional(self):
        """Retry is gated on options.onRetry (send machinery); AI copy/save are
        gated on server ids. Copying a prompt needs neither, so it must not sit
        inside either gate."""
        user_branch = MSGS[MSGS.index("// User message: copy + optional retry"):]
        user_branch = user_branch[:user_branch.index("metaDiv.appendChild(rightMeta)")]
        self.assertIn("copyPromptBtn", user_branch)
        create_at = user_branch.index("document.createElement('button')")
        self.assertNotIn("if (", user_branch[:create_at],
                         "the copy-prompt button must not be conditional")

    def test_it_copies_the_raw_text_not_rendered_html(self):
        self.assertIn("const raw = typeof text === 'string' ? text : final_text_raw", MSGS)
        block = MSGS[MSGS.index("copyPromptBtn.onclick"):]
        self.assertIn("writeText(raw)", block[:300])

    def test_it_is_styled_for_the_green_bubble(self):
        """White-on-green: the AI bar's grey icons would vanish here."""
        m = re.search(r"copyPromptBtn\.className = '([^']+)'", MSGS)
        self.assertIsNotNone(m)
        self.assertIn("text-white", m.group(1))

    def test_feedback_on_copy(self):
        block = MSGS[MSGS.index("copyPromptBtn.onclick"):]
        self.assertIn("iconCheck", block[:400])
        self.assertIn("Prompt copied", block[:400])


if __name__ == "__main__":
    unittest.main(verbosity=2)
