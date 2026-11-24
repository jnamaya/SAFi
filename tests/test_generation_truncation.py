import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FLASK_ENV", "development")

from safi_app.core.services import llm_provider as lp


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


class _StubClient:

    def __init__(self, resp, kind):
        self._resp = resp
        if kind == "openai":
            self.chat = type("C", (), {"completions": self})()
        elif kind == "anthropic":
            self.messages = self
        elif kind == "gemini":
            self.models = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._resp

    def generate_content(self, **kwargs):
        self.last_kwargs = kwargs
        return self._resp


def _provider(resp, kind):
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
    kw.setdefault("route", "intellect")
    kw.setdefault("system_prompt", "sys")
    kw.setdefault("user_prompt", "hi")

    async def go():
        text = await provider._chat_completion(**kw)
        return text, lp.generation_was_truncated()

    return asyncio.run(go())


class EveryProviderReportsItsOwnTruncation(unittest.TestCase):

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
        class _Enum:
            def __str__(self):
                return "FinishReason.MAX_TOKENS"
        _, truncated = _complete(_provider(_GeminiResponse("cut off", _Enum()), "gemini"))
        self.assertTrue(truncated)


class ANormalCompletionIsNotFlagged(unittest.TestCase):

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
        for token in ("#", "*", "`", "---", "_", "|"):
            with self.subTest(token=token):
                self.assertNotIn(token, lp.TRUNCATION_NOTICE)

    def test_the_notice_survives_the_disclaimer_check(self):
        will = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                / "faculties" / "will.py").read_text(encoding="utf-8")
        self.assertIn("elif expected not in draft_output:", will)


class TheBudgetIsConfigurable(unittest.TestCase):

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
        src = (Path(__file__).resolve().parent.parent / "safi_app" / "core" / "services"
               / "llm_provider.py").read_text(encoding="utf-8")
        i = src.index("async def run_intellect")
        body = src[i:src.index("\n    async def ", i + 10)]
        self.assertIn("max_tokens=MAX_INTELLECT_TOKENS,", body)
        self.assertNotIn("max_tokens=8192", body)


class TheDeterministicTierIsUntouched(unittest.TestCase):

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
