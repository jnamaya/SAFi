import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core.orchestrator import _render_history, _HISTORY_FETCH_ALL

ORCH = (ROOT / "safi_app" / "core" / "orchestrator.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "safi_app" / "config.py").read_text(encoding="utf-8")


def msgs(n, size=10, prefix="m"):
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
        out = _render_history(msgs(20, size=100), 500)
        self.assertIn("NOT the start of the conversation", out)

    def test_messages_are_dropped_whole_never_cut_mid_message(self):
        body = "y" * 300
        history = [{"role": "user", "content": body}, {"role": "assistant", "content": body}]
        out = _render_history(history, 320)
        for line in out.splitlines():
            if line.startswith(("User: ", "Assistant: ")):
                self.assertEqual(len(line.split(": ", 1)[1]), 300,
                                 "a message was truncated mid-content")

    def test_at_least_one_message_survives_an_impossible_budget(self):
        out = _render_history(msgs(3, size=500), 10)
        self.assertIn("m2", out)


class ConfigSurface(unittest.TestCase):

    def test_both_settings_exist_with_env_overrides(self):
        self.assertIn('os.environ.get("SAFI_HISTORY_TURNS"', CONFIG)
        self.assertIn('os.environ.get("SAFI_HISTORY_MAX_CHARS"', CONFIG)

    def test_the_default_depth_is_three_pairs(self):
        self.assertRegex(CONFIG, r'SAFI_HISTORY_TURNS",\s*"3"')

    def test_all_is_accepted_as_a_word(self):
        self.assertIn('"all", "unlimited", "-1"', CONFIG)

    def test_unlimited_still_bounds_the_database_read(self):
        self.assertGreater(_HISTORY_FETCH_ALL, 100)
        self.assertIn("_HISTORY_FETCH_ALL if turns == 0", ORCH)


class PerAgentOverride(unittest.TestCase):

    def test_the_resolver_prefers_the_agent_over_the_deployment_default(self):
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn('prof.get("history_turns"', block)
        self.assertIn('prof.get("history_max_chars"', block)
        self.assertIn("HISTORY_TURNS", block)

    def test_a_bad_value_falls_back_instead_of_raising(self):
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn("except (TypeError, ValueError)", block)
        self.assertIn("log.warning", block)

    def test_negative_depth_cannot_become_a_slice_bug(self):
        block = ORCH[ORCH.index("def _resolve_history_window"):]
        block = block[:block.index("\n    def _is_cancelled")]
        self.assertIn("max(0, int(raw))", block)

    def test_the_window_is_applied_only_when_a_depth_is_set(self):
        self.assertIn("if turns:\n            recent_window = recent_window[-(turns * 2):]", ORCH)


class NothingElseChanged(unittest.TestCase):

    def test_the_current_user_message_is_still_dropped(self):
        self.assertIn("recent_window = prior_turns[:-1]", ORCH)

    def test_the_hardcoded_three_pair_slice_is_gone(self):
        self.assertNotIn("[-6:]", ORCH)
        self.assertNotIn("limit=8", ORCH)


class ClientOwnedHistoryCleaning(unittest.TestCase):

    def test_drops_intermediate_tool_call_hops_and_strips_envelopes(self):
        from safi_app.core.orchestrator import _clean_client_owned_history

        raw = [
            {
                "role": "user",
                "content": (
                    "[Client workspace metadata]\nClient working directory: /repo\n[/Client workspace metadata]\n\n"
                    "Implement feature X"
                ),
            },
            {"role": "ai", "content": "[tool_calls] read, read"},
            {
                "role": "user",
                "content": (
                    "[ACTIVE WORKSPACE SCRATCHPAD (.safi/scratchpad.md)]\n- [ ] Step 1\n[/ACTIVE WORKSPACE SCRATCHPAD]\n\n"
                    "[Client workspace metadata]\nClient working directory: /repo\n[/Client workspace metadata]\n\n"
                    "Implement feature X\n\nTOOL RESULT — read called with {'path': 'a.py'}\n" + ("A" * 20000)
                ),
            },
            {"role": "ai", "content": "[tool_call] edit({'path': 'a.py'})"},
            {
                "role": "user",
                "content": (
                    "[Client workspace metadata]\nClient working directory: /repo\n[/Client workspace metadata]\n\n"
                    "Implement feature X\n\nTOOL RESULT — edit called with {'path': 'a.py'}\nSuccessfully edited."
                ),
            },
            {"role": "ai", "content": "Feature X has been implemented and verified."},
        ]
        cleaned = _clean_client_owned_history(raw)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["role"], "user")
        self.assertEqual(cleaned[0]["content"], "Implement feature X")
        self.assertEqual(cleaned[1]["role"], "ai")
        self.assertEqual(cleaned[1]["content"], "Feature X has been implemented and verified.")

    def test_in_flight_first_turn_returns_empty_history(self):
        from safi_app.core.orchestrator import _clean_client_owned_history

        raw = [
            {"role": "user", "content": "Implement feature X"},
            {"role": "ai", "content": "[tool_calls] read, read"},
            {"role": "user", "content": "Implement feature X\n\nTOOL RESULT — read called with {}\nbody"},
            {"role": "ai", "content": "[tool_calls] bash, bash"},
        ]
        self.assertEqual(_clean_client_owned_history(raw), [])

    def test_strips_tail_appended_scratchpad_and_task_state(self):
        from safi_app.core.orchestrator import _strip_harness_envelope

        msg = (
            "[Client workspace metadata]\nClient working directory: /repo\n[/Client workspace metadata]\n\n"
            "Generate security report\n\n"
            "[ACTIVE WORKSPACE SCRATCHPAD (.safi/scratchpad.md)]\n- [x] Done\n[/ACTIVE WORKSPACE SCRATCHPAD]\n\n"
            "[TASK STATE — mid-task progress reminder, not a new user message]\nOriginal request: Generate security report"
        )
        self.assertEqual(_strip_harness_envelope(msg), "Generate security report")


if __name__ == "__main__":
    unittest.main(verbosity=2)
