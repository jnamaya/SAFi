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
