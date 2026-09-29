"""Pure routing tests for the bundled OpenAI-compatible appliance model."""
from types import SimpleNamespace

from safi_app.core.services.model_routing import (
    build_providers_config,
    detect_provider,
    PROVIDER_METADATA,
)


def test_safi_demo_routes_to_local_provider():
    assert detect_provider("safi-demo") == "local"


def test_every_appliance_model_alias_routes_to_local():
    # The setup wizard publishes the operator's choice as a safi- alias, so the
    # reserved prefix has to carry the whole catalogue, not one literal name.
    for alias in ("safi-qwen3-4b", "safi-qwen3-8b", "safi-qwen3-14b", "safi-qwen3-32b"):
        assert detect_provider(alias) == "local", alias


def test_alias_routing_is_case_insensitive():
    assert detect_provider("SAFi-Qwen3-8B") == "local"


def test_unprefixed_local_looking_names_still_default_to_groq():
    # Guards the prefix widening: a raw community id such as "llama3-8b" must
    # not be captured by the safi- rule, and a bare "safi" without the
    # separator is not an alias.
    assert detect_provider("llama3-8b") == "groq"
    assert detect_provider("safi") == "groq"
    assert detect_provider("saf") == "groq"


def test_local_provider_uses_existing_openai_shape():
    config = SimpleNamespace(LOCAL_MODEL_API_KEY="local")
    providers = build_providers_config(config)
    assert providers["local"] == {
        "type": "openai",
        "api_key": "local",
        "base_url": "http://127.0.0.1:8081/v1",
    }


def test_local_provider_has_no_external_compliance_badges():
    metadata = PROVIDER_METADATA["local"]
    assert metadata["baa_capable"] is False
    assert metadata["eu_hostable"] is False


# --------------------------------------------------------------------------
# local output-token ceiling
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

    async def create(self, **params):
        self._sink.update(params)
        return _StubResponse("{}")


class _StubClient:
    def __init__(self, sink):
        self.chat = type("_Chat", (), {"completions": _StubCompletions(sink)})()


def _provider_for(provider_name):
    """An LLMProvider whose single provider records the params it was called with."""
    from safi_app.core.services.llm_provider import LLMProvider

    config = {
        "providers": {
            provider_name: {"type": "openai", "api_key": "x", "base_url": "http://x/v1"}
        },
        "routes": {"conscience": {"provider": provider_name, "model": "m"}},
    }
    provider = LLMProvider.__new__(LLMProvider)
    provider.config = config
    import logging

    provider.log = logging.getLogger("test")
    sink = {}
    provider.clients = {provider_name: _StubClient(sink)}
    provider._org_clients = {}
    return provider, sink


def _call(provider, sink, max_tokens):
    import asyncio

    sink.clear()
    asyncio.run(
        provider._chat_completion(
            route="conscience", system_prompt="s", user_prompt="u", max_tokens=max_tokens
        )
    )
    return sink["max_tokens"]


def test_local_provider_request_is_capped_so_the_generation_finishes():
    # 8192 tokens on a 3B model at CPU speeds runs minutes past the 300s
    # per-call timeout, which returns nothing. Capping returns a real answer.
    provider, sink = _provider_for("local")
    assert _call(provider, sink, 8192) == 1024


def test_a_request_already_under_the_ceiling_is_untouched():
    provider, sink = _provider_for("local")
    assert _call(provider, sink, 512) == 512


def test_cloud_providers_keep_the_callers_budget():
    # The ceiling is a capacity limit on the on-box server, not an audit policy,
    # so it must not touch a provider that can serve the full budget.
    provider, sink = _provider_for("groq")
    assert _call(provider, sink, 8192) == 8192


def test_the_ceiling_can_be_disabled(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "LOCAL_MAX_TOKENS", 0)
    provider, sink = _provider_for("local")
    assert _call(provider, sink, 8192) == 8192


def test_the_ceiling_is_configurable(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "LOCAL_MAX_TOKENS", 2048)
    provider, sink = _provider_for("local")
    assert _call(provider, sink, 8192) == 2048
