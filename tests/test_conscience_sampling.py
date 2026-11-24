import asyncio
import inspect
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services import llm_provider as llm_provider_module
from safi_app.core.services.llm_provider import LLMProvider, CONSCIENCE_TEMPERATURE

MODELS = [
    "qwen3-32b",
    "Qwen3-235B-A22B",
    "gemma-4-31b",
    "openai/gpt-oss-120b",
    "claude-haiku-4-5-20251001",
    "some-model-nobody-has-heard-of",
]


class _CapturingCompletions:
    def __init__(self, sink, content):
        self._sink = sink
        self._content = content

    def create(self, **kwargs):
        self._sink.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self._content, tool_calls=None))]
        )


class _FakeClient:
    def __init__(self, sink, content):
        self.chat = SimpleNamespace(completions=_CapturingCompletions(sink, content))


LEDGER_JSON = '{"evaluations": [{"value": "Honesty", "score": 1.0, "confidence": 0.9, "reason": "ok"}]}'


def _conscience_calls(model, content=LEDGER_JSON):
    sink = []
    provider = LLMProvider({
        "providers": {"groq": {"type": "openai", "api_key": ""}},
        "routes": {"conscience": {"provider": "groq", "model": model}},
    })
    provider.clients["groq"] = _FakeClient(sink, content)
    asyncio.run(provider.run_conscience("sys", "usr"))
    return sink


class ConscienceSamplingContract(unittest.TestCase):

    def test_01_temperature_is_zero(self):
        self.assertEqual(CONSCIENCE_TEMPERATURE, 0.0)

    def test_02_every_model_is_sampled_at_zero(self):
        for model in MODELS:
            with self.subTest(model=model):
                calls = _conscience_calls(model)
                self.assertTrue(calls)
                self.assertEqual(calls[0].get("temperature"), 0.0)

    def test_03_no_model_gets_top_p_or_extra_body(self):
        for model in MODELS:
            with self.subTest(model=model):
                p = _conscience_calls(model)[0]
                self.assertIsNone(p.get("top_p"))
                self.assertNotIn("reasoning_format", p)
                self.assertNotIn("reasoning_effort", p)

    def test_04_request_is_identical_across_models(self):
        baselines = []
        for model in MODELS:
            p = dict(_conscience_calls(model)[0])
            p.pop("model", None)
            baselines.append((model, p))
        first_model, first = baselines[0]
        for model, params in baselines[1:]:
            self.assertEqual(
                params, first,
                f"'{model}' is sent a different request than '{first_model}' — "
                "run_conscience must not branch on the model name",
            )

    def test_05_json_mode_is_attempted_for_every_model(self):
        for model in MODELS:
            with self.subTest(model=model):
                self.assertEqual(
                    _conscience_calls(model)[0].get("response_format"),
                    {"type": "json_object"},
                )

    def test_06_degenerate_json_mode_reply_falls_back_unconstrained(self):
        calls = _conscience_calls("gemma-4-31b", content="{}")
        self.assertEqual(len(calls), 2, "expected a retry without json_mode")
        self.assertEqual(calls[0].get("response_format"), {"type": "json_object"})
        self.assertNotIn("response_format", calls[1])
        self.assertEqual(calls[1].get("temperature"), 0.0,
                         "the retry must not quietly use a different temperature")


class NoModelNamesInFacultyCode(unittest.TestCase):

    FACULTY_METHODS = ("run_conscience", "run_intellect")
    FORBIDDEN = re.compile(
        r"\b(qwen|gemma|llama|mistral|deepseek|claude|gemini|glm|kimi|grok)\b",
        re.IGNORECASE,
    )

    def test_faculty_runners_reference_no_model_family(self):
        for name in self.FACULTY_METHODS:
            with self.subTest(method=name):
                src = inspect.getsource(getattr(LLMProvider, name))
                code = "\n".join(
                    line.split("#", 1)[0] for line in src.splitlines()
                )
                hit = self.FORBIDDEN.search(code)
                self.assertIsNone(
                    hit,
                    f"{name} branches on model family "
                    f"'{hit.group(0) if hit else ''}'. Per-model behaviour in a "
                    "faculty changes how strictly agents are audited based on an "
                    "unreviewed substring match. If a model needs a different "
                    "request SHAPE, put it in _chat_completion instead.",
                )

    def test_module_defines_the_temperature_once(self):
        src = inspect.getsource(llm_provider_module.LLMProvider.run_conscience)
        self.assertNotIn("temperature=0.1", src)
        self.assertNotIn("temperature=0.6", src)
        self.assertEqual(src.count("CONSCIENCE_TEMPERATURE"), 2,
                         "both the json_mode call and the fallback must use the constant")

    def test_the_value_is_defined_in_the_conscience_faculty(self):
        import safi_app.core.faculties.conscience as conscience_module
        self.assertEqual(conscience_module.CONSCIENCE_TEMPERATURE, 0.0)
        self.assertRegex(inspect.getsource(conscience_module),
                         r"(?m)^CONSCIENCE_TEMPERATURE\s*=\s*0\.0\s*$",
                         "the definition belongs in the covered faculty file")
        provider_src = inspect.getsource(llm_provider_module)
        self.assertNotRegex(provider_src, r"(?m)^CONSCIENCE_TEMPERATURE\s*=",
                            "llm_provider must import the value, never define it")
        self.assertIn("from ..faculties.conscience import CONSCIENCE_TEMPERATURE",
                      provider_src)

    def test_the_value_is_not_an_env_var(self):
        import safi_app.core.faculties.conscience as conscience_module
        src = inspect.getsource(conscience_module)
        at = src.index("CONSCIENCE_TEMPERATURE")
        self.assertNotIn("environ", src[at:at + 200],
                         "the Conscience temperature must not be env-configurable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
