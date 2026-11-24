from __future__ import annotations


PROVIDER_METADATA = {
    "local":     {"label": "Local model (this appliance)", "baa_capable": False, "eu_hostable": False,
                   "tier": "core",
                   "zdr": "default",
                   "zdr_note": "Runs locally on this appliance; prompts are not sent to a third-party model provider."},
    "openai":    {"label": "OpenAI",        "baa_capable": True,  "eu_hostable": True,
                  "tier": "core",
                  "zdr": "available",
                  "zdr_note": "Abuse-monitoring logs up to 30 days by default; zero data retention requires OpenAI approval."},
    "anthropic": {"label": "Anthropic",     "baa_capable": True,  "eu_hostable": True,
                  "tier": "core",
                  "zdr": "available",
                  "zdr_note": "Deletion within 30 days by default; per-org zero-data-retention agreement via sales (some models/features excluded)."},
    "gemini":    {"label": "Google Gemini", "baa_capable": True,  "eu_hostable": True,
                  "tier": "core",
                  "zdr": "available",
                  "zdr_note": "No at-rest storage; 24h in-memory cache can be disabled per project; abuse-logging exception on request."},
    "mistral":   {"label": "Mistral",       "baa_capable": True,  "eu_hostable": True,
                  "tier": "extended",
                  "zdr": "available",
                  "zdr_note": "30-day abuse-monitoring retention by default; zero data retention on request (paid tier)."},
    "groq":      {"label": "Groq",          "baa_capable": False, "eu_hostable": False,
                  "tier": "extended",
                  "zdr": "default",
                  "zdr_note": "Inference requests not retained by default; self-serve ZDR control removes the troubleshooting exception."},
    "cerebras":  {"label": "Cerebras",      "baa_capable": False, "eu_hostable": False,
                  "tier": "extended",
                  "zdr": "default",
                  "zdr_note": "States prompts, requests, and outputs are processed and discarded — no retention."},
    "deepseek":  {"label": "DeepSeek",      "baa_capable": False, "eu_hostable": False,
                  "tier": "extended",
                  "zdr": False,
                  "zdr_note": "Data stored in China, retained indefinitely, used for training; no ZDR option."},
    "zhipu":     {"label": "Zhipu (Z.ai)",  "baa_capable": False, "eu_hostable": False,
                   "tier": "extended",
                   "zdr": False,
                   "zdr_note": "Policy claims real-time processing without storage, but no contractual ZDR program or training-use statement."},
}


_CUSTOM_MODELS_TTL = 60.0
_custom_models_cache = {"at": None, "rows": [], "map": {}}


def custom_models() -> list:
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
            pass
        cache["at"] = now
    return cache["rows"]


def invalidate_custom_models_cache() -> None:
    _custom_models_cache["at"] = None


class UnknownModelProviderError(ValueError):
    pass


def detect_provider(model_name: str) -> str:
    if not model_name:
        raise UnknownModelProviderError(
            "empty model id: no provider can be resolved")
    m = model_name.lower()
    custom_models()
    custom = _custom_models_cache["map"].get(m)
    if custom:
        return custom
    if m.startswith("models/"):
        m = m[7:]
    if m.startswith("openai/gpt-oss") or m.startswith("groq/"):
        return "groq"
    if (m.startswith("gpt-oss") or m.startswith("zai-")
            or m.startswith("qwen-")):
        return "cerebras"
    if m.startswith("gpt-") or m.startswith("o1-"):
        return "openai"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-") or m.startswith("gemma-"):
        return "gemini"
    if m.startswith("deepseek-"):
        return "deepseek"
    if m.startswith("mistral-") or m.startswith("ministral-") or m.startswith("codestral-") or m.startswith("open-mi") or m.startswith("voxtral-"):
        return "mistral"
    if m.startswith("glm-") or m.startswith("codegeex-"):
        return "zhipu"
    if m.startswith("safi-") or m in ("local", "@local", "serving", "@serving"):
        return "local"
    raise UnknownModelProviderError(
        f"model id {model_name!r} matched no known provider; "
        "register it explicitly in the custom_models table to resolve it")


def build_providers_config(config) -> dict:
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
            "base_url": getattr(config, "ZHIPU_BASE_URL", "") or "https://api.z.ai/api/coding/paas/v4",
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
    return frozenset(
        name
        for name, p in build_providers_config(config).items()
        if (p.get("api_key") or "").strip()
    )


def effective_configured_providers(config, org_id=None) -> frozenset:
    from .deployment_keys import deployment_key_providers
    from .org_keys import org_key_providers
    try:
        return frozenset(
            configured_providers(config)
            | deployment_key_providers()
            | org_key_providers(org_id)
        )
    except Exception:
        return configured_providers(config)


def resolve_faculty_model_pair(
    intellect_model: str,
    conscience_model: str,
    available_models: list,
    *,
    conscience_explicit: bool = False,
    intellect_explicit: bool = False,
) -> tuple[str, str]:
    entries = []
    for entry in available_models or []:
        model_id = entry.get("id") if isinstance(entry, dict) else entry
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        provider = (
            entry.get("provider") if isinstance(entry, dict) else None
        ) or detect_provider(model_id)
        entries.append((model_id, provider))

    by_id = {model_id.casefold(): (model_id, provider) for model_id, provider in entries}
    llm_models = [model_id for model_id, provider in entries]
    llm_models = list(dict.fromkeys(llm_models))

    intellect = intellect_model or ""
    conscience = conscience_model or ""
    configured_conscience = by_id.get(conscience.casefold()) if conscience else None

    if not conscience_explicit and configured_conscience is None and llm_models:
        conscience = llm_models[0]

    if not intellect_explicit and intellect.casefold() not in by_id and llm_models:
        intellect = llm_models[0]

    if intellect and conscience and intellect.casefold() == conscience.casefold():
        if not (intellect_explicit and conscience_explicit):
            alternatives = [model for model in llm_models if model.casefold() != conscience.casefold()]
            if alternatives:
                intellect = alternatives[0]

    return intellect, conscience


def resolve_effective_faculty_models(
    config,
    intellect_model: str,
    conscience_model: str,
    org_id=None,
    *,
    conscience_explicit: bool = False,
    intellect_explicit: bool = False,
    allowlist: Optional[FrozenSet[str]] = None,
) -> tuple[str, str]:
    from .provider_governance import get_org_allowlist, list_models_for_org, model_allowed
    from ...config import active_local_model

    if intellect_model in ("local", "@local", "serving", "@serving"):
        live = active_local_model()
        if live:
            intellect_model = live
    if conscience_model in ("local", "@local", "serving", "@serving"):
        live = active_local_model()
        if live:
            conscience_model = live

    effective_allowlist = allowlist if allowlist is not None else get_org_allowlist(org_id)
    if effective_allowlist is not None and any(
        not model_allowed(model, effective_allowlist)
        for model in (intellect_model, conscience_model)
        if model
    ):
        return intellect_model, conscience_model

    available = list_models_for_org(org_id, allow=effective_allowlist)
    return resolve_faculty_model_pair(
        intellect_model,
        conscience_model,
        available,
        conscience_explicit=conscience_explicit,
        intellect_explicit=intellect_explicit,
    )


def model_provider_configured(model_name: str, config, org_id=None) -> bool:
    return detect_provider(model_name) in effective_configured_providers(config, org_id)
