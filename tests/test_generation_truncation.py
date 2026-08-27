"""A generation that stops because it ran out of budget must not look finished.

GOVERNANCE_BACKLOG 85. Observed 2026-08-27: three turns in one session stopped
at exactly 8192 output tokens. The answers reached the user cut off mid-sentence
with nothing in the log, nothing in the record, and no sign to the reader that
anything was missing. Only the Gemini branch had ever checked; Anthropic looked
at `stop_reason` for `tool_use` and `refusal` and ignored `max_tokens`, and the
OpenAI-compatible branch (which serves zhipu, Groq, DeepSeek and Mistral) had no
check at all.

Each provider signals truncation differently, so the detection is per branch and
each branch needs its own test. The stubs below stand in for the SDK response
objects; no network, no database, no model.

Run:  python tests/test_generation_truncation.py
"""
import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLASK_ENV", "development")

from safi_app.core.services import llm_provider as lp  # noqa: E402


# ── stub SDK responses ───────────────────────────────────────────────────────

class _OpenAIMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _OpenAIChoice:
    def __init__(self, content, finish_reason):
        self.message = _OpenAIMessage(content)
        self.finish_reason = finish_reason


class _OpenAIResponse:
    def __init__(self, content, finish_reason):
        self.choices = [_OpenAIChoice(content, finish_reason)]


class _AnthropicBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _AnthropicResponse:
    def __init__(self, text, stop_reason):
        self.content = [_AnthropicBlock(text)]
        self.stop_reason = stop_reason


class _GeminiCandidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _GeminiResponse:
    def __init__(self, text, finish_reason):
        self.text = text
        self.candidates = [_GeminiCandidate(finish_reason)]
        self.function_calls = None


# ── a provider wired to the stubs ────────────────────────────────────────────

class _StubClient:
    """Mimics whichever SDK surface the branch under test reaches for."""

    def __init__(self, resp, kind):
        self._resp = resp
        if kind == "openai":
            self.chat = type("C", (), {"completions": self})()
        elif kind == "anthropic":
            self.messages = self
        elif kind == "gemini":
            self.aio = type("A", (), {"models": self})()

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._resp

    async def generate_content(self, **kwargs):
        self.last_kwargs = kwargs
        return self._resp


def _provider(resp, kind):
    """An LLMProvider with just enough state for _chat_completion to dispatch."""
    p = lp.LLMProvider.__new__(lp.LLMProvider)
    p.log = logging.getLogger("test-truncation")
    p.config = {
        "routes": {"intellect": {"provider": "stub", "model": "stub-model-1"}},
        "providers": {"stub": {"type": kind}},
    }
    p.clients = {"stub": _StubClient(resp, kind)}
    p._org_override_client = lambda *a, **k: None
    p._capture_usage = lambda *a, **k: None
    p.last_intellect_error = None
    return p


def _complete(provider, **kw):
    """Make the call and read the flag INSIDE the same task.

    `_TRUNCATED` is a ContextVar, and `asyncio.run` runs its coroutine in a copy
    of the context, so a set inside is invisible to a read after the run returns.
    That is correct behaviour and is exactly what makes the var safe under
    concurrency; it just means the assertion has to happen on the inside, the
    same place `run_intellect` reads it. Returns (text, truncated).
    """
    kw.setdefault("route", "intellect")
    kw.setdefault("system_prompt", "sys")
    kw.setdefault("user_prompt", "hi")

    async def go():
        text = await provider._chat_completion(**kw)
        return text, lp.generation_was_truncated()

    return asyncio.run(go())


class EveryProviderReportsItsOwnTruncation(unittest.TestCase):
    """The regression: two of these three used to say nothing."""

    def test_openai_compatible_finish_reason_length(self):
        text, truncated = _complete(_provider(_OpenAIResponse("cut off here", "length"), "openai"))
        self.assertEqual(text, "cut off here", "the partial text must still be returned")
        self.assertTrue(truncated)

    def test_anthropic_stop_reason_max_tokens(self):
        text, truncated = _complete(
            _provider(_AnthropicResponse("cut off here", "max_tokens"), "anthropic"))
        self.assertEqual(text, "cut off here")
        self.assertTrue(truncated)

    def test_gemini_finish_reason_max_tokens(self):
        _, truncated = _complete(_provider(_GeminiResponse("cut off here", "MAX_TOKENS"), "gemini"))
        self.assertTrue(truncated)

    def test_gemini_enum_repr_is_matched_not_just_the_string(self):
        """The SDK returns an enum in some versions, hence the substring compare."""
        class _Enum:
            def __str__(self):
                return "FinishReason.MAX_TOKENS"
        _, truncated = _complete(_provider(_GeminiResponse("cut off", _Enum()), "gemini"))
        self.assertTrue(truncated)


class ANormalCompletionIsNotFlagged(unittest.TestCase):
    """A false positive would put a "this is incomplete" notice on every answer,
    which is worse than the bug: it teaches the reader to ignore the notice."""

    def test_openai_stop(self):
        self.assertFalse(_complete(_provider(_OpenAIResponse("all done.", "stop"), "openai"))[1])

    def test_anthropic_end_turn(self):
        self.assertFalse(
            _complete(_provider(_AnthropicResponse("all done.", "end_turn"), "anthropic"))[1])

    def test_gemini_stop(self):
        self.assertFalse(_complete(_provider(_GeminiResponse("all done.", "STOP"), "gemini"))[1])

    def test_a_missing_finish_reason_is_not_truncation(self):
        self.assertFalse(_complete(_provider(_OpenAIResponse("all done.", None), "openai"))[1])


class TheFlagDoesNotLeakBetweenCalls(unittest.TestCase):
    """The agent loop makes several calls per turn. Only the one that produced
    the text the user sees may flag it, or a truncated tool-lookup early in the
    loop would mark a complete final answer as incomplete."""

    def test_a_later_clean_call_clears_an_earlier_truncated_one(self):
        cut = _provider(_AnthropicResponse("cut", "max_tokens"), "anthropic")
        done = _provider(_AnthropicResponse("done", "end_turn"), "anthropic")

        async def two_calls_one_context():
            await cut._chat_completion(route="intellect", system_prompt="s", user_prompt="u")
            first = lp.generation_was_truncated()
            await done._chat_completion(route="intellect", system_prompt="s", user_prompt="u")
            return first, lp.generation_was_truncated()

        first, second = asyncio.run(two_calls_one_context())
        self.assertTrue(first)
        self.assertFalse(second, "the flag must be cleared at the start of every call")


class TheFlagReachesTheCaller(unittest.TestCase):
    """A ContextVar set inside an awaited coroutine IS visible to the awaiting
    caller: same task, same context. That is what carries the flag from
    `_chat_completion` up to `run_intellect`, and it would break silently if
    someone wrapped the call in create_task or gather."""

    def test_run_intellect_sees_what_chat_completion_set(self):
        body = "half an answer---REFLECTION---{\"reflection\": \"ok\"}"
        p = _provider(_AnthropicResponse(body, "max_tokens"), "anthropic")
        p._INTELLECT_MAX_ATTEMPTS = lp.LLMProvider._INTELLECT_MAX_ATTEMPTS

        async def go():
            answer, _, _, _ = await p.run_intellect("sys", "hi", "ctx")
            return answer, lp.generation_was_truncated()

        answer, truncated = asyncio.run(go())
        self.assertTrue(truncated)
        self.assertIn("incomplete", answer.lower())


class TheReaderIsTold(unittest.TestCase):
    """The half that matters to the person who reported this: a log line they
    never see does not tell them their answer is missing its ending.

    The stub bodies use the real wire format, `answer---REFLECTION---{json}`.
    That ordering is why a truncated turn loses its reflection entirely: the
    reflection is emitted last, so it is the first thing a hard stop costs. A
    long answer beside an empty reflection is the field signature of this bug,
    and it is how event 8952 was identified.
    """

    def _run_intellect(self, resp, kind):
        p = _provider(resp, kind)
        p._INTELLECT_MAX_ATTEMPTS = lp.LLMProvider._INTELLECT_MAX_ATTEMPTS
        return asyncio.run(p.run_intellect("sys", "hi", "ctx"))

    def test_a_truncated_answer_carries_the_notice(self):
        body = ("The first half of a long answer that stops"
                "---REFLECTION---{\"reflection\": \"ok\"}")
        answer, _, _, _ = self._run_intellect(_AnthropicResponse(body, "max_tokens"), "anthropic")
        self.assertIn(lp.TRUNCATION_NOTICE.strip(), answer)
        self.assertIn("incomplete", answer.lower())

    def test_a_complete_answer_is_left_exactly_as_written(self):
        body = "A complete answer.---REFLECTION---{\"reflection\": \"fine\"}"
        answer, _, _, _ = self._run_intellect(_AnthropicResponse(body, "end_turn"), "anthropic")
        self.assertEqual(answer, "A complete answer.")

    def test_the_notice_carries_no_markdown(self):
        """It is appended to the DRAFT, so the Will's banned_markdown_syntaxes
        and the Conscience both see it. A notice that trips its own deployment's
        style gate would turn a truncated answer into a blocked one."""
        for token in ("#", "*", "`", "---", "_", "|"):
            with self.subTest(token=token):
                self.assertNotIn(token, lp.TRUNCATION_NOTICE)

    def test_the_notice_survives_the_disclaimer_check(self):
        """will.py:107 asks `expected not in draft_output`, a substring test, so
        appending after a mandatory disclaimer cannot break it. Pinned because
        an endswith() check there would silently start blocking these."""
        will = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                / "faculties" / "will.py").read_text(encoding="utf-8")
        self.assertIn("elif expected not in draft_output:", will)


class TheBudgetIsConfigurable(unittest.TestCase):
    """It was a hardcoded 8192, so a deployment that hit it could not raise it
    without editing the code."""

    def test_the_default_is_unchanged(self):
        self.assertEqual(lp.MAX_INTELLECT_TOKENS, 8192)

    def test_the_intellect_sends_the_configured_budget(self):
        body = "ok---REFLECTION---{\"reflection\": \"fine\"}"
        p = _provider(_AnthropicResponse(body, "end_turn"), "anthropic")
        p._INTELLECT_MAX_ATTEMPTS = lp.LLMProvider._INTELLECT_MAX_ATTEMPTS
        asyncio.run(p.run_intellect("sys", "hi", "ctx"))
        self.assertEqual(p.clients["stub"].last_kwargs["max_tokens"],
                         lp.MAX_INTELLECT_TOKENS)

    def test_the_env_var_is_the_source(self):
        src = (Path(__file__).resolve().parent.parent / "safi_app" / "core" / "services"
               / "llm_provider.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("SAFI_MAX_INTELLECT_TOKENS", "8192")', src)

    def test_run_intellect_does_not_hardcode_a_budget_again(self):
        """Scoped to run_intellect on purpose. The conscience route still sends a
        literal 8192, which is a separate call with a separate failure mode: a
        truncated ledger is malformed JSON and the Will fails closed, so it stops
        the turn instead of reaching the reader. Noted in BACKLOG 85."""
        src = (Path(__file__).resolve().parent.parent / "safi_app" / "core" / "services"
               / "llm_provider.py").read_text(encoding="utf-8")
        i = src.index("async def run_intellect")
        body = src[i:src.index("\n    async def ", i + 10)]
        self.assertIn("max_tokens=MAX_INTELLECT_TOKENS,", body)
        self.assertNotIn("max_tokens=8192", body)


class TheDeterministicTierIsUntouched(unittest.TestCase):
    """Detection is transport-level bookkeeping in a service module. It reads a
    field the provider already returned; it calls no model and decides nothing."""

    def test_no_faculty_was_changed(self):
        core = Path(__file__).resolve().parent.parent / "safi_app" / "core"
        src = (core / "services" / "llm_provider.py").read_text(encoding="utf-8")
        i = src.index("def _note_truncation")
        j = src.index("def _capture_usage", i)
        for token in ("run_intellect", "run_conscience", "await "):
            with self.subTest(token=token):
                self.assertNotIn(token, src[i:j])


if __name__ == "__main__":
    unittest.main(verbosity=2)
