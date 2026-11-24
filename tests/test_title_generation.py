import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator_mixins.tasks import BackgroundTasksMixin

clean = BackgroundTasksMixin._clean_title
THREAD = inspect.getsource(BackgroundTasksMixin._run_title_thread)
ORCH = (Path(__file__).resolve().parent.parent / "safi_app" / "core" / "orchestrator.py").read_text(
    encoding="utf-8")


class CleaningDegradesToTheFallback(unittest.TestCase):

    def test_plain_title_passes(self):
        self.assertEqual(clean("PTO Policy Question"), "PTO Policy Question")

    def test_wrapping_quotes_are_stripped(self):
        for raw in ('"PTO Policy Question"', "'PTO Policy Question'",
                    "“PTO Policy Question”"):
            self.assertEqual(clean(raw), "PTO Policy Question")

    def test_title_prefix_is_stripped(self):
        self.assertEqual(clean("Title: PTO Policy Question"), "PTO Policy Question")

    def test_trailing_period_goes_question_mark_stays(self):
        self.assertEqual(clean("PTO Policy Question."), "PTO Policy Question")
        self.assertEqual(clean("What Counts As PTO?"), "What Counts As PTO?")

    def test_only_the_first_line_is_used(self):
        self.assertEqual(clean("PTO Policy Question\nHere is why I chose it..."),
                         "PTO Policy Question")

    def test_a_chatting_model_is_rejected_not_displayed(self):
        self.assertIsNone(clean(
            "I'm sorry, but as an AI language model I cannot generate a title "
            "for this conversation without more context about it."))

    def test_empty_and_quote_only_yield_none(self):
        for raw in (None, "", "   ", '""', "'.'"):
            self.assertIsNone(clean(raw), f"expected None for {raw!r}")


class ARenameIsNeverOverwritten(unittest.TestCase):

    def test_the_thread_rereads_before_writing(self):
        self.assertIn("db.get_conversation_title(conversation_id)", THREAD)
        self.assertIn("current != initial_title", THREAD)
        self.assertLess(THREAD.index("get_conversation_title"),
                        THREAD.index("db.rename_conversation"),
                        "the guard must run before the write, not after")

    def test_failures_are_swallowed(self):
        self.assertIn("except Exception", THREAD)

    def test_an_unchanged_title_writes_nothing(self):
        self.assertIn("title == initial_title", THREAD)


class ItFiresOncePerConversation(unittest.TestCase):

    def test_both_first_turn_paths_dispatch(self):
        self.assertEqual(ORCH.count("_run_title_thread"), 2)

    def test_gated_on_new_title(self):
        for i in range(2):
            at = ORCH.index("_run_title_thread",
                            0 if i == 0 else ORCH.index("_run_title_thread") + 1)
            window = ORCH[max(0, at - 400):at]
            self.assertIn("if new_title:", window)

    def test_it_is_off_the_request_path(self):
        at = ORCH.index("_run_title_thread")
        self.assertIn("_submit_bg", ORCH[at - 60:at])


if __name__ == "__main__":
    unittest.main(verbosity=2)
