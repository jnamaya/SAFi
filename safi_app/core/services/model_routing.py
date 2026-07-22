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


def detect_provider(model_name: str) -> str:
    """Map a model name to its provider key by prefix. Defaults to 'groq'."""
    if not model_name:
        return "groq"
    m = model_name.lower()
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
