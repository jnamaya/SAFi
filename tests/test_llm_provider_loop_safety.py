"""Regression guard for the "Event loop is closed" outage.

The appliance runs Flask under gunicorn's `gthread` worker. Flask bridges each
`async def` view through asgiref, which runs the request on a NEW event loop in
a NEW thread and closes that loop when the request ends. `LLMProvider` caches
its SDK clients for the life of the process, so an async client's httpx pool
bound to the first request's loop was dead for every later request: ~90% of
Intellect attempts failed instantly with RuntimeError("Event loop is closed").

The fix uses the sync SDK clients through `asyncio.to_thread`. These tests pin
the two properties that make it correct: the cached client is sync (owns no
event loop), and it keeps working when reused across separate event loops.
"""
import asyncio
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic
from openai import AsyncOpenAI, OpenAI

from safi_app.core.services.llm_provider import LLMProvider


class _ThreadRecordingCompletions:
    """Records the thread each call runs on, so we can prove `to_thread`."""

    def __init__(self, content="ok"):
        self._content = content
        self.calls = 0
        self.thread_ids = []

    def create(self, **kwargs):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self._content, tool_calls=None),
                finish_reason="stop",
            )],
        )


class _FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def _provider(completions):
    provider = LLMProvider.__new__(LLMProvider)
    provider.log = logging.getLogger("test-loop-safety")
    provider.config = {
        "providers": {"groq": {"type": "openai", "api_key": "x"}},
        "routes": {"intellect": {"provider": "groq", "model": "m"}},
    }
    provider.clients = {"groq": _FakeClient(completions)}
    provider._org_clients = {}
    provider._org_override_client = lambda *a, **k: None
    provider._capture_usage = lambda *a, **k: None
    return provider


def _call(provider):
    return asyncio.run(
        provider._chat_completion(
            route="intellect", system_prompt="s", user_prompt="u", max_tokens=64
        )
    )


def test_initialized_clients_are_the_sync_sdk():
    provider = LLMProvider({
        "providers": {
            "groq": {"type": "openai", "api_key": "deploy-key"},
            "anthropic": {"type": "anthropic", "api_key": "deploy-key"},
        },
        "routes": {},
    })
    assert isinstance(provider.clients["groq"], OpenAI)
    assert not isinstance(provider.clients["groq"], AsyncOpenAI)
    assert isinstance(provider.clients["anthropic"], Anthropic)


def test_a_cached_client_survives_reuse_across_event_loops():
    # Two separate asyncio.run() calls == two separate, sequentially closed
    # event loops. With the old async client the second call raised
    # RuntimeError("Event loop is closed"); the sync client has no such tie.
    completions = _ThreadRecordingCompletions()
    provider = _provider(completions)

    assert _call(provider) == "ok"
    assert _call(provider) == "ok"
    assert completions.calls == 2


def test_the_blocking_call_runs_off_the_event_loop_thread():
    # Proves the call is dispatched through asyncio.to_thread rather than
    # blocking the request's loop inline.
    completions = _ThreadRecordingCompletions()
    provider = _provider(completions)

    loop_thread = []

    async def go():
        loop_thread.append(threading.get_ident())
        return await provider._chat_completion(
            route="intellect", system_prompt="s", user_prompt="u", max_tokens=64
        )

    asyncio.run(go())
    assert completions.thread_ids, "the client must be called"
    assert completions.thread_ids[0] != loop_thread[0], (
        "the model call must not block the event loop thread"
    )
