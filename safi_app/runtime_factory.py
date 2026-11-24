from __future__ import annotations

import json
from pathlib import Path

from .core.orchestrator import SAFi
from .core.orchestrator_mixins.tasks import BackgroundTasksMixin, apply_memory_budget
from .core.services import LLMProvider, RAGService, MCPManager, review_alerts
from .core.services.model_routing import detect_provider, build_providers_config
from .core.services.provider_governance import activate_org
from .core.services.usage_tracking import activate_agent
from .persistence import database


class ApplicationSAFi(SAFi, BackgroundTasksMixin):

    def __init__(self, **kwargs):
        kwargs["context_budgeter"] = apply_memory_budget
        kwargs["background_task_callback"] = self._run_background_updates
        super().__init__(**kwargs)

    def _run_background_updates(self, payload):
        if payload.get("new_title"):
            self._run_title_thread(
                payload["conversation_id"], payload["user_prompt"],
                payload["assistant_output"], payload["new_title"],
            )
        self._run_summarization_thread(
            payload["conversation_id"], payload["memory_summary"],
            payload["user_prompt"], payload["assistant_output"],
        )
        if payload.get("enable_profile_extraction") and hasattr(self.config, "SUMMARIZER_MODEL"):
            self._run_profile_update_thread(
                payload["user_id"], payload["current_profile_json"],
                payload["user_prompt"], payload["assistant_output"],
            )
        if payload.get("track_work_context"):
            self._run_agent_context_update_thread(
                payload["user_id"], payload["profile_name"],
                payload["current_agent_context"], payload["user_prompt"],
                payload["assistant_output"], payload.get("message_id"),
            )


def build_conscience_route(config, conscience_model: str) -> dict:
    provider = getattr(config, "CONSCIENCE_PROVIDER", detect_provider(conscience_model))
    route = {"provider": provider, "model": conscience_model}
    if provider == "local":
        base_url = (getattr(config, "CONSCIENCE_BASE_URL", "") or "").strip()
        if base_url:
            route["base_url"] = base_url
    return route


def _resolve_live_local_model_id(base_url: str, requested: str) -> Optional[str]:
    if not base_url:
        return None
    generic = {"safi-conscience", "safi-intellect", "local", "@local", "serving", "@serving"}
    try:
        import urllib.request
        url = f"{base_url.rstrip('/')}/models"
        with urllib.request.urlopen(url, timeout=0.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            aliases = [a for a in (item.get("aliases") or []) if isinstance(a, str)]
            item_id = item.get("id")
            if item_id and item_id not in generic and (item_id == requested or requested in aliases or requested in generic):
                return item_id
            for alias in aliases:
                if alias not in generic:
                    return alias
    except Exception:
        pass
    return None


def _enrich_model_attribution(provider: str, model_name: str, base_url: Optional[str] = None) -> str:
    if not model_name:
        return f"{provider}/"
    if provider == "local" or model_name.startswith("safi-"):
        lookup_name = _resolve_live_local_model_id(base_url or "", model_name) or model_name
        try:
            catalogue_path = Path("/etc/safi/local-models.json")
            if catalogue_path.is_file():
                with open(catalogue_path, encoding="utf-8") as handle:
                    cat = json.load(handle)
                for entry in cat.get("models", []) or []:
                    entry_id = entry.get("id", "")
                    entry_alias = entry.get("alias", "")
                    entry_aliases = entry.get("aliases", [])
                    entry_file = entry.get("file", "")
                    if (
                        lookup_name == entry_id
                        or lookup_name == entry_alias
                        or (isinstance(entry_aliases, list) and lookup_name in entry_aliases)
                    ):
                        if model_name != entry_id and entry_file:
                            return f"{provider}/{model_name} [{entry_id}:{entry_file}]"
                        elif entry_file:
                            return f"{provider}/{model_name} [{entry_file}]"
        except Exception:
            pass
        if lookup_name != model_name:
            return f"{provider}/{model_name} [{lookup_name}]"
    return f"{provider}/{model_name}"


def build_safi(
    *,
    config,
    profile,
    intellect_model=None,
    will_model=None,
    conscience_model=None,
    spirit_beta=None,
):
    intellect_model = intellect_model or getattr(config, "INTELLECT_MODEL")
    conscience_model = conscience_model or getattr(config, "CONSCIENCE_MODEL")

    if intellect_model in ("local", "@local", "serving", "@serving"):
        from .config import active_local_model
        live = active_local_model()
        intellect_model = live or getattr(config, "INTELLECT_MODEL")
    if conscience_model in ("local", "@local", "serving", "@serving"):
        from .config import active_local_model
        live = active_local_model()
        conscience_model = live or getattr(config, "CONSCIENCE_MODEL")
    llm_config = {
        "providers": build_providers_config(config),
        "routes": {
            "intellect": {
                "provider": getattr(config, "INTELLECT_PROVIDER", detect_provider(intellect_model)),
                "model": intellect_model,
            },
            "conscience": build_conscience_route(config, conscience_model),
        },
    }
    llm_provider = LLMProvider(llm_config)
    rag_service = RAGService(knowledge_base_name=(profile or {}).get("rag_knowledge_base"))
    mcp_manager = MCPManager(getattr(config, "MCP_CONFIG", {}))
    intellect_prov = llm_config["routes"]["intellect"]["provider"]
    conscience_prov = llm_config["routes"]["conscience"]["provider"]
    intellect_base_url = (llm_config["providers"].get(intellect_prov) or {}).get("base_url")
    conscience_base_url = (
        llm_config["routes"]["conscience"].get("base_url")
        or (llm_config["providers"].get(conscience_prov) or {}).get("base_url")
    )
    attribution = json.dumps({
        "intellect": _enrich_model_attribution(
            intellect_prov, intellect_model, base_url=intellect_base_url
        ),
        "conscience": _enrich_model_attribution(
            conscience_prov, conscience_model, base_url=conscience_base_url
        ),
    })
    application_prompts_path = Path(__file__).with_name("application_prompts.json")
    try:
        application_prompts = json.loads(application_prompts_path.read_text(encoding="utf-8"))
    except Exception:
        application_prompts = {}

    return ApplicationSAFi(
        config=config,
        value_profile_or_list=profile,
        intellect_model=intellect_model,
        will_model=will_model,
        conscience_model=conscience_model,
        spirit_beta=spirit_beta,
        llm_provider=llm_provider,
        retriever=rag_service.retriever,
        mcp_manager=mcp_manager,
        persistence=database,
        model_attribution=attribution,
        application_prompts=application_prompts,
        activate_org_callback=activate_org,
        activate_agent_callback=activate_agent,
        review_alert_callback=review_alerts.evaluate_turn_alerts,
    )
