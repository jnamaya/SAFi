"""Host-side assembly of model, retrieval, connector, and storage adapters."""
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
    """Host-layer feature composition around the neutral request pipeline."""

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
    """The Conscience route: provider, model, and optional dedicated base_url.

    The Conscience may run on its own local endpoint
    (SAFI_CONSCIENCE_BASE_URL), separate from the Intellect's model server, so a
    deployment can pair a strong answering model with a cheaper, faster judge.
    The override applies only when the Conscience resolves to the local
    provider: it relocates a transport address, it never changes which provider
    is chosen, so a cloud Conscience keeps its provider's own endpoint — an
    override must not silently move a hosted audit off its configured provider.
    """
    provider = getattr(config, "CONSCIENCE_PROVIDER", detect_provider(conscience_model))
    route = {"provider": provider, "model": conscience_model}
    if provider == "local":
        base_url = (getattr(config, "CONSCIENCE_BASE_URL", "") or "").strip()
        if base_url:
            route["base_url"] = base_url
    return route


def _enrich_model_attribution(provider: str, model_name: str) -> str:
    """Enrich an alias (like 'safi-intellect' or 'safi-conscience') with its concrete
    underlying model id and weights artifact from local-models.json for tamper-proof
    governance and audit trail attribution."""
    if not model_name:
        return f"{provider}/"
    if provider == "local" or model_name.startswith("safi-"):
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
                        model_name == entry_id
                        or model_name == entry_alias
                        or (isinstance(entry_aliases, list) and model_name in entry_aliases)
                    ):
                        if model_name != entry_id and entry_file:
                            return f"{provider}/{model_name} [{entry_id}:{entry_file}]"
                        elif entry_file:
                            return f"{provider}/{model_name} [{entry_file}]"
        except Exception:
            pass
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
    """Wire user-land adapters into the generic governance pipeline."""
    intellect_model = intellect_model or getattr(config, "INTELLECT_MODEL")
    conscience_model = conscience_model or getattr(config, "CONSCIENCE_MODEL")
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
    attribution = json.dumps({
        "intellect": _enrich_model_attribution(
            llm_config["routes"]["intellect"]["provider"], intellect_model
        ),
        "conscience": _enrich_model_attribution(
            llm_config["routes"]["conscience"]["provider"], conscience_model
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
