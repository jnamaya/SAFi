"""
Tool output must reach the Conscience as evidence.

Until this was fixed, tool results went only into the Intellect's agent_history.
The Conscience received retrieved_context, which is assigned only from the RAG
path, so a turn that ran three web searches audited against an EMPTY evidence
block. The auditor then correctly scored Evidence First -1 on claims the agent
had actually retrieved, and because Claim Discipline is a hard gate in the
marketing policy the answer was blocked. Tool use and grounding enforcement were
mutually exclusive: every searched answer blocked, permanently.

The load-bearing assertions here are the two that would have caught it:
  * test_tool_result_lands_inside_the_auditors_fence — end to end, the exact
    string a tool returned appears inside <retrieved_context> in the audit prompt.
  * test_merge_precedes_finalize_draft — order in process_prompt. Merging after
    _finalize_draft would leave the audit exactly as broken while every other
    test still passed.

Run:  venv/bin/python tests/test_tool_evidence_reaches_conscience.py
"""
import asyncio
import inspect
import logging
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core import orchestrator as orch
from safi_app.core.faculties.conscience import ConscienceAuditor
from safi_app.core.faculties.intellect import _apply_context_budget, _MAX_CONTEXT_CHARS

TOOL_RESULT = '[{"title": "Introducing SAFi", "snippet": "January 27, 2026 - open source"}]'
ARGS = '{"query": "site:selfalignmentframework.com SAFi articles"}'
EVIDENCE = f"[TOOL RESULT — web_search called with {ARGS}]\n{TOOL_RESULT}"


class CapturingProvider:
    """Stands in for LLMProvider and keeps the prompts it was handed.

    run_conscience is the real entry point (conscience.py:215); capturing a
    generic get_completion would have silently recorded nothing.
    """

    def __init__(self):
        self.calls = []

    async def run_conscience(self, *, system_prompt, user_prompt):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        return []


def fence(provider, name="retrieved_context"):
    """Extract a data fence from the audit BODY.

    Scoped to the user prompt on purpose: the SYSTEM prompt's data-boundary
    instruction NAMES these tags, so searching system+user together matches an
    opening tag inside the instructions and a closing tag far away in the body.
    """
    body = "\n".join(c["user"] for c in provider.calls)
    m = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
    return m.group(1) if m else None


class TestFenceDelivery(unittest.TestCase):

    def test_tool_result_lands_inside_the_auditors_fence(self):
        provider = CapturingProvider()
        auditor = ConscienceAuditor(
            provider,
            values=[{"value": "Evidence First", "rubric": {
                "description": "d", "scoring_guide": [{"score": 1.0, "descriptor": "x"}]}}],
            profile={"worldview": "w"},
            prompt_config={"prompt_template": "{worldview_injection}{rubrics_str}",
                           "worldview_template": "{worldview}"},
        )
        asyncio.run(auditor.evaluate(
            final_output="The article was published January 27, 2026.",
            user_prompt="check the articles",
            reflection="",
            retrieved_context=EVIDENCE,
        ))
        self.assertTrue(provider.calls, "the auditor never called the provider")
        body = "\n".join(c["user"] for c in provider.calls)
        self.assertIn(TOOL_RESULT, body,
                      "the tool result never reached the audit prompt")

        ctx = fence(provider)
        self.assertIsNotNone(ctx, "no <retrieved_context> fence in the audit body")
        self.assertIn(TOOL_RESULT, ctx,
                      "tool result reached the prompt but OUTSIDE the data fence")
        self.assertIn("web_search", ctx,
                      "evidence must name the tool that produced it")
        self.assertIn(ARGS, ctx,
                      "evidence must carry the arguments, or a reviewer cannot tell "
                      "which call produced the result")

    def test_empty_context_is_still_reported_as_none(self):
        # The no-evidence case must stay distinguishable from the has-evidence one.
        provider = CapturingProvider()
        auditor = ConscienceAuditor(
            provider,
            values=[{"value": "V", "rubric": {"description": "d", "scoring_guide": []}}],
            profile={},
            prompt_config={"prompt_template": "{worldview_injection}{rubrics_str}",
                           "worldview_template": "{worldview}"},
        )
        asyncio.run(auditor.evaluate(final_output="o", user_prompt="p",
                                     reflection="", retrieved_context=""))
        self.assertEqual((fence(provider) or "").strip(), "None")


class TestMergeSemantics(unittest.TestCase):
    """The expression process_prompt uses, exercised directly."""

    @staticmethod
    def merge(retrieved_context, tool_evidence):
        if tool_evidence:
            return _apply_context_budget(
                ([retrieved_context] if retrieved_context else []) + tool_evidence)
        return retrieved_context

    def test_tool_evidence_alone(self):
        self.assertIn(TOOL_RESULT, self.merge("", [EVIDENCE]))

    def test_rag_context_is_not_displaced(self):
        merged = self.merge("RAG CHUNK ABOUT CONSCIENCE", [EVIDENCE])
        self.assertIn("RAG CHUNK ABOUT CONSCIENCE", merged)
        self.assertIn(TOOL_RESULT, merged)

    def test_no_tool_evidence_is_a_no_op(self):
        # Non-tool turns must be bit-identical to before the change.
        self.assertEqual(self.merge("RAG ONLY", []), "RAG ONLY")
        self.assertEqual(self.merge("", []), "")

    def test_oversized_evidence_says_so_rather_than_silently_dropping(self):
        big = [f"[TOOL RESULT — web_search #{i}]\n" + ("x" * 3000) for i in range(6)]
        merged = self.merge("", big)
        self.assertLess(len(merged), _MAX_CONTEXT_CHARS + 600)
        self.assertIn("CONTEXT TRUNCATED", merged,
                      "silent truncation would look like fabrication to the auditor")


class TestWiring(unittest.TestCase):

    def test_merge_precedes_finalize_draft(self):
        src = inspect.getsource(orch.SAFi.process_prompt)
        merge_at = src.find("if tool_evidence:")
        finalize_at = src.find("await self._finalize_draft(")
        self.assertNotEqual(merge_at, -1, "the tool-evidence merge is gone")
        self.assertNotEqual(finalize_at, -1, "_finalize_draft call not found")
        self.assertLess(merge_at, finalize_at,
                        "the merge must run BEFORE _finalize_draft, or the audit "
                        "sees the unmerged context and this bug is back")

    def test_every_executed_tool_appends_evidence(self):
        # One append per execute_tool, so a second call site added later without
        # evidence would be caught.
        src = inspect.getsource(orch.SAFi.process_prompt)
        self.assertEqual(src.count("await self.mcp_manager.execute_tool("),
                         src.count("tool_evidence.append("),
                         "an execute_tool call site has no matching "
                         "tool_evidence.append — its output is invisible to the audit")

    def test_args_available_on_both_history_branches(self):
        # _args_str used to be defined only in the non-Gemini else-branch; the
        # evidence block needs it on both, so it must be assigned before the split.
        src = inspect.getsource(orch.SAFi.process_prompt)
        assign = src.find("_args_str = json.dumps")
        branch = src.find("if raw_turn and _use_gemini_history:")
        self.assertNotEqual(assign, -1)
        self.assertNotEqual(branch, -1)
        self.assertLess(assign, branch,
                        "_args_str must be assigned before the Gemini/other split "
                        "or the evidence block NameErrors on the Gemini path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
