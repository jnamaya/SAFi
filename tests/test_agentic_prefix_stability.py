#!/usr/bin/env python3
"""Regression tests for KV-cache prefix stability in the agentic loop.

The tool catalogue lives at the very start of the system prompt. If any part of
the system prompt varies between the steps of a single governed turn, the
llama-server discards its KV cache and re-evaluates the whole prompt on every
step (observed: a ~9.5k-token prompt re-evaluated at ~9.3s with LCP similarity
0.357). The fix keeps the system prompt byte-identical and moves the per-step
"results are already present" reminder into the appended USER turn.

These tests assert the invariant directly on the prompts handed to the provider.
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.intellect import IntellectEngine


class _CapturingLLM:
    """Stands in for LLMProvider, recording the prompts it is asked to run."""

    def __init__(self):
        self.calls = []

    async def run_intellect(self, *, system_prompt, user_prompt, context_for_audit, tools=None):
        self.calls.append({"system": system_prompt, "user": user_prompt, "tools": tools})
        return ("Answer.", "reflection", "ctx", None)


def _engine(tools):
    engine = IntellectEngine.__new__(IntellectEngine)
    engine.profile = {"worldview": "You are a coding agent.", "style": ""}
    engine.prompt_config = {}
    engine.retriever = None
    engine.mcp_manager = None
    engine.max_context_chars = 0
    engine.last_error = None
    engine.log = __import__("logging").getLogger("test.prefix")
    engine.llm_provider = _CapturingLLM()
    engine._tools = tools
    return engine


class PrefixStabilityTests(unittest.TestCase):

    def _run(self, tool_results_supplied, recent_turns=""):
        tools = [
            {"name": "read", "description": "Read a file."},
            {"name": "grep", "description": "Search text."},
        ]
        engine = _engine(tools)
        asyncio.run(engine.generate(
            user_prompt="USER QUERY: do it",
            memory_summary="",
            recent_turns=recent_turns,
            user_profile_json="{}",
            tools_override=tools,
            tool_results_supplied=tool_results_supplied,
        ))
        return engine.llm_provider.calls[-1]

    def test_system_prompt_is_byte_identical_across_steps(self):
        first = self._run(0)
        follow_up = self._run(3)
        self.assertEqual(first["system"], follow_up["system"])

    def test_recent_history_does_not_touch_the_system_prompt(self):
        without = self._run(0, recent_turns="")
        with_history = self._run(0, recent_turns="USER: hi\nASSISTANT: hello")
        self.assertEqual(without["system"], with_history["system"])
        self.assertNotIn("RECENT CONVERSATION", with_history["system"])

    def test_recent_history_rides_the_user_turn(self):
        with_history = self._run(0, recent_turns="USER: hi\nASSISTANT: hello")
        self.assertIn("RECENT CONVERSATION", with_history["user"])
        self.assertIn("USER: hi", with_history["user"])

    def test_catalogue_does_not_embed_the_result_count(self):
        system = self._run(3)["system"]
        self.assertNotIn("3 result(s)", system)

    def test_results_reminder_rides_the_user_turn(self):
        first = self._run(0)
        follow_up = self._run(3)
        self.assertNotIn("SYSTEM NOTE", first["user"])
        self.assertIn("SYSTEM NOTE", follow_up["user"])
        self.assertIn("3 tool result(s)", follow_up["user"])

    def test_user_turn_is_otherwise_append_only(self):
        first = self._run(0)
        follow_up = self._run(3)
        self.assertTrue(follow_up["user"].startswith(first["user"]))


if __name__ == "__main__":
    unittest.main()
