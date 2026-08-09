"""
Unit tests for LLMProvider.run_conscience's json_mode fallback ladder.

Regression guard for the 2026-07-11 Gemma incident: gemma-4-31b (Cerebras)
under response_format=json_object with a long audit system prompt returns a
literal "{}" with HTTP 200. The old fallback only retried without json_mode
on an EXCEPTION, so the empty-but-successful response parsed to an unusable
ledger and the orchestrator failed closed. run_conscience must now:
  1. retry without json_mode when the json_mode call yields an empty ledger,
  2. retry without json_mode when the json_mode call raises (existing).

A third rule — "skip json_mode entirely for Gemma-family conscience models" —
was removed on 2026-08-09. Rules 1 and 2 already recover the same incident
without knowing what the model is called, and a model name inside faculty code
means the strictness of every audit in a deployment turns on a substring match.
See `test_conscience_sampling.py` for the guard that keeps it out.

Run:  venv/bin/python tests/test_conscience_json_fallback.py
"""
import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.llm_provider import LLMProvider

VALID_LEDGER_JSON = (
    '{"evaluations": [{"value": "Honesty", "score": 1.0, '
    '"confidence": 0.9, "reason": "ok"}]}'
)


def make_provider(model="some-model"):
    return LLMProvider({
        "providers": {},
        "routes": {"conscience": {"provider": "p", "model": model}},
    })


def run(provider):
    return asyncio.run(provider.run_conscience("sys", "user"))


class TestConscienceJsonFallback(unittest.TestCase):

    def test_valid_json_mode_ledger_needs_one_call(self):
        p = make_provider()
        p._chat_completion = AsyncMock(return_value=VALID_LEDGER_JSON)
        ledger = run(p)
        self.assertEqual(ledger[0]["value"], "Honesty")
        self.assertEqual(p._chat_completion.call_count, 1)
        self.assertTrue(p._chat_completion.call_args.kwargs.get("json_mode"))

    def test_empty_json_mode_response_retries_unconstrained(self):
        # The Gemma failure shape: HTTP 200, body "{}" — no exception raised.
        p = make_provider()
        p._chat_completion = AsyncMock(side_effect=["{}", VALID_LEDGER_JSON])
        ledger = run(p)
        self.assertEqual(ledger[0]["value"], "Honesty")
        self.assertEqual(p._chat_completion.call_count, 2)
        self.assertTrue(p._chat_completion.call_args_list[0].kwargs.get("json_mode"))
        self.assertFalse(p._chat_completion.call_args_list[1].kwargs.get("json_mode", False))

    def test_json_mode_exception_retries_unconstrained(self):
        p = make_provider()
        p._chat_completion = AsyncMock(
            side_effect=[RuntimeError("json_mode unsupported"), VALID_LEDGER_JSON])
        ledger = run(p)
        self.assertEqual(ledger[0]["value"], "Honesty")
        self.assertEqual(p._chat_completion.call_count, 2)

    def test_gemma_recovers_through_the_generic_ladder_not_a_name_check(self):
        """Replaces `test_gemma_model_skips_json_mode_entirely` (2026-08-09).

        The outcome that matters — a Gemma conscience still returns a usable
        ledger — is unchanged. What changed is how: `run_conscience` no longer
        inspects the model name, so Gemma now attempts json_mode like everything
        else, gets the degenerate "{}", and recovers via the empty-ledger retry.

        The old shortcut saved one call but put a model id inside faculty code,
        where per-model behaviour decides how strictly agents are audited. That
        trade was reversed deliberately: one wasted call on a model already kept
        out of the Conscience defaults (`config.py`) is cheaper than a naming
        convention the auditor's strictness silently depends on.
        """
        p = make_provider(model="gemma-4-31b")
        p._chat_completion = AsyncMock(side_effect=["{}", VALID_LEDGER_JSON])
        ledger = run(p)
        self.assertEqual(ledger[0]["value"], "Honesty")
        self.assertEqual(p._chat_completion.call_count, 2)
        self.assertTrue(p._chat_completion.call_args_list[0].kwargs.get("json_mode"))
        self.assertFalse(p._chat_completion.call_args_list[1].kwargs.get("json_mode", False))

    def test_model_name_does_not_change_the_first_attempt(self):
        """The general form: every model gets the same opening request."""
        for model in ("gemma-4-31b", "qwen3-32b", "openai/gpt-oss-120b", "anything"):
            with self.subTest(model=model):
                p = make_provider(model=model)
                p._chat_completion = AsyncMock(return_value=VALID_LEDGER_JSON)
                run(p)
                kwargs = p._chat_completion.call_args.kwargs
                self.assertTrue(kwargs.get("json_mode"))
                self.assertEqual(kwargs.get("temperature"), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
