"""Pure routing tests for the bundled OpenAI-compatible appliance model."""
from types import SimpleNamespace

import pytest

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


def test_unprefixed_local_looking_names_fail_closed():
    # Guards the prefix widening: a raw community id such as "llama3-8b" must
    # not be captured by the safi- rule, and a bare "safi" without the
    # separator is not an alias. None of these match a provider, so they now
    # raise instead of silently defaulting to groq (which would publish a
    # false HIPAA/ZDR badge).
    import pytest
    from safi_app.core.services.model_routing import UnknownModelProviderError

    for bad in ("llama3-8b", "safi", "saf", "totally-unknown-model"):
        with pytest.raises(UnknownModelProviderError):
            detect_provider(bad)


def test_empty_model_id_fails_closed():
    from safi_app.core.services.model_routing import UnknownModelProviderError

    with pytest.raises(UnknownModelProviderError):
        detect_provider("")
    with pytest.raises(UnknownModelProviderError):
        detect_provider("   ")


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

    def create(self, **params):
        self._sink.update(params)
        return _StubResponse("{}")


class _StubClient:
    def __init__(self, sink):
        self.chat = type("_Chat", (), {"completions": _StubCompletions(sink)})()


def _provider_for(provider_name, routes=None):
    """An LLMProvider whose single provider records the params it was called with."""
    from safi_app.core.services.llm_provider import LLMProvider

    config = {
        "providers": {
            provider_name: {"type": "openai", "api_key": "x", "base_url": "http://x/v1"}
        },
        "routes": routes or {"conscience": {"provider": provider_name, "model": "m"}},
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


def _call_route(provider, sink, route, max_tokens):
    import asyncio

    sink.clear()
    asyncio.run(
        provider._chat_completion(
            route=route, system_prompt="s", user_prompt="u", max_tokens=max_tokens
        )
    )
    return sink["max_tokens"]


def _both_routes(provider_name):
    return {
        "intellect": {"provider": provider_name, "model": "m"},
        "conscience": {"provider": provider_name, "model": "m"},
    }


def test_the_answering_route_gets_a_larger_ceiling_than_the_judge(monkeypatch):
    # The same local provider serves both. The Intellect must be able to finish
    # a tool call (a whole file body or diff); the Conscience stays small so
    # raising the answering budget never loosens the audit.
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "LOCAL_INTELLECT_MAX_TOKENS", 8192)
    monkeypatch.setattr(mod, "LOCAL_MAX_TOKENS", 1024)
    provider, sink = _provider_for("local", routes=_both_routes("local"))
    assert _call_route(provider, sink, "intellect", 8192) == 8192
    assert _call_route(provider, sink, "intellect", 16384) == 8192
    assert _call_route(provider, sink, "conscience", 8192) == 1024


def test_the_intellect_ceiling_defaults_to_the_configured_budget():
    # Out of the box the on-box Intellect is not squeezed below
    # SAFI_MAX_INTELLECT_TOKENS: raising that budget is not silently undone by
    # the local cap. Lower it explicitly (e.g. a CPU-only box) if needed.
    from safi_app.core.services import llm_provider as mod

    assert mod.LOCAL_INTELLECT_MAX_TOKENS == mod.MAX_INTELLECT_TOKENS


def test_the_intellect_ceiling_is_configurable(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "LOCAL_INTELLECT_MAX_TOKENS", 4096)
    provider, sink = _provider_for("local", routes=_both_routes("local"))
    assert _call_route(provider, sink, "intellect", 8192) == 4096


def test_the_intellect_ceiling_can_be_disabled(monkeypatch):
    from safi_app.core.services import llm_provider as mod

    monkeypatch.setattr(mod, "LOCAL_INTELLECT_MAX_TOKENS", 0)
    provider, sink = _provider_for("local", routes=_both_routes("local"))
    assert _call_route(provider, sink, "intellect", 8192) == 8192


def test_a_cloud_intellect_keeps_the_full_budget():
    provider, sink = _provider_for("groq", routes=_both_routes("groq"))
    assert _call_route(provider, sink, "intellect", 16384) == 16384


# --------------------------------------------------------------------------
# malformed / truncated tool calls
# --------------------------------------------------------------------------

class _StubFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _StubToolCall:
    def __init__(self, name, arguments):
        self.id = "call_1"
        self.function = _StubFunction(name, arguments)


class _ToolCallMessage:
    def __init__(self, name, arguments):
        self.content = None
        self.tool_calls = [_StubToolCall(name, arguments)]


class _ToolCallChoice:
    def __init__(self, name, arguments, finish_reason):
        self.message = _ToolCallMessage(name, arguments)
        self.finish_reason = finish_reason


class _ToolCallResponse:
    def __init__(self, name, arguments, finish_reason):
        self.choices = [_ToolCallChoice(name, arguments, finish_reason)]
        self.usage = _StubUsage()


class _ToolCallCompletions:
    def __init__(self, name, arguments, finish_reason):
        self._name = name
        self._arguments = arguments
        self._finish_reason = finish_reason

    def create(self, **params):
        return _ToolCallResponse(self._name, self._arguments, self._finish_reason)


class _ToolCallClient:
    def __init__(self, name, arguments, finish_reason):
        completions = _ToolCallCompletions(name, arguments, finish_reason)
        self.chat = type("_Chat", (), {"completions": completions})()


def _provider_returning_tool_call(name, arguments, finish_reason):
    import logging

    from safi_app.core.services.llm_provider import LLMProvider

    provider = LLMProvider.__new__(LLMProvider)
    provider.config = {
        "providers": {"local": {"type": "openai", "api_key": "x", "base_url": "http://x/v1"}},
        "routes": {"intellect": {"provider": "local", "model": "m"}},
    }
    provider.log = logging.getLogger("test")
    provider.clients = {"local": _ToolCallClient(name, arguments, finish_reason)}
    provider._org_clients = {}
    return provider


def _run(provider):
    import asyncio

    return asyncio.run(
        provider._chat_completion(
            route="intellect", system_prompt="s", user_prompt="u", max_tokens=8192
        )
    )


def test_a_valid_tool_call_is_returned_as_json():
    provider = _provider_returning_tool_call("write_file", '{"path": "/tmp/foo"}', "tool_calls")
    result = _run(provider)
    import json

    payload = json.loads(result)
    assert payload["tool_calls"][0]["name"] == "write_file"
    assert payload["tool_calls"][0]["arguments"] == {"path": "/tmp/foo"}


def test_truncated_tool_call_arguments_raise_an_actionable_error():
    # The exact shape the coder emits when the output cap cuts it off mid-string:
    # json.loads used to die here with an opaque JSONDecodeError that surfaced as
    # "could not reach the language model".
    provider = _provider_returning_tool_call("write_file", '{"path": "/tmp/foo', "length")
    with pytest.raises(RuntimeError) as exc:
        _run(provider)
    assert "tool call arguments" in str(exc.value).lower()
    assert "truncated" in str(exc.value).lower()


def test_malformed_tool_call_arguments_report_a_parse_failure():
    provider = _provider_returning_tool_call("write_file", "not json at all", "stop")
    with pytest.raises(RuntimeError) as exc:
        _run(provider)
    assert "tool call arguments" in str(exc.value).lower()


def test_explain_provider_error_maps_a_bad_tool_call_to_the_output_cap():
    from safi_app.core.services.llm_provider import LLMProvider

    exc = RuntimeError(
        "the model's tool call arguments were not valid JSON (empty); the generation "
        "was truncated at the output-token cap before the arguments closed"
    )
    message = LLMProvider.explain_provider_error(exc)
    assert "tool call" in message.lower()
    assert "SAFI_LOCAL_MAX_TOKENS" in message
