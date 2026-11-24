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
    completions = _ThreadRecordingCompletions()
    provider = _provider(completions)

    assert _call(provider) == "ok"
    assert _call(provider) == "ok"
    assert completions.calls == 2


def test_the_blocking_call_runs_off_the_event_loop_thread():
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
