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
    return "groq"
