"""
The Conscience is sampled at temperature 0, identically for every model.

WHY. The Conscience is the only intelligent component whose output feeds an
enforcement decision — its per-value scores drive the hard gates (Will Pass 2)
and the alignment threshold (Will Pass 3). So its sampling settings are a
governance parameter, not a quality knob:

  * A non-zero temperature means the same draft can be blocked on one turn and
    shipped on the next, with nothing in the audit record able to explain the
    difference.
  * Per-model tuning inside `run_conscience` silently changes how strictly every
    agent in a deployment is audited, decided by a substring match on a model id
    that nobody reviewed. `run_conscience` previously set temperature 0.6 and
    top_p 0.95 for any model whose name contained "qwen3", and 0.1 otherwise.

This pins both properties. What it does NOT claim is reproducibility: some
providers reject an explicit temperature (gpt-5/o1 — see test_gpt5_params.py)
and batching moves logits even at 0. The deterministic part of SAFi is the rule
applied to the ledger, not the ledger itself.

The request-*shape* adapters in `_chat_completion` are a separate matter and are
legitimate: those models 400 without them. The rule is that faculty code carries
no model names; transport code may.

Captures the kwargs actually handed to the client, so it tests the real dispatch
path. No database, no network. Run:
    venv/bin/python tests/test_conscience_sampling.py
"""
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

# Deliberately spans the two ids that used to take different branches, plus
# unrelated families, so a reintroduced name check fails here rather than in
# production audits.
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

    async def create(self, **kwargs):
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
    """Run run_conscience against a fake client; return every call's kwargs."""
    sink = []
    provider = LLMProvider({
        # No api_key -> _initialize_clients skips it, so nothing real is built.
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
        """These were the qwen3 branch's other two settings. top_p in particular
        narrows the sampling distribution differently per model, so leaving it on
        one family means that family audits to a different standard."""
        for model in MODELS:
            with self.subTest(model=model):
                p = _conscience_calls(model)[0]
                self.assertIsNone(p.get("top_p"))
                self.assertNotIn("reasoning_format", p)
                self.assertNotIn("reasoning_effort", p)

    def test_04_request_is_identical_across_models(self):
        """The strongest form of the rule: two different model ids must produce
        the same request but for the model name itself."""
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
        """The old code skipped json_mode for "gemma" by name. The generic
        fallback below replaces that, so the first attempt is now uniform."""
        for model in MODELS:
            with self.subTest(model=model):
                self.assertEqual(
                    _conscience_calls(model)[0].get("response_format"),
                    {"type": "json_object"},
                )

    def test_06_degenerate_json_mode_reply_falls_back_unconstrained(self):
        """What replaced the gemma name check: a model that returns a bare "{}"
        under json_mode is detected by the empty result, whatever it is called.
        Without this the audit returns an empty ledger and the Will fails closed
        on every request."""
        calls = _conscience_calls("gemma-4-31b", content="{}")
        self.assertEqual(len(calls), 2, "expected a retry without json_mode")
        self.assertEqual(calls[0].get("response_format"), {"type": "json_object"})
        self.assertNotIn("response_format", calls[1])
        self.assertEqual(calls[1].get("temperature"), 0.0,
                         "the retry must not quietly use a different temperature")


class NoModelNamesInFacultyCode(unittest.TestCase):
    """Source-level guard. The behavioural tests above only catch a name check
    for a model they happen to list; this catches any new one."""

    FACULTY_METHODS = ("run_conscience", "run_intellect")
    # Families seen in this repo's provider tables. Transport-layer adapters
    # (o1/o3, gpt-5) are intentionally excluded: those are API contracts, and
    # they live in _chat_completion, not in these methods.
    FORBIDDEN = re.compile(
        r"\b(qwen|gemma|llama|mistral|deepseek|claude|gemini|glm|kimi|grok)\b",
        re.IGNORECASE,
    )

    def test_faculty_runners_reference_no_model_family(self):
        for name in self.FACULTY_METHODS:
            with self.subTest(method=name):
                src = inspect.getsource(getattr(LLMProvider, name))
                # Strip comments: prose explaining why a check was REMOVED is
                # useful history, and must not fail the guard.
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
        """A second hardcoded temperature on a conscience call is how the
        per-model split would creep back."""
        src = inspect.getsource(llm_provider_module.LLMProvider.run_conscience)
        self.assertNotIn("temperature=0.1", src)
        self.assertNotIn("temperature=0.6", src)
        self.assertEqual(src.count("CONSCIENCE_TEMPERATURE"), 2,
                         "both the json_mode call and the fallback must use the constant")


if __name__ == "__main__":
    unittest.main(verbosity=2)
