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
            "conscience": {
                "provider": getattr(config, "CONSCIENCE_PROVIDER", detect_provider(conscience_model)),
                "model": conscience_model,
            },
        },
    }
    llm_provider = LLMProvider(llm_config)
    rag_service = RAGService(knowledge_base_name=(profile or {}).get("rag_knowledge_base"))
    mcp_manager = MCPManager(getattr(config, "MCP_CONFIG", {}))
    attribution = json.dumps({
        "intellect": f"{llm_config['routes']['intellect']['provider']}/{intellect_model}",
        "conscience": f"{llm_config['routes']['conscience']['provider']}/{conscience_model}",
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
