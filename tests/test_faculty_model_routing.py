"""Automatic Conscience preference and faculty-model separation."""
from safi_app.config import _PROVIDER_KEY_ENV_ORDER, _detect_faculty_defaults
from safi_app.core.services import model_routing, provider_governance
from safi_app.core.services.model_routing import (
    resolve_effective_faculty_models,
    resolve_faculty_model_pair,
)


LLM_MODELS = [
    {"id": "openai/gpt-oss-20b", "provider": "groq"},
    {"id": "openai/gpt-oss-120b", "provider": "groq"},
]


def test_automatic_conscience_prefers_jev_when_key_is_available():
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        LLM_MODELS,
        jev_available=True,
    )
    assert conscience == "jev-1.13.0"
    assert intellect == "openai/gpt-oss-20b"


def test_explicit_llm_conscience_choice_is_preserved_and_intellect_is_separated():
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "openai/gpt-oss-20b",
        LLM_MODELS,
        jev_available=True,
        conscience_explicit=True,
    )
    assert conscience == "openai/gpt-oss-20b"
    assert intellect == "openai/gpt-oss-120b"


def test_stale_jev_choice_falls_back_to_available_llm_without_key():
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "jev-1.13.0",
        LLM_MODELS,
        jev_available=False,
    )
    assert conscience == "openai/gpt-oss-20b"
    assert intellect == "openai/gpt-oss-120b"


def test_same_model_is_allowed_when_it_is_the_only_chat_model():
    only_model = [{"id": "openai/gpt-oss-20b", "provider": "groq"}]
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "jev-1.13.0",
        only_model,
        jev_available=False,
    )
    assert intellect == conscience == "openai/gpt-oss-20b"


def test_deployment_defaults_use_jev_for_conscience_when_key_is_set(monkeypatch):
    for _provider, env_var in _PROVIDER_KEY_ENV_ORDER:
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "configured")
    monkeypatch.setenv("TYPESAFE_API_KEY", "configured")

    defaults = _detect_faculty_defaults()

    assert defaults["conscience"] == "jev-1.13.0"
    assert defaults["intellect"] == "openai/gpt-oss-20b"


def test_effective_deployment_or_org_key_enables_automatic_jev(monkeypatch):
    monkeypatch.setattr(provider_governance, "get_org_allowlist", lambda _org: None)
    monkeypatch.setattr(provider_governance, "list_models_for_org", lambda _org: LLM_MODELS)
    monkeypatch.setattr(
        model_routing, "effective_configured_providers",
        lambda _config, _org: frozenset({"groq", "typesafe"}),
    )

    intellect, conscience = resolve_effective_faculty_models(
        object(), "openai/gpt-oss-20b", "openai/gpt-oss-120b",
    )

    assert intellect == "openai/gpt-oss-20b"
    assert conscience == "jev-1.13.0"


def test_org_provider_block_does_not_silently_reroute(monkeypatch):
    monkeypatch.setattr(
        provider_governance, "get_org_allowlist", lambda _org: frozenset({"groq"})
    )
    monkeypatch.setattr(provider_governance, "list_models_for_org", lambda _org: LLM_MODELS)

    pair = resolve_effective_faculty_models(
        object(), "openai/gpt-oss-20b", "jev-1.13.0", "org-1",
    )

    assert pair == ("openai/gpt-oss-20b", "jev-1.13.0")
