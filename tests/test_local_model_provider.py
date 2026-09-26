"""Pure routing tests for the bundled OpenAI-compatible appliance model."""
from types import SimpleNamespace

from safi_app.core.services.model_routing import (
    build_providers_config,
    detect_provider,
    PROVIDER_METADATA,
)


def test_safi_demo_routes_to_local_provider():
    assert detect_provider("safi-demo") == "local"


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
