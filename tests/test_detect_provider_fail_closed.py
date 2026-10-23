"""Fail-closed behaviour for detect_provider (finding #1).

An unrecognised model id used to fall through to 'groq', which is a valid
provider, so the known-provider check passed and the model rendered with
Groq's baa_capable=False / zdr="default" badge — a false HIPAA/ZDR claim.
A miss must now surface loudly instead of guessing a provider.
"""
import pytest

from safi_app.core.services.model_routing import (
    UnknownModelProviderError,
    detect_provider,
)


# --------------------------------------------------------------------------
# known ids still resolve (regression guard: fail-closed must not over-match)
# --------------------------------------------------------------------------

def test_known_prefixes_still_resolve():
    assert detect_provider("gpt-5") == "openai"
    assert detect_provider("gpt-6-luna") == "openai"
    assert detect_provider("o1-preview") == "openai"
    assert detect_provider("claude-haiku-4-5-20251001") == "anthropic"
    assert detect_provider("gemini-3.8-flash") == "gemini"
    assert detect_provider("gemma-4-31b-it") == "gemini"
    assert detect_provider("deepseek-v4-pro") == "deepseek"
    assert detect_provider("mistral-small-2603") == "mistral"
    assert detect_provider("glm-5.3") == "zhipu"
    assert detect_provider("qwen-3.8-27b") == "cerebras"
    assert detect_provider("openai/gpt-oss-120b") == "groq"
    assert detect_provider("openai/gpt-oss-20b") == "groq"
    assert detect_provider("safi-qwen3-8b") == "local"
    assert detect_provider("jev-1.13.0") == "typesafe"
    assert detect_provider("kev-4b") == "typesafe"
    assert detect_provider("jaredpalmer/kev-4b") == "typesafe"


def test_case_insensitive_known_ids():
    assert detect_provider("GPT-5") == "openai"
    assert detect_provider("Claude-Haiku") == "anthropic"
    assert detect_provider("SAFi-Qwen3-8B") == "local"


def test_groq_vendor_prefix_is_distinct_from_bare_cerebras_ids():
    # "groq/"-prefixed ids are Groq's, not Cerebras' bare "gpt-oss"/"qwen-".
    assert detect_provider("groq/openai-gpt-oss-120b") == "groq"


# --------------------------------------------------------------------------
# unknown / empty ids now raise instead of silently returning groq
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "llama3-8b",
        "safi",
        "saf",
        "totally-unknown-model",
        "foo-bar-baz",
        "models/does-not-exist",
    ],
)
def test_unknown_model_ids_raise(bad):
    with pytest.raises(UnknownModelProviderError):
        detect_provider(bad)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_model_id_raises(bad):
    with pytest.raises(UnknownModelProviderError):
        detect_provider(bad)


def test_error_is_a_value_error_and_is_actionable():
    # UnknownModelProviderError is a ValueError so generic ValueError handling
    # upstream (API error shapes) still catches it.
    assert issubclass(UnknownModelProviderError, ValueError)
    with pytest.raises(UnknownModelProviderError) as exc:
        detect_provider("mystery-model-9000")
    message = str(exc.value).lower()
    assert "mystery-model-9000" in message
    # The message tells the operator how to fix it: register the id.
    assert "custom_models" in message


# --------------------------------------------------------------------------
# custom_models precedence, models/ stripping, DB-error cache behaviour
# --------------------------------------------------------------------------

from safi_app.core.services import model_routing  # noqa: E402


@pytest.fixture
def custom_map(monkeypatch):
    """Seed the custom_models cache with an operator-registered row."""
    rows = [{"model_id": "mystery-9000", "label": "Mystery", "provider": "mistral",
             "org_id": None}]
    monkeypatch.setattr(model_routing, "_custom_models_cache",
                        {"at": None, "rows": rows,
                         "map": {"mystery-9000": "mistral"}})
    model_routing.invalidate_custom_models_cache()
    # Patch DB read so nothing is refetched (cache is already populated only
    # after custom_models() runs; force one benign read).
    monkeypatch.setattr(model_routing, "custom_models", lambda: rows)
    yield rows
    model_routing.invalidate_custom_models_cache()


def test_custom_models_takes_precedence_over_prefix_heuristics(custom_map):
    # "gpt-" would heuristically resolve to openai; the operator-registered
    # mapping must win.
    rows = custom_map + [{"model_id": "gpt-custom-999", "label": "Custom",
                          "provider": "deepseek", "org_id": None}]
    monkey_map = {r["model_id"].lower(): r["provider"] for r in rows}
    import safi_app.core.services.model_routing as mr
    original = mr.custom_models
    mr.custom_models = lambda: rows
    mr._custom_models_cache["map"] = monkey_map
    mr._custom_models_cache["rows"] = rows
    try:
        assert detect_provider("gpt-custom-999") == "deepseek"
    finally:
        mr.custom_models = original
        model_routing.invalidate_custom_models_cache()


def test_custom_models_registration_makes_unknown_id_resolve(custom_map):
    # The same id that raises without a row resolves once registered.
    assert detect_provider("mystery-9000") == "mistral"


def test_models_prefix_is_stripped_before_heuristics():
    # HuggingFace-style "models/..." ids must resolve via the stripped id.
    assert detect_provider("models/gpt-5") == "openai"
    assert detect_provider("models/claude-haiku-4-5-20251001") == "anthropic"
    # But an unrecognised stripped id still fails closed.
    with pytest.raises(UnknownModelProviderError):
        detect_provider("models/does-not-exist")


def test_db_error_keeps_last_known_custom_map(monkeypatch):
    # custom_models() fails OPEN on a DB hiccup: the last known map survives,
    # so a registered id still resolves while the DB is down.
    rows = [{"model_id": "mystery-9000", "label": "Mystery", "provider": "mistral",
             "org_id": None}]
    monkeypatch.setattr(model_routing, "_custom_models_cache",
                        {"at": None, "rows": rows,
                         "map": {"mystery-9000": "mistral"}})
    monkeypatch.setattr(
        "safi_app.persistence.database.list_custom_models",
        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert model_routing.custom_models() == rows  # survived the DB error
    model_routing.invalidate_custom_models_cache()
