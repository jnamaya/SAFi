"""A dedicated local Conscience endpoint (SAFI_CONSCIENCE_BASE_URL).

The appliance's main local provider points at one llama-server, so by default
Intellect and Conscience share a single model. These tests cover the opt-in that
lets a second on-box server be the Conscience's judge: the route gains its own
base_url while the provider identity stays `local`, so provider governance, org
allow-lists and the on-box output ceiling are all unchanged.
"""
import asyncio
import logging
from types import SimpleNamespace

from safi_app.runtime_factory import build_conscience_route


def _config(**overrides):
    base = dict(
        INTELLECT_MODEL="safi-qwen3.6-35b-a3b",
        CONSCIENCE_MODEL="safi-llama3.1-8b",
        CONSCIENCE_BASE_URL="http://127.0.0.1:8082/v1",
        LOCAL_MODEL_API_KEY="local",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------
# route assembly
# --------------------------------------------------------------------------


def test_conscience_keeps_the_local_provider_identity():
    route = build_conscience_route(_config(), "safi-llama3.1-8b")
    assert route["provider"] == "local"
    assert route["model"] == "safi-llama3.1-8b"


def test_configured_base_url_moves_only_the_conscience_address():
    route = build_conscience_route(_config(), "safi-llama3.1-8b")
    assert route["base_url"] == "http://127.0.0.1:8082/v1"


def test_no_base_url_by_default():
    route = build_conscience_route(_config(CONSCIENCE_BASE_URL=""), "safi-llama3.1-8b")
    assert "base_url" not in route


def test_whitespace_only_base_url_is_ignored():
    route = build_conscience_route(_config(CONSCIENCE_BASE_URL="   "), "safi-llama3.1-8b")
    assert "base_url" not in route


def test_the_override_never_relocates_a_cloud_conscience():
    # The knob moves a local transport address; it must not hijack a hosted
    # provider's endpoint, even when the env var is set.
    route = build_conscience_route(
        _config(CONSCIENCE_MODEL="openai/gpt-oss-120b", CONSCIENCE_BASE_URL="http://127.0.0.1:8082/v1"),
        "openai/gpt-oss-120b",
    )
    assert route["provider"] == "groq"
    assert "base_url" not in route


def test_an_explicit_conscience_provider_is_respected():
    config = SimpleNamespace(
        INTELLECT_MODEL="safi-qwen3.6-35b-a3b",
        CONSCIENCE_MODEL="safi-llama3.1-8b",
        CONSCIENCE_PROVIDER="groq",
        CONSCIENCE_BASE_URL="http://127.0.0.1:8082/v1",
    )
    route = build_conscience_route(config, "safi-llama3.1-8b")
    assert route["provider"] == "groq"
    assert "base_url" not in route


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

class _StubMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _StubChoice:
    def __init__(self, content):
        self.message = _StubMessage(content)
        self.finish_reason = "stop"


class _StubUsage:
    prompt_tokens = 1
    completion_tokens = 1


class _StubResponse:
    def __init__(self, content):
        self.choices = [_StubChoice(content)]
        self.usage = _StubUsage()


class _StubCompletions:
    def __init__(self, sink):
        self._sink = sink

    def create(self, **params):
        self._sink["called"] = True
        self._sink["params"] = params
        return _StubResponse("{}")


class _StubClient:
    def __init__(self, sink):
        self.chat = type("_Chat", (), {"completions": _StubCompletions(sink)})()


def _provider_with_override():
    from safi_app.core.services.llm_provider import LLMProvider

    provider = LLMProvider.__new__(LLMProvider)
    provider.config = {
        "providers": {
            "local": {
                "type": "openai",
                "api_key": "local",
                "base_url": "http://127.0.0.1:8081/v1",
            }
        },
        "routes": {
            "conscience": {
                "provider": "local",
                "model": "safi-llama3.1-8b",
                "base_url": "http://127.0.0.1:8082/v1",
            }
        },
    }
    provider.log = logging.getLogger("test")
    main_sink, override_sink = {}, {}
    provider.clients = {"local": _StubClient(main_sink)}
    provider._org_clients = {}
    provider._route_override_clients = {
        ("conscience", "local"): _StubClient(override_sink)
    }
    return provider, main_sink, override_sink


def test_conscience_dispatches_to_its_override_client():
    provider, main_sink, override_sink = _provider_with_override()
    asyncio.run(
        provider._chat_completion(
            route="conscience", system_prompt="s", user_prompt="u", max_tokens=8192
        )
    )
    assert override_sink.get("called") is True
    assert "called" not in main_sink


def test_route_override_keeps_the_local_output_ceiling():
    # The provider is still "local", so the on-box token ceiling must still
    # apply; a runaway judge generation would otherwise ride out the timeout.
    provider, _, override_sink = _provider_with_override()
    asyncio.run(
        provider._chat_completion(
            route="conscience", system_prompt="s", user_prompt="u", max_tokens=8192
        )
    )
    assert override_sink["params"]["max_tokens"] == 1024


# --------------------------------------------------------------------------
# client construction
# --------------------------------------------------------------------------

def _provider_config(base_url=None):
    conscience_route = {"provider": "local", "model": "safi-llama3.1-8b"}
    if base_url:
        conscience_route["base_url"] = base_url
    return {
        "providers": {
            "local": {
                "type": "openai",
                "api_key": "local",
                "base_url": "http://127.0.0.1:8081/v1",
            }
        },
        "routes": {"conscience": conscience_route},
    }


def _bare_provider(config):
    from safi_app.core.services.llm_provider import LLMProvider

    provider = LLMProvider.__new__(LLMProvider)
    provider.config = config
    provider.log = logging.getLogger("test")
    provider.clients = {}
    provider._org_clients = {}
    provider._route_override_clients = {}
    return provider


def test_override_client_is_built_with_the_second_base_url(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    created = []
    class _FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(mod, "OpenAI", _FakeOpenAI)
    provider = _bare_provider(_provider_config(base_url="http://127.0.0.1:8082/v1"))
    provider._initialize_clients()
    base_urls = [c.get("base_url") for c in created]
    assert "http://127.0.0.1:8081/v1" in base_urls
    assert "http://127.0.0.1:8082/v1" in base_urls


def test_no_override_client_when_base_url_is_absent(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "OpenAI", lambda **kwargs: object())
    provider = _bare_provider(_provider_config())
    provider._initialize_clients()
    assert provider._route_override_clients == {}


def test_no_override_client_when_base_url_matches_the_provider(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "OpenAI", lambda **kwargs: object())
    provider = _bare_provider(_provider_config(base_url="http://127.0.0.1:8081/v1"))
    provider._initialize_clients()
    assert provider._route_override_clients == {}