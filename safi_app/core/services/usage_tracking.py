"""
Per-org LLM token usage capture (backlog 61).

Every model call in SAFi goes through LLMProvider._chat_completion, and every
provider response already carries token counts. This module extracts those
counts and records one row per call in the plaintext llm_usage table, so the
"Usage & Cost" tab can aggregate spend per org without touching governance
records. Cost never enters the governance record: examiners adjudicate what
the model saw and said, not what it cost.

Attribution:
- org comes from provider_governance.active_org(), the same ContextVar the
  provider allow-list uses. It is set once per turn and copied into
  background executor threads.
- agent comes from the activate_agent ContextVar below, set beside the two
  activate_org calls in the orchestrator. None is fine (wizard calls, public
  bot): the row still lands with the org.

Failure contract: record_usage never raises. A usage write failure is a log
line, not a broken chat turn.

Pricing is display-time only. Raw token counts are stored because they stay
true forever; prices go stale, so they live in a config map that the API
serves to the front end. Override or extend with SAFI_LLM_PRICES, a JSON
object of {"model substring": [input_usd_per_mtok, output_usd_per_mtok]}.
"""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from typing import Any, Optional, Tuple

from .provider_governance import active_org

_ACTIVE_AGENT: ContextVar[Optional[str]] = ContextVar("safi_active_agent", default=None)

# USD per 1M tokens (input, output), matched by longest substring of the
# model name. Estimates for display, not billing records. Claude rates
# verified against Anthropic's published pricing 2026-08-17; the rest are
# best-effort defaults. Override any entry with SAFI_LLM_PRICES.
DEFAULT_PRICES = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku": (1.00, 5.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (5.00, 25.00),
    "claude-fable": (10.00, 50.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "deepseek": (0.28, 0.42),
    "llama-3.3-70b": (0.59, 0.79),
    "llama-4": (0.20, 0.60),
    "gpt-oss-120b": (0.15, 0.60),
    "gpt-oss-20b": (0.10, 0.50),
    "qwen": (0.29, 0.59),
    "mistral": (0.40, 2.00),
}


def activate_agent(profile_key: Optional[str]) -> None:
    """Names the agent for subsequent usage rows in this execution context."""
    _ACTIVE_AGENT.set(str(profile_key) if profile_key else None)


def active_agent() -> Optional[str]:
    return _ACTIVE_AGENT.get()


def get_price_map() -> dict:
    """Default prices merged with the SAFI_LLM_PRICES env override (JSON of
    {"model substring": [in_usd_per_mtok, out_usd_per_mtok]}). Bad JSON or a
    malformed entry is skipped, never fatal."""
    prices = {k: list(v) for k, v in DEFAULT_PRICES.items()}
    raw = os.environ.get("SAFI_LLM_PRICES")
    if raw:
        try:
            override = json.loads(raw)
            for key, pair in override.items():
                if (isinstance(pair, (list, tuple)) and len(pair) == 2
                        and all(isinstance(p, (int, float)) for p in pair)):
                    prices[str(key)] = [float(pair[0]), float(pair[1])]
        except (ValueError, AttributeError) as e:
            logging.warning(f"SAFI_LLM_PRICES ignored (invalid JSON): {e}")
    return prices


def extract_usage(provider_type: str, resp: Any) -> Optional[Tuple[int, int]]:
    """(input_tokens, output_tokens) from a provider response, or None when
    the response carries no usage. Never raises: SDK shape drift downgrades
    to an uncounted call, not a broken one."""
    try:
        if provider_type == "openai":
            u = getattr(resp, "usage", None)
            if u and u.prompt_tokens is not None:
                return int(u.prompt_tokens), int(u.completion_tokens or 0)
        elif provider_type == "anthropic":
            u = getattr(resp, "usage", None)
            if u and u.input_tokens is not None:
                return int(u.input_tokens), int(u.output_tokens or 0)
        elif provider_type == "gemini":
            u = getattr(resp, "usage_metadata", None)
            if u and u.prompt_token_count is not None:
                tokens_in = int(u.prompt_token_count)
                # total - prompt includes thinking tokens, which are billed as
                # output; candidates_token_count alone would undercount them.
                total = getattr(u, "total_token_count", None)
                if total:
                    return tokens_in, max(0, int(total) - tokens_in)
                return tokens_in, int(getattr(u, "candidates_token_count", 0) or 0)
    except Exception as e:
        logging.warning(f"LLM usage extraction failed ({provider_type}): {e}")
    return None


def record_usage(route: str, provider: str, model: str,
                 tokens_in: int, tokens_out: int) -> None:
    """Persist one usage row attributed to the active org and agent.
    Fire-and-forget: any failure is logged and swallowed."""
    try:
        from ...persistence import database as db
        db.insert_llm_usage(
            org_id=active_org(),
            agent=active_agent(),
            route=route,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    except Exception as e:
        logging.warning(f"LLM usage row not recorded ({provider}/{model}): {e}")
