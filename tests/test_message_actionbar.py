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
        for sel in (".msg-actionbar", ".dark .msg-actionbar"):
            self.assertNotIn("#f9f9f9", _block(sel) or "")

    def test_the_buttons_keep_their_hover_affordance(self):
        self.assertRegex(CSS, r"\.overflow-btn:hover")


class RedoOnTheAnswer(unittest.TestCase):

    def test_the_renderer_builds_it_only_when_a_handler_is_supplied(self):
        self.assertIn("if (onRedo)", MSGS)
        self.assertIn("() => onRedo()", MSGS)
        self.assertIn("onRedo: options.onRedo", MSGS)

    def test_it_lives_in_the_overflow_menu(self):
        self.assertIn("_createOverflowControl", MSGS)
        self.assertIn("Retry — ask again", MSGS)
        self.assertIn("if (overflowCtrl) bar.appendChild(overflowCtrl)", MSGS)

    def test_the_live_turn_redoes_the_clean_prompt(self):
        self.assertIn("onRedo: () => retryHandler(userMessage)", CHAT)

    def test_replayed_history_redoes_the_stripped_prompt(self):
        self.assertIn("_lastReplayedUserPrompt = displayContent", CHAT)
        self.assertIn("options.onRedo = () => resend(promptForRedo)", CHAT)
        set_at = CHAT.index("_lastReplayedUserPrompt = displayContent")
        strip_at = CHAT.index("_stripDocumentContext(turn.content)")
        self.assertGreater(set_at, strip_at)

    def test_redo_is_labelled_as_ask_again_not_replace(self):
        self.assertIn("ask again", MSGS.lower())

    def test_accessible_name_exists(self):
        self.assertIn("Retry — ask again", MSGS)
        self.assertIn("'aria-label', 'More actions'", MSGS)


class CopyOnThePrompt(unittest.TestCase):

    def test_it_is_unconditional(self):
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
        m = re.search(r"copyPromptBtn\.className = '([^']+)'", MSGS)
        self.assertIsNotNone(m)
        self.assertIn("text-white", m.group(1))

    def test_feedback_on_copy(self):
        block = MSGS[MSGS.index("copyPromptBtn.onclick"):]
        self.assertIn("iconCheck", block[:400])
        self.assertIn("Prompt copied", block[:400])


if __name__ == "__main__":
    unittest.main(verbosity=2)
