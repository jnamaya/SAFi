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


def test_explicit_llm_conscience_choice_is_preserved_and_intellect_is_separated():
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "openai/gpt-oss-20b",
        LLM_MODELS,
        conscience_explicit=True,
    )
    assert conscience == "openai/gpt-oss-20b"
    assert intellect == "openai/gpt-oss-120b"


def test_same_model_is_allowed_when_it_is_the_only_chat_model():
    only_model = [{"id": "openai/gpt-oss-20b", "provider": "groq"}]
    intellect, conscience = resolve_faculty_model_pair(
        "openai/gpt-oss-20b",
        "openai/gpt-oss-20b",
        only_model,
    )
    assert intellect == conscience == "openai/gpt-oss-20b"


def test_org_provider_block_does_not_silently_reroute(monkeypatch):
    monkeypatch.setattr(
        provider_governance, "get_org_allowlist", lambda _org: frozenset({"groq"})
    )
    monkeypatch.setattr(provider_governance, "list_models_for_org", lambda _org: LLM_MODELS)

    pair = resolve_effective_faculty_models(
        object(), "openai/gpt-oss-20b", "openai/gpt-oss-120b", "org-1",
    )

    assert pair == ("openai/gpt-oss-20b", "openai/gpt-oss-120b")



