"""
Unit tests for LLMProvider.run_conscience's json_mode fallback ladder.

Regression guard for the 2026-07-11 Gemma incident: gemma-4-31b (Cerebras)
under response_format=json_object with a long audit system prompt returns a
literal "{}" with HTTP 200. The old fallback only retried without json_mode
on an EXCEPTION, so the empty-but-successful response parsed to an unusable
ledger and the orchestrator failed closed. run_conscience must now:
  1. retry without json_mode when the json_mode call yields an empty ledger,
  2. retry without json_mode when the json_mode call raises (existing), and
  3. skip json_mode entirely for Gemma-family conscience models.

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

    def test_gemma_model_skips_json_mode_entirely(self):
        p = make_provider(model="gemma-4-31b")
        p._chat_completion = AsyncMock(return_value=VALID_LEDGER_JSON)
        ledger = run(p)
        self.assertEqual(ledger[0]["value"], "Honesty")
        self.assertEqual(p._chat_completion.call_count, 1)
        self.assertFalse(p._chat_completion.call_args.kwargs.get("json_mode", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
