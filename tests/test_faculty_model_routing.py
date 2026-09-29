"""Automatic Conscience preference and faculty-model separation."""
import os

from safi_app.config import (
    _PROVIDER_KEY_ENV_ORDER,
    _detect_faculty_defaults,
    _faculty_env,
)
from safi_app.core.services import model_routing, provider_governance
from safi_app.core.services.model_routing import (
    resolve_effective_faculty_models,
    resolve_faculty_model_pair,
)


LLM_MODELS = [
    {"id": "openai/gpt-oss-20b", "provider": "groq"},
    {"id": "openai/gpt-oss-120b", "provider": "groq"},
]


def test_blank_faculty_env_falls_back_to_the_detected_default():
    """.env.example ships blank faculty lines; a blank must not shadow the default.

    The appliance wizard leaves Conscience empty on purpose, and
    load_dotenv() turns that into an empty string. If Config treated it as a
    set value, CONSCIENCE_MODEL would be "" instead of the local alias, and
    every reader that bypasses the resolver (auth.py, policy_api_routes.py)
    would be handed a model that does not exist.
    """
    monkey_env = {"SAFI_CONSCIENCE_MODEL": "  "}
    saved = {k: os.environ.get(k) for k in monkey_env}
    try:
        os.environ.update(monkey_env)
        assert _faculty_env("SAFI_CONSCIENCE_MODEL", "safi-phi4-mini") == "safi-phi4-mini"
        os.environ["SAFI_CONSCIENCE_MODEL"] = "safi-qwen3-8b"
        assert _faculty_env("SAFI_CONSCIENCE_MODEL", "safi-phi4-mini") == "safi-qwen3-8b"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _BareCfg:
    TYPESAFE_API_KEY = ""
    GROQ_API_KEY = ""
    OPENAI_API_KEY = ""
    ANTHROPIC_API_KEY = ""
    GEMINI_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    MISTRAL_API_KEY = ""
    ZHIPU_API_KEY = ""
    CEREBRAS_API_KEY = ""
    LOCAL_MODEL_API_KEY = ""


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


def test_local_laya_bundle_counts_as_jev_without_an_api_key(monkeypatch):
    """An appliance has no Jev key, so the bundle itself must make Jev reachable.

    If this did not hold, the model picker would hide the typed Conscience route
    on every offline appliance and the faculty resolver would fall back to a chat
    model, quietly downgrading Conscience from a typed audit to a self-judgement.
    """
    from safi_app.core.services import jev_local

    class _Cfg:
        TYPESAFE_API_KEY = ""
        GROQ_API_KEY = ""
        OPENAI_API_KEY = ""
        ANTHROPIC_API_KEY = ""
        GEMINI_API_KEY = ""
        DEEPSEEK_API_KEY = ""
        MISTRAL_API_KEY = ""
        ZHIPU_API_KEY = ""
        CEREBRAS_API_KEY = ""
        LOCAL_MODEL_API_KEY = "local"

    monkeypatch.setattr(jev_local, "is_available", lambda: True)
    assert "typesafe" in model_routing.configured_providers(_Cfg())

    monkeypatch.setattr(jev_local, "is_available", lambda: False)
    assert "typesafe" not in model_routing.configured_providers(_Cfg())


def test_local_laya_promotes_jev_as_conscience(monkeypatch):
    """The same automatic preference a Jev key earns must follow the bundle."""
    from safi_app.core.services import jev_local
    monkeypatch.setattr(jev_local, "is_available", lambda: True)
    providers = model_routing.effective_configured_providers(_BareCfg())
    assert "typesafe" in providers
    intellect, conscience = model_routing.resolve_faculty_model_pair(
        "openai/gpt-oss-20b", "openai/gpt-oss-20b", LLM_MODELS,
        jev_available="typesafe" in providers,
    )
    assert conscience == model_routing.JEV_CONSCIENCE_MODEL
    assert intellect == "openai/gpt-oss-20b"


def test_no_bundle_and_no_key_leaves_typesafe_unconfigured(monkeypatch):
    """The hosted path must be untouched when there is no bundle."""
    from safi_app.core.services import jev_local
    monkeypatch.setattr(jev_local, "is_available", lambda: False)
    assert "typesafe" not in model_routing.configured_providers(_BareCfg())


