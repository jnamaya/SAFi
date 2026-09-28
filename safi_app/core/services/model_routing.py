"""
Model -> provider routing.

Single source of truth for mapping a model name to its LLM provider, used by the
orchestrator, the background note-taker, and the agent/policy save endpoints.
Kept dependency-free so it can be imported anywhere without circular-import risk.
"""
from __future__ import annotations


# Provider governance metadata. baa_capable = the provider offers a HIPAA
# Business Associate Agreement on an enterprise/API tier (OpenAI, Anthropic,
# Google via Vertex, Mistral enterprise — verified July 2026); eu_hostable =
# an EU/EEA-resident hosting option exists. zdr = zero-data-retention
# posture, verified against official provider docs July 2026:
#   "default"   — prompts/completions not retained by default
#   "available" — ZDR offered on an enterprise/request basis (not automatic;
#                 default is typically ~30-day abuse-monitoring retention)
#   False       — no ZDR option, or only an unverifiable policy assertion
#                 (Zhipu claims real-time processing but publishes no
#                 contractual ZDR program or training-use statement, so it
#                 is deliberately NOT badged; DeepSeek retains indefinitely
#                 in China and trains on API data).
# zdr_note is surfaced verbatim as the badge tooltip in the org-settings UI.
# Consumed by the per-org provider allow-list (provider_governance.py), the
# /models endpoint, and the org-settings UI badges. Keys MUST match
# build_providers_config below.
PROVIDER_METADATA = {
    "local":     {"label": "Local model (this appliance)", "baa_capable": False, "eu_hostable": False,
                   "zdr": "default",
                   "zdr_note": "Runs locally on this appliance; prompts are not sent to a third-party model provider."},
    "openai":    {"label": "OpenAI",        "baa_capable": True,  "eu_hostable": True,
                  "zdr": "available",
                  "zdr_note": "Abuse-monitoring logs up to 30 days by default; zero data retention requires OpenAI approval."},
    "anthropic": {"label": "Anthropic",     "baa_capable": True,  "eu_hostable": True,
                  "zdr": "available",
                  "zdr_note": "Deletion within 30 days by default; per-org zero-data-retention agreement via sales (some models/features excluded)."},
    "gemini":    {"label": "Google Gemini", "baa_capable": True,  "eu_hostable": True,
                  "zdr": "available",
                  "zdr_note": "No at-rest storage; 24h in-memory cache can be disabled per project; abuse-logging exception on request."},
    "mistral":   {"label": "Mistral",       "baa_capable": True,  "eu_hostable": True,
                  "zdr": "available",
                  "zdr_note": "30-day abuse-monitoring retention by default; zero data retention on request (paid tier)."},
    "groq":      {"label": "Groq",          "baa_capable": False, "eu_hostable": False,
                  "zdr": "default",
                  "zdr_note": "Inference requests not retained by default; self-serve ZDR control removes the troubleshooting exception."},
    "cerebras":  {"label": "Cerebras",      "baa_capable": False, "eu_hostable": False,
                  "zdr": "default",
                  "zdr_note": "States prompts, requests, and outputs are processed and discarded — no retention."},
    "deepseek":  {"label": "DeepSeek",      "baa_capable": False, "eu_hostable": False,
                  "zdr": False,
                  "zdr_note": "Data stored in China, retained indefinitely, used for training; no ZDR option."},
    "zhipu":     {"label": "Zhipu (Z.ai)",  "baa_capable": False, "eu_hostable": False,
                  "zdr": False,
                  "zdr_note": "Policy claims real-time processing without storage, but no contractual ZDR program or training-use statement."},
}


# Operator-added models (backlog 63): id -> provider, cached from the
# custom_models table. Consulted by detect_provider BEFORE the prefix
# heuristics, because those default to groq and a custom id must never
# depend on guessable spelling. 60s TTL like the org allow-list cache;
# fails open to the last known map so a DB hiccup cannot change routing.
_CUSTOM_MODELS_TTL = 60.0
_custom_models_cache = {"at": None, "rows": [], "map": {}}


def custom_models() -> list:
    """Rows from custom_models, cached. Each: model_id, label, provider, org_id.

    Deliberately EVERY row, unscoped: detect_provider below must resolve any
    registered id to its provider and has no org in scope. Callers that show
    models to a user filter by org_id themselves (see list_models_for_org).
    """
    import time
    now = time.monotonic()
    cache = _custom_models_cache
    if cache["at"] is None or now - cache["at"] > _CUSTOM_MODELS_TTL:
        try:
            from ...persistence import database as db
            rows = db.list_custom_models()
            cache["rows"] = rows
            cache["map"] = {r["model_id"].lower(): r["provider"] for r in rows}
        except Exception:
            pass  # keep the last known catalog
        cache["at"] = now
    return cache["rows"]


def invalidate_custom_models_cache() -> None:
    _custom_models_cache["at"] = None


def detect_provider(model_name: str) -> str:
    """Map a model name to its provider key. Operator-added models carry an
    explicit provider (exact-id match); everything else falls back to the
    prefix heuristics below. Defaults to 'groq'."""
    if not model_name:
        return "groq"
    m = model_name.lower()
    custom_models()
    custom = _custom_models_cache["map"].get(m)
    if custom:
        return custom
    # Cerebras serves gpt-oss WITHOUT the vendor prefix (Groq's id is
    # "openai/gpt-oss-*"), so this must be checked before the bare "gpt-" rule.
    if m.startswith("gpt-oss") or m.startswith("zai-") or m.startswith("gemma-4"):
        return "cerebras"
    if m.startswith("gpt-") or m.startswith("o1-"):
        return "openai"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-"):
        return "gemini"
    if m.startswith("deepseek-"):
        return "deepseek"
    if m.startswith("mistral-") or m.startswith("ministral-") or m.startswith("codestral-") or m.startswith("open-mi") or m.startswith("voxtral-"):
        return "mistral"
    if m.startswith("glm-"):
        return "zhipu"
    # Appliance-selected local models all carry a "safi-" alias
    # (safi-qwen3-8b, safi-qwen3-32b, ...), so match the reserved prefix rather
    # than one literal name. An unmatched alias would otherwise fall through to
    # groq below and send the prompt to Groq with a placeholder key, which
    # surfaces as an unreachable-provider error rather than a routing fault.
    if m.startswith("safi-"):
        return "local"
    return "groq"


def build_providers_config(config) -> dict:
    """
    Standard "providers" block for LLMProvider, built from the app Config.

    Every place that instantiates LLMProvider (orchestrator, agent/policy
    wizard endpoints) must use this so new providers only need to be added
    here — the previously hand-copied dicts had already drifted out of sync.
    """
    return {
        "openai": {
            "type": "openai",
            "api_key": getattr(config, "OPENAI_API_KEY", ""),
        },
        "groq": {
            "type": "openai",
            "api_key": getattr(config, "GROQ_API_KEY", ""),
            "base_url": "https://api.groq.com/openai/v1",
        },
        "anthropic": {
            "type": "anthropic",
            "api_key": getattr(config, "ANTHROPIC_API_KEY", ""),
        },
        "gemini": {
            "type": "gemini",
            "api_key": getattr(config, "GEMINI_API_KEY", ""),
        },
        "deepseek": {
            "type": "openai",
            "api_key": getattr(config, "DEEPSEEK_API_KEY", ""),
            "base_url": "https://api.deepseek.com",
        },
        "mistral": {
            "type": "openai",
            "api_key": getattr(config, "MISTRAL_API_KEY", ""),
            "base_url": "https://api.mistral.ai/v1",
        },
        "zhipu": {
            "type": "openai",
            "api_key": getattr(config, "ZHIPU_API_KEY", ""),
            "base_url": "https://api.z.ai/api/paas/v4",
        },
        "cerebras": {
            "type": "openai",
            "api_key": getattr(config, "CEREBRAS_API_KEY", ""),
            "base_url": "https://api.cerebras.ai/v1",
        },
        "local": {
            "type": "openai",
            "api_key": getattr(config, "LOCAL_MODEL_API_KEY", ""),
            "base_url": "http://127.0.0.1:8081/v1",
        },
    }


def configured_providers(config) -> frozenset:
    """Provider keys whose API key is actually set in the running config.

    Derived from build_providers_config so it can never drift from the set of
    providers the dispatch layer knows how to reach.
    """
    return frozenset(
        name
        for name, p in build_providers_config(config).items()
        if (p.get("api_key") or "").strip()
    )


def effective_configured_providers(config, org_id=None) -> frozenset:
    """Providers that can actually dispatch a call right now.

    The .env keys are only the *default* layer. A deployment key stored from
    the UI, and an org's own key, both make a provider usable without any .env
    entry — which is the whole point on an appliance, where there is no org and
    the .env is not editable from the UI. Returns the union so a model picker
    never hides a model that would work.
    """
    from .deployment_keys import deployment_key_providers
    from .org_keys import org_key_providers
    try:
        return frozenset(
            configured_providers(config)
            | deployment_key_providers()
            | org_key_providers(org_id)
        )
    except Exception:
        # Never let a DB hiccup hide every provider; .env alone is a safe floor.
        return configured_providers(config)


def model_provider_configured(model_name: str, config, org_id=None) -> bool:
    """True when this install holds a usable API key for the model's provider.

    Guards places that would STORE a model selection on a user's behalf
    (demo/guest defaults): a stored model whose provider has no key fails
    every turn with an unreachable-client error, so refuse the write instead.
    """
    return detect_provider(model_name) in effective_configured_providers(config, org_id)
