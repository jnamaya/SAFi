"""Tests for turn_loop: resume-budget loop, step-ceiling fallback, subagent role filtering."""

import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from safi_cli import ui
from safi_cli.client import SafiClient
from safi_cli.subagents import run_subagent_task
from safi_cli.turn_loop import run_agent_turn


def _tool_call(name, args=None):
    return {"type": "tool_call", "tool_name": name, "parameters": args or {}}


def _final(text):
    return {"type": "final", "finalOutput": text, "willDecision": "approve"}


class TurnLoopTestBase(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=SafiClient)
        self.client.get_turn_progress.return_value = {}
        for mod in ("print_user_prompt", "print_final_output", "print_tool_proposal",
                    "print_tool_result_summary", "print_subagent_start",
                    "print_subagent_step", "print_subagent_done", "print_error"):
            patcher = patch.object(ui, mod)
            patcher.start()
            self.addCleanup(patcher.stop)
        ui.clear_active_todos()


class TestResumeBudget(TurnLoopTestBase):
    def test_unfinished_todos_force_continuation_then_finish(self):
        # Step 0: final with pending todos -> harness_note appended, loop continues.
        # Step 1: todos completed -> final returned.
        ui.set_active_todos([{"task": "Step A", "status": "in_progress"}])
        self.client.send_turn.side_effect = [
            _final("Mid-task status note."),
            _final("All done."),
        ]
        with patch.object(ui, "get_active_todos", side_effect=[
            [{"task": "Step A", "status": "in_progress"}],
            [],
        ]):
            res = run_agent_turn(
                client=self.client, prompt="do work",
                workspace_root=Path("/tmp"), conversation_id="c1",
                user_id="u1", agent="software_engineer", auto_approve=True,
            )
        self.assertEqual(res["finalOutput"], "All done.")
        # Second send_turn must carry the harness_note continuation.
        second_kwargs = self.client.send_turn.call_args_list[1].kwargs
        harness_notes = [tr for tr in second_kwargs["tool_results"]
                         if tr["tool_name"] == "harness_note"]
        self.assertEqual(len(harness_notes), 1)
        self.assertIn("unfinished steps", harness_notes[0]["result"])

    def test_resume_budget_exhausts_after_repeats(self):
        # Budget starts at 3: the first 3 mid-task finals each trigger one
        # continuation; the 4th final is accepted even though todos are
        # still pending, so the loop terminates deterministically.
        self.client.send_turn.side_effect = [_final(f"note {i}") for i in range(4)]
        with patch.object(ui, "get_active_todos",
                          return_value=[{"task": "T", "status": "pending"}]):
            res = run_agent_turn(
                client=self.client, prompt="p", workspace_root=Path("/tmp"),
                conversation_id="c1", user_id="u1", agent="software_engineer",
                auto_approve=True, max_steps=10,
            )
        self.assertEqual(res["finalOutput"], "note 3")
        self.assertEqual(self.client.send_turn.call_count, 4)
        # Exactly three continuation harness notes were injected (one per
        # budgeted resume); later calls re-send all earlier notes, so count
        # distinct notes via the final call's accumulated tool_results.
        final_trs = self.client.send_turn.call_args_list[-1].kwargs["tool_results"]
        harness = [t for t in final_trs if t["tool_name"] == "harness_note"]
        self.assertEqual(len(harness), 3)

    def test_intercepted_will_decision_not_continued(self):
        # An intercepted (refused) turn must NOT trigger resume continuation.
        ui.set_active_todos([{"task": "T", "status": "pending"}])
        res_refused = {"type": "final", "finalOutput": "no",
                       "willDecision": "refuse"}
        self.client.send_turn.return_value = res_refused
        res = run_agent_turn(
            client=self.client, prompt="p", workspace_root=Path("/tmp"),
            conversation_id="c1", user_id="u1", agent="software_engineer",
            auto_approve=True,
        )
        self.assertEqual(res["willDecision"], "refuse")
        self.assertEqual(self.client.send_turn.call_count, 1)


class TestStepCeiling(TurnLoopTestBase):
    def test_ceiling_appends_summary_harness_note_and_gets_final(self):
        # max_steps tool calls, then a final summary call with tools=[].
        calls = []

        def fake_send_turn(**kwargs):
            calls.append(kwargs)
            if len(calls) <= 3:
                return _tool_call("read", {"path": "a.py"})
            return _final("Summary of partial work.")

        self.client.send_turn.side_effect = fake_send_turn
        with patch.object(ui, "print_tool_result_summary"):
            res = run_agent_turn(
                client=self.client, prompt="p", workspace_root=Path("/tmp"),
                conversation_id="c1", user_id="u1", agent="software_engineer",
                auto_approve=True, max_steps=3,
            )
        self.assertEqual(res["finalOutput"], "Summary of partial work.")
        last_call = calls[-1]
        ceiling_notes = [tr for tr in last_call["tool_results"]
                         if tr["tool_name"] == "harness_note"]
        self.assertEqual(len(ceiling_notes), 1)
        self.assertIn("step ceiling", ceiling_notes[0]["result"])
        self.assertEqual(last_call["tools"], [])

    def test_ceiling_without_tool_results_errors(self):
        self.client.send_turn.return_value = _tool_call("noop")  # never final
        with patch("safi_cli.tools.execute_tool", return_value="ok"):
            res = run_agent_turn(
                client=self.client, prompt="p", workspace_root=Path("/tmp"),
                conversation_id="c1", user_id="u1", agent="software_engineer",
                auto_approve=True, max_steps=1,
            )
        # With max_steps=1 the fallback send never runs; loop returns None via error.
        self.assertTrue(res is None or res.get("finalOutput"))


class TestSubagentToolFiltering(TurnLoopTestBase):
    def _run_subagent(self, proposals):
        self.client.send_turn.side_effect = (
            [{"type": "tool_call", "tool_calls": proposals}, _final("done")]
        )
        return run_subagent_task(
            client=self.client,
            args={"description": "d", "prompt": "p", "subagent_type": "researcher"},
            workspace_root=Path("/tmp"), parent_conv_id="conv-1", user_id="u1",
            max_steps=2,
        )

    def test_child_tools_restricted_to_role(self):
        with patch("safi_cli.subagents._execute_tool_with_live_status",
                   return_value="out") as mock_exec:
            self._run_subagent([_tool_call("read", {"path": "x"})])
            sent_tools = self.client.send_turn.call_args_list[0].kwargs["tools"]
            names = {t["function"]["name"] for t in sent_tools}
            self.assertTrue(names)
            self.assertNotIn("write", names)
            self.assertNotIn("edit", names)
            self.assertNotIn("bash", names)
            mock_exec.assert_called_once()

    def test_out_of_role_proposal_blocked_not_executed(self):
        with patch("safi_cli.subagents._execute_tool_with_live_status") as mock_exec:
            self._run_subagent([_tool_call("write", {"path": "x", "content": "y"})])
            mock_exec.assert_not_called()
            first_kwargs = self.client.send_turn.call_args_list[0].kwargs
            # Blocked tool call recorded as a result for the server.
            tr = first_kwargs["tool_results"]  # populated only on next call
        # The blocked entry appears in the continuation turn's tool_results.
        second_kwargs = self.client.send_turn.call_args_list[1].kwargs
        blocked = [t for t in second_kwargs["tool_results"] if t["tool_name"] == "write"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("restricted", blocked[0]["result"])


if __name__ == "__main__":
    unittest.main()
