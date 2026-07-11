"""
Model -> provider routing.

Single source of truth for mapping a model name to its LLM provider, used by the
orchestrator, the background note-taker, and the agent/policy save endpoints.
Kept dependency-free so it can be imported anywhere without circular-import risk.
"""
from __future__ import annotations


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
    if m.startswith("mistral-") or m.startswith("ministral-") or m.startswith("codestral-") or m.startswith("open-mi"):
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
