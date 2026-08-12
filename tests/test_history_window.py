"""
The verbatim conversation window: how deep it goes, and what bounds it.

WHY IT IS TWO NUMBERS AND NOT ONE. Depth was hardcoded to three user/assistant
pairs. Some agents need the whole thread, so depth is configurable — but a turn
count alone would have been the wrong knob, because the window is sent to the
Intellect *and* fenced into the Conscience's audit material, and the Conscience
has no context budget of any kind. Uncapped, a thread carrying one 50k-char
attachment re-sends it on every later turn, twice: cost grows with the square of
the conversation. So depth is bounded by characters as well.

WHY THE DROP IS ANNOUNCED. An agent whose history was quietly clipped
contradicts something it was told earlier with complete confidence, and neither
the reader nor the audit record can distinguish that from ordinary forgetting.
The note is what makes "was not shown it" separable from "ignored it".

Run:  venv/bin/python tests/test_history_window.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core.orchestrator import _render_history, _HISTORY_FETCH_ALL  # noqa: E402

ORCH = (ROOT / "safi_app" / "core" / "orchestrator.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "safi_app" / "config.py").read_text(encoding="utf-8")


def msgs(n, size=10, prefix="m"):
    """n alternating messages, oldest first, each `size` chars of body."""
    out = []
    for i in range(n):
        out.append({"role": "user" if i % 2 == 0 else "assistant",
                    "content": f"{prefix}{i}" + "x" * max(0, size - len(f"{prefix}{i}"))})
    return out


class Rendering(unittest.TestCase):

    def test_empty_history_renders_as_empty_string(self):
        self.assertEqual(_render_history([], 1000), "")

    def test_roles_are_labelled(self):
        out = _render_history(msgs(2), 1000)
        self.assertTrue(out.startswith("User: "))
        self.assertIn("\nAssistant: ", out)

    def test_order_is_preserved_oldest_first(self):
        out = _render_history(msgs(4, prefix="turn"), 10_000)
        positions = [out.index(f"turn{i}") for i in range(4)]
        self.assertEqual(positions, sorted(positions))

    def test_a_budget_of_zero_means_unbounded(self):
        """0 is 'no character cap', matching HISTORY_TURNS where 0 means 'no turn
        cap'. Both knobs read the same way."""
        out = _render_history(msgs(50, size=100), 0)
        self.assertNotIn("EARLIER HISTORY OMITTED", out)
        self.assertIn("m49", out)


class TheCharacterBudget(unittest.TestCase):

    def test_under_budget_is_untouched(self):
        out = _render_history(msgs(4, size=10), 10_000)
        self.assertNotIn("EARLIER HISTORY OMITTED", out)

    def test_over_budget_drops_the_oldest_and_keeps_the_newest(self):
        out = _render_history(msgs(20, size=100), 500)
        self.assertIn("EARLIER HISTORY OMITTED", out)
        self.assertIn("m19", out, "the most recent exchange must survive")
        self.assertNotIn("m0", out, "the oldest should have been dropped first")

    def test_the_note_counts_what_was_dropped(self):
        out = _render_history(msgs(20, size=100), 500)
        self.assertRegex(out, r"OMITTED: \d+ of 20 prior messages")

    def test_the_note_warns_against_assuming_a_topic_was_never_raised(self):
        """The whole point of announcing it."""
        out = _render_history(msgs(20, size=100), 500)
        self.assertIn("NOT the start of the conversation", out)

    def test_messages_are_dropped_whole_never_cut_mid_message(self):
        """A severed turn invites the model to finish the thought itself — the
        same reason _apply_context_budget keeps whole retrieved passages."""
        body = "y" * 300
        history = [{"role": "user", "content": body}, {"role": "assistant", "content": body}]
        out = _render_history(history, 320)
        for line in out.splitlines():
            if line.startswith(("User: ", "Assistant: ")):
                self.assertEqual(len(line.split(": ", 1)[1]), 300,
                                 "a message was truncated mid-content")

    def test_at_least_one_message_survives_an_impossible_budget(self):
        """Better to overrun the budget than to send a bare note with no content
        and let the model answer from nothing."""
        out = _render_history(msgs(3, size=500), 10)
        self.assertIn("m2", out)


class ConfigSurface(unittest.TestCase):

    def test_both_settings_exist_with_env_overrides(self):
        self.assertIn('os.environ.get("SAFI_HISTORY_TURNS"', CONFIG)
        self.assertIn('os.environ.get("SAFI_HISTORY_MAX_CHARS"', CONFIG)

    def test_the_default_depth_is_three_pairs(self):
        """Preserves the behaviour that was hardcoded; this is a new knob, not a
        new default."""
        self.assertRegex(CONFIG, r'SAFI_HISTORY_TURNS",\s*"3"')

    def test_all_is_accepted_as_a_word(self):
        """"all" is what a human writes in a config field; 0 is what the code
        wants."""
        self.assertIn('"all", "unlimited", "-1"', CONFIG)

    def test_unlimited_still_bounds_the_database_read(self):
        """'every prior turn' should not become an unbounded query on a thread
        that has run for months."""
        self.assertGreater(_HISTORY_FETCH_ALL, 100)
        self.assertIn("_HISTORY_FETCH_ALL if turns == 0", ORCH)


class PerAgentOverride(unittest.TestCase):

    def test_the_resolver_prefers_the_persona_over_the_deployment_default(self):
        """"Some agents need full memory" is a fact about the agent, not the
        install."""
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn('prof.get("history_turns"', block)
        self.assertIn('prof.get("history_max_chars"', block)
        self.assertIn("HISTORY_TURNS", block)

    def test_a_bad_value_falls_back_instead_of_raising(self):
        """A typo in one agent's persona must not take that agent off the air."""
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn("except (TypeError, ValueError)", block)
        self.assertIn("log.warning", block)

    def test_negative_depth_cannot_become_a_slice_bug(self):
        """max(0, ...) — a negative turn count would slice from the wrong end and
        silently return the OLDEST turns instead of the newest."""
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn("max(0, int(raw))", block)

    def test_the_window_is_applied_only_when_a_depth_is_set(self):
        """`if turns:` — slicing by [-0:] would return the whole list, which is
        the opposite of what 0 means here for the DB limit."""
        self.assertIn("if turns:\n            recent_window = recent_window[-(turns * 2):]", ORCH)


class NothingElseChanged(unittest.TestCase):

    def test_the_current_user_message_is_still_dropped(self):
        """It is the prompt; replaying it as history duplicates it."""
        self.assertIn("recent_window = prior_turns[:-1]", ORCH)

    def test_the_hardcoded_three_pair_slice_is_gone(self):
        self.assertNotIn("[-6:]", ORCH)
        self.assertNotIn("limit=8", ORCH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
