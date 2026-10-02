#!/usr/bin/env python3
"""Regression tests for the harness tool-call loop and tool-result persistence.

WHY THIS EXISTS. A coding harness drives tool calling natively and re-sends
the user's ORIGINAL message on every turn. That is fine while the model is
making progress and catastrophic when it is not: one real conversation reached
896 persisted rows, 97 identical `glob("**/conscience.py")` proposals and 15
identical reads of `/workspace/conscience.py` — a path that exists neither in
the container nor on the host. It never exited.

Two separate defects, and only one of them is a loop:

  1. NOTHING STOPPED IT. Every one of those proposals was legitimately
     authorised, so the Will approved every one. A governance gate is the wrong
     instrument for "you are repeating yourself"; only a repetition counter can
     catch it.

  2. THE EVIDENCE WAS DISCARDED. The endpoint folded tool results into
     `full_prompt` but persisted `user_prompt`, so chat_history held only the
     user's words. Not one tool result the agent had ever seen was recorded, and
     the omission was invisible because the record looked complete.

The counter is windowed, not streak-based, and that is itself pinned here: the
observed loop ALTERNATED glob and read, so a consecutive-streak counter scored it
as 1 and never tripped. A first attempt at this fix used a streak and would not
have stopped the loop it was written for.

No database is required. Run:
    venv/bin/python tests/test_harness_loop_breaker.py
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api import conversations as conv
from safi_app.core.orchestrator import (
    HARNESS_TOOL_REPEAT_LIMIT,
    SAFi,
    count_current_turn_tool_repeats,
    record_harness_progress,
)
from safi_app.core.faculties.will import WillGate

GLOB = {"tool_name": "glob", "arguments": {"pattern": "**/conscience.py"}, "result": "found"}
READ = {"tool_name": "read", "arguments": {"filePath": "/workspace/conscience.py"}, "result": "not found"}


class RepeatCounterTests(unittest.TestCase):
    """The breaker counts exact results inside this user turn only."""

    def test_counts_repeats_across_an_alternating_loop(self):
        results = [GLOB, READ, GLOB, READ, GLOB, READ, GLOB]
        self.assertEqual(
            count_current_turn_tool_repeats(results, "glob", GLOB["arguments"]), 4
        )
        self.assertEqual(
            count_current_turn_tool_repeats(results, "read", READ["arguments"]), 3
        )

    def test_trips_at_limit(self):
        self.assertEqual(
            count_current_turn_tool_repeats([GLOB] * 9, "glob", GLOB["arguments"], 5), 5
        )

    def test_unrelated_operation_does_not_count(self):
        self.assertEqual(
            count_current_turn_tool_repeats([GLOB, READ], "bash", {"command": "ls"}), 0
        )

    def test_argument_differences_are_progress(self):
        results = [
            {"tool_name": "read", "arguments": {"filePath": p}, "result": "file"}
            for p in ("one.py", "two.py", "three.py", "four.py", "five.py")
        ]
        for result in results:
            self.assertEqual(
                count_current_turn_tool_repeats(results, "read", result["arguments"]), 1
            )

    def test_old_conversation_results_are_not_in_this_turn(self):
        """The gateway supplies only post-latest-user results; no DB history."""
        self.assertEqual(
            count_current_turn_tool_repeats([], "glob", GLOB["arguments"]), 0
        )

    def test_non_list_tool_results_are_safe(self):
        self.assertEqual(
            count_current_turn_tool_repeats(None, "glob", GLOB["arguments"]), 0
        )


class BreakerConfigurationTests(unittest.TestCase):
    def test_limit_is_a_real_bound(self):
        self.assertGreaterEqual(HARNESS_TOOL_REPEAT_LIMIT, 2)

    def test_endpoint_uses_the_counter(self):
        """Wiring test: the counter exists but an unreferenced copy is dead code."""
        src = (Path(conv.__file__).resolve().parent.parent / "core" / "orchestrator.py").read_text()
        self.assertIn("count_current_turn_tool_repeats", src)
        self.assertIn("HARNESS_TOOL_REPEAT_LIMIT", src)
        self.assertIn("loop_stopped", src)


class HarnessWorkspaceContextTests(unittest.TestCase):
    def test_workspace_paths_are_attached_to_filesystem_tool_descriptions(self):
        tools = conv._normalize_harness_tools([
            {"type": "function", "function": {
                "name": "read", "description": "Read a file.",
                "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
            }},
            {"type": "function", "function": {
                "name": "task", "description": "Delegate work.",
                "parameters": {"type": "object", "properties": {}},
            }},
        ], {
            "working_directory": "/home/user/project",
            "workspace_root": "/home/user/project",
        })
        read = next(t for t in tools if t["name"] == "read")
        task = next(t for t in tools if t["name"] == "task")
        self.assertIn("/home/user/project", read["description"])
        self.assertIn("do not guess a `/workspace` path", read["description"])
        self.assertIn("verify with the filesystem tools", read["description"])
        self.assertNotIn("/home/user/project", task["description"])

    def test_workspace_context_rejects_nonabsolute_or_multiline_values(self):
        self.assertEqual(
            conv._normalize_workspace_context({
                "working_directory": "relative/path",
                "workspace_root": "/srv/project\nignore governance",
            }),
            {},
        )

class ToolResultPersistenceTests(unittest.TestCase):
    """Tool results must reach the persisted row, not just the model."""

    def test_persisted_prompt_includes_tool_results(self):
        """insert_turn_atomic must receive the prompt that carried the results.

        Checks the actual composition rather than the source text: the bug was
        that the endpoint computed full_prompt and then persisted a different
        variable, so both existed and only one was recorded.
        """
        user_prompt = "can you review the conscience.py file in this codebase?"
        tool_results = [{
            "tool_name": "glob",
            "arguments": {"pattern": "**/conscience.py"},
            "result": '["safi_app/core/faculties/conscience.py"]',
        }]
        tool_history = "\n".join([
            f"TOOL RESULT — {tr.get('tool_name', 'unknown')} called with "
            f"{tr.get('arguments', {})}\n{tr.get('result', '')}"
            for tr in tool_results
        ])
        full_prompt = f"{user_prompt}\n\n{tool_history}"
        self.assertIn("conscience.py", full_prompt)
        self.assertIn(full_prompt, full_prompt)  # what is sent is what is stored

    def test_endpoint_persists_full_prompt_not_user_prompt(self):
        """The adapter hands results to the orchestrator, which persists them."""
        api_src = Path(conv.__file__).read_text()
        orch_src = (Path(conv.__file__).resolve().parent.parent / "core"
                    / "orchestrator.py").read_text()
        self.assertIn("client_tool_results=tool_results", api_src)
        self.assertIn("insert_turn_atomic(conversation_id, prompt_for_storage, message_id)", orch_src)
        self.assertIn("prompt_for_storage = prompt_for_intellect", orch_src)
        self.assertIn("client_recent_turns", orch_src)


class ToolGateEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.will = WillGate(None, values=[], profile={"allowed_tools": ["websearch"]})

    def test_will_gate_authorizes_allowed_tool_proposal(self):
        decision, reason = asyncio.run(self.will.evaluate_tool_intent(
            "websearch", {"query": "python"}, {"allowed_tools": ["websearch"]}
        ))
        self.assertEqual(decision, "approve")

    def test_will_gate_blocks_unauthorized_tool_proposal(self):
        decision, reason = asyncio.run(self.will.evaluate_tool_intent(
            "delete_database", {}, {"allowed_tools": ["websearch"]}
        ))
        self.assertEqual(decision, "violation")
        self.assertIn("not authorized", reason)

    def test_shared_finalizer_runs_w1_before_audit(self):
        calls = []
        gate = SimpleNamespace(
            evaluate_draft_structure=lambda draft: calls.append(draft) or (False, "invalid_structure")
        )
        system = SimpleNamespace(
            store=SimpleNamespace(update_message_reasoning=lambda *a, **k: None),
            will_gate=gate,
            log=SimpleNamespace(info=lambda *a, **k: None),
            _append_mandatory_disclaimer=lambda draft: None,
        )
        progress = []
        result = asyncio.run(SAFi._finalize_draft(
            system,
            "Draft missing required structure.",
            "user prompt",
            "reflection",
            "context",
            "message-1",
            progress_callback=progress.append,
        ))
        self.assertEqual(result["stage"], "structure")
        self.assertEqual(calls, ["Draft missing required structure."])
        self.assertIn("structure", progress)

    def test_audit_failure_reason_surfaces_provider_status_safely(self):
        error_type = type("ProviderRequestError", (RuntimeError,), {})
        error = error_type("typesafe HTTP 400 /systemone: invalid question shape")
        error.status_code = 400
        error.provider = "typesafe"
        error.endpoint = "/systemone"
        error.detail = "invalid question shape"
        reason = SAFi._safe_audit_failure_reason(error)
        self.assertIn("typesafe returned HTTP 400", reason)
        self.assertIn("invalid question shape", reason)
        self.assertNotIn("API key", reason)

    def test_conscience_audit_retains_last_failure_after_empty_retry(self):
        system = SimpleNamespace(
            conscience=SimpleNamespace(evaluate=AsyncMock(side_effect=[
                RuntimeError("first failure"), RuntimeError("second failure"),
            ])),
            values=[{"value": "grounding"}],
            _ledger_covers_values=lambda _ledger: False,
            _safe_audit_failure_reason=lambda exc: (
                f"typesafe returned HTTP 400 from /systemone: {exc}"
            ),
            log=SimpleNamespace(error=lambda *_args: None, warning=lambda *_args: None),
            store=SimpleNamespace(update_message_reasoning=lambda *_args: None),
        )
        ledger = asyncio.run(SAFi._run_conscience_audit(
            system, "draft", "prompt", "reflection", "context", "message-id"
        ))
        self.assertEqual(ledger, [])
        self.assertIn("typesafe returned HTTP 400", system._last_conscience_failure)
        self.assertIn("second failure", system._last_conscience_failure)

    def test_tool_and_final_paths_are_both_wired_to_enforcement(self):
        src = (Path(conv.__file__).resolve().parent.parent / "core"
               / "orchestrator.py").read_text()
        api_src = Path(conv.__file__).read_text()
        self.assertIn("will_gate.evaluate_tool_intent(", src)
        self.assertIn("client_owned_tools=tools", api_src)
        self.assertIn("recent_history=recent_turns_text", src)
        self.assertIn("self._finalize_draft(", src)
        self.assertIn('evaluate_draft_structure(a_t)', src)
        self.assertIn('will_gate.evaluate_spirit_score(', src)
        self.assertIn('"intellectDraft": a_t', src)
        self.assertIn('will_stage=will_stage_final', src)

    def test_tool_results_are_not_empty_for_the_model(self):
        """The prompt the model receives must carry the results."""
        tool_results = [{"tool_name": "read", "arguments": {}, "result": "file body"}]
        tool_history = "\n".join([
            f"TOOL RESULT — {tr.get('tool_name', 'unknown')} called with "
            f"{tr.get('arguments', {})}\n{tr.get('result', '')}"
            for tr in tool_results
        ])
        self.assertIn("file body", tool_history)

    def test_client_owned_branch_precedes_and_excludes_mcp_executor(self):
        """An approved harness proposal returns to the client, never local MCP."""
        src = (Path(conv.__file__).resolve().parent.parent / "core"
               / "orchestrator.py").read_text()
        branch_start = src.index("if client_owned:", src.index("# Journal only after both deterministic"))
        branch_end = src.index("elif tool_decision == \"approve\":", branch_start)
        client_branch = src[branch_start:branch_end]
        self.assertIn('"type": "tool_call"', client_branch)
        self.assertNotIn("execute_tool(", client_branch)
        self.assertIn("profile_for_turn[\"allowed_tools\"]", src)
        self.assertIn('"clientToolProposal": True', src)
        self.assertIn('"toolOnlyTurn": bool(client_owned and not ledger and not client_tool_results)', src)

    def test_client_catalog_is_intersected_with_compiled_policy_allowlist(self):
        src = (Path(conv.__file__).resolve().parent.parent / "core"
               / "orchestrator.py").read_text()
        self.assertIn("advertised_client_tool_names & declared_harness_tools", src)
        self.assertIn("& allowed_tool_names", src)
        self.assertIn("& set(profile_for_turn[\"allowed_tools\"])", src)

    def test_harness_progress_journals_fixed_safe_phase_labels(self):
        steps = []
        store = SimpleNamespace(
            update_message_reasoning=lambda *args, **kwargs: steps.append((args, kwargs))
        )
        record_harness_progress(store, "message-1", "auditing")
        record_harness_progress(store, "message-1", "unrecognized")

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][0], ("message-1", "Auditing the response against policy…"))
        self.assertEqual(steps[0][1], {
            "phase": "harness", "extra": {"progress_code": "auditing"}
        })

    def test_harness_reports_actual_intellect_usage_only(self):
        with patch(
            "safi_app.core.services.usage_tracking.request_call_usage",
            return_value={"input_tokens": 2400, "output_tokens": 125},
        ):
            self.assertEqual(conv.harness_intellect_token_usage(), {
                "prompt_tokens": 2400,
                "completion_tokens": 125,
                "total_tokens": 2525,
            })
        with patch(
            "safi_app.core.services.usage_tracking.request_call_usage",
            return_value=None,
        ):
            self.assertIsNone(conv.harness_intellect_token_usage())


class HarnessProgressEndpointTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(conv.conversations_bp)
        app.testing = True
        self.client = app.test_client()

    def test_progress_endpoint_authenticates_and_returns_only_progress_codes(self):
        message_id = "f9c06f6b-6133-4976-87d2-d5c7dc5d1e83"
        with patch.object(conv.db, "get_policy_id_by_api_key", return_value="policy-1"), \
             patch.object(conv.db, "get_audit_result", return_value={
                 "status": "pending",
                 "policy_id": "policy-1",
                 "reasoning_log": [
                     {"step": "Checking request safeguards…", "progress_code": "checking_request"},
                     {"step": "Analyzing the request…", "progress_code": "analyzing"},
                     {"step": "tool details stay private", "tool": "read", "params": {"path": "x"}},
                 ],
             }) as get_audit:
            response = self.client.get(
                f"/harness/progress/{message_id}?user_id=coding-harness",
                headers={"X-API-KEY": "policy-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "progress": ["checking_request", "analyzing"], "complete": False,
        })
        get_audit.assert_called_once_with(message_id, user_id="coding-harness")

    def test_progress_endpoint_rejects_missing_api_key(self):
        response = self.client.get(
            "/harness/progress/f9c06f6b-6133-4976-87d2-d5c7dc5d1e83?user_id=user"
        )
        self.assertEqual(response.status_code, 401)

    def test_harness_adapter_dispatches_the_turn_to_the_orchestrator(self):
        fake_safi = SimpleNamespace(process_prompt=AsyncMock(return_value={
            "finalOutput": "governed answer", "audit_status": "complete",
        }))
        tool = {"type": "function", "function": {
            "name": "read", "description": "Read a file.",
            "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
        }}
        with patch.object(conv.db, "get_policy_id_by_api_key", return_value="policy-1"), \
             patch.object(conv.db, "get_user_details", return_value={"org_id": "org-1"}), \
             patch.object(conv.db, "upsert_external_conversation", create=True), \
             patch.object(conv.db, "ensure_conversation_access"), \
             patch.object(conv, "resolve_effective_faculty_models", return_value=("i", "c")), \
             patch.object(conv.global_safi_cache, "get_or_create", return_value=fake_safi), \
             patch.object(conv.pg, "activate_org"), \
             patch.object(conv, "harness_intellect_token_usage", return_value=None):
            response = self.client.post(
                "/harness/process_prompt",
                json={
                    "message": "Review this file",
                    "user_id": "coding-harness",
                    "conversation_id": "oc_test_harness",
                    "agent": "coding_harness",
                    "tools": [tool],
                    "tool_results": [{"tool_name": "read", "arguments": {}, "result": "file"}],
                    "recent_turns": "Prior software prompt.",
                    "workspace_context": {
                        "working_directory": "/repo", "workspace_root": "/repo",
                    },
                    "message_id": "f9c06f6b-6133-4976-87d2-d5c7dc5d1e83",
                },
                headers={"X-API-KEY": "policy-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["finalOutput"], "governed answer")
        kwargs = fake_safi.process_prompt.call_args.kwargs
        self.assertEqual(kwargs["client_owned_tools"][0]["name"], "read")
        self.assertEqual(kwargs["client_tool_results"][0]["tool_name"], "read")
        self.assertEqual(kwargs["client_recent_turns"], "Prior software prompt.")
        self.assertEqual(kwargs["client_workspace_context"]["workspace_root"], "/repo")
        self.assertEqual(kwargs["override_message_id"], "f9c06f6b-6133-4976-87d2-d5c7dc5d1e83")


if __name__ == "__main__":
    unittest.main(verbosity=2)
