"""
Defines the SAFi class, the main orchestrator for the application.
"""
from __future__ import annotations
import json
import threading
import uuid
import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional
from pathlib import Path
import logging

# --- Import Provider SDKs (Needed for Sync Clients) ---
from openai import OpenAI
import google.generativeai as genai

# --- Import App-Specific Core Modules ---
from collections import deque
from .feedback import build_spirit_feedback
from ..persistence import database as db
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from .plugins.bible_scholar_readings import handle_bible_scholar_commands
from .plugins.fiduciary_data import handle_fiduciary_commands

# --- Import Mixins ---
from .orchestrator_mixins.tts import TtsMixin
from .orchestrator_mixins.suggestions import SuggestionsMixin
from .orchestrator_mixins.tasks import BackgroundTasksMixin

# --- Import Refactored Services ---
from .services import LLMProvider, RAGService

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class SAFi(TtsMixin, SuggestionsMixin, BackgroundTasksMixin):
    """
    Orchestrates Intellect, Will, Conscience, and Spirit faculties.
    """

    def __init__(
        self,
        config,
        value_profile_or_list: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        value_set: Optional[List[Dict[str, Any]]] = None,
        intellect_model: Optional[str] = None,
        will_model: Optional[str] = None,
        conscience_model: Optional[str] = None
    ):
        """
        Initializes the SAFi orchestration system.
        """
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        
        # --- Helper: Auto-detect Provider (Backward Compatibility) ---
        def detect_provider(model_name: str) -> str:
            if not model_name: return "groq"
            model_lower = model_name.lower()
            if model_lower.startswith("gpt-") or model_lower.startswith("o1-"): return "openai"
            if model_lower.startswith("claude-"): return "anthropic"
            if model_lower.startswith("gemini-"): return "gemini"
            # NEW: Auto-detect DeepSeek and Mistral
            if model_lower.startswith("deepseek-"): return "deepseek"
            if model_lower.startswith("mistral-") or model_lower.startswith("codestral-") or model_lower.startswith("open-mi"): return "mistral"
            return "groq" 

        i_model = intellect_model or getattr(config, "INTELLECT_MODEL")
        w_model = will_model or getattr(config, "WILL_MODEL")
        c_model = conscience_model or getattr(config, "CONSCIENCE_MODEL")

        # --- 1. Construct LLM Configuration ---
        # FIX: We use standard keys ("groq", "openai") so existing Mixins can find them.
        llm_config = {
            "providers": {
                "openai": {
                    "type": "openai", 
                    "api_key": config.OPENAI_API_KEY
                },
                "groq": {
                    "type": "openai", 
                    "api_key": config.GROQ_API_KEY,
                    "base_url": "https://api.groq.com/openai/v1"
                },
                "anthropic": {
                    "type": "anthropic",
                    "api_key": config.ANTHROPIC_API_KEY
                },
                "gemini": {
                    "type": "gemini",
                    "api_key": config.GEMINI_API_KEY
                },
                # DeepSeek Native API
                "deepseek": {
                    "type": "openai",
                    "api_key": getattr(config, "DEEPSEEK_API_KEY", ""),
                    "base_url": "https://api.deepseek.com"
                },
                # Mistral Native API
                "mistral": {
                    "type": "openai",
                    "api_key": getattr(config, "MISTRAL_API_KEY", ""),
                    "base_url": "https://api.mistral.ai/v1"
                }
            },
            "routes": {
                "intellect": {
                    "provider": getattr(config, "INTELLECT_PROVIDER", detect_provider(i_model)), 
                    "model": i_model
                },
                "will": {
                    "provider": getattr(config, "WILL_PROVIDER", detect_provider(w_model)),
                    "model": w_model
                },
                "conscience": {
                    "provider": getattr(config, "CONSCIENCE_PROVIDER", detect_provider(c_model)),
                    "model": c_model
                }
            }
        }
        
        # Initialize the Universal LLM Provider
        self.llm_provider = LLMProvider(llm_config)
        
        # FIX: Expose the async clients to Mixins (SuggestionsMixin looks for self.clients["groq"])
        self.clients = self.llm_provider.clients

        # --- 2. RESTORE SYNC CLIENTS (For Background Threads & TTS) ---
        # The LLMProvider is purely async. We must manually restore sync clients
        # because BackgroundTasksMixin and TtsMixin rely on them.
        
        if config.GROQ_API_KEY:
            self.groq_client_sync = OpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
        
        if config.OPENAI_API_KEY:
            self.openai_client_sync = OpenAI(api_key=config.OPENAI_API_KEY)
        else:
            self.openai_client_sync = None
            
        self.gemini_client = None
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.gemini_client = genai.GenerativeModel 
            except Exception: pass

        # --- 3. Load System Prompts ---
        prompts_path = Path(__file__).parent / "system_prompts.json"
        try:
            with prompts_path.open("r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except Exception as e:
            self.log.error(f"Failed to load system_prompts.json: {e}")
            self.prompts = {}

        # --- 4. Load Persona and Values ---
        if value_profile_or_list:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = self.profile["values"]
            elif isinstance(value_profile_or_list, list):
                self.profile, self.values = None, list(value_profile_or_list)
        elif value_set:
            self.profile, self.values = None, list(value_set)
        else:
            raise ValueError("Provide either value_profile_or_list or value_set")

        # --- 5. Initialize Services & Faculties ---
        self.log_dir = getattr(config, "LOG_DIR", "logs")
        self.log_template = getattr(config, "LOG_FILE_TEMPLATE", None)
        self.active_profile_name = (self.profile or {}).get("name", "custom").lower()
        self.last_drift = 0.0
        self.mu_history = deque(maxlen=5)

        self.rag_service = RAGService(
            knowledge_base_name=self.profile.get("rag_knowledge_base")
        )
        
        self.intellect_engine = IntellectEngine(
            llm_provider=self.llm_provider,
            profile=self.profile, 
            prompt_config=self.prompts.get("intellect_engine", {})
        )
        self.intellect_engine.retriever = self.rag_service.retriever

        self.will_gate = WillGate(
            llm_provider=self.llm_provider,
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("will_gate", {})
        )

        self.conscience = ConscienceAuditor(
            llm_provider=self.llm_provider,
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("conscience_auditor", {})
        )

        self.spirit = SpiritIntegrator(self.values, beta=getattr(config, "SPIRIT_BETA", 0.9))


    async def process_prompt(
        self, 
        user_prompt: str, 
        user_id: str, 
        conversation_id: str,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        The main entrypoint for processing a user's prompt.
        """
        message_id = str(uuid.uuid4()) 
        now_utc = datetime.now(timezone.utc)
        current_date_string = now_utc.strftime("Current Date: %A, %B %d, %Y. %H:%M:%S Z")
        prompt_with_date = f"{current_date_string}\n\nUSER QUERY: {user_prompt}"
        
        # Plugins
        plugin_context_data = {}
        # Plugins may need a raw client. Use Groq sync client if available, else Async from provider.
        plugin_client = self.clients.get("groq") 
        
        plugin_tasks = [
            handle_bible_scholar_commands(user_prompt, self.active_profile_name, self.log),
            handle_fiduciary_commands(user_prompt, self.active_profile_name, self.log, plugin_client)
        ]
        plugin_results = await asyncio.gather(*plugin_tasks)
        for _, data in plugin_results:
            if data: plugin_context_data.update(data)
        
        # Memories
        memory_summary = db.fetch_conversation_summary(conversation_id)
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
        if temp_spirit_memory is None:
             temp_spirit_memory = {"turn": 0, "mu": np.zeros(max(len(self.values), 1))} 

        current_mu = temp_spirit_memory.get("mu", np.zeros(len(self.values)))
        if len(current_mu) != len(self.values):
            current_mu = np.zeros(len(self.values))

        spirit_feedback = build_spirit_feedback(
            mu=current_mu,
            value_names=[v['value'] for v in self.values],
            drift=self.last_drift,
            recent_mu=list(self.mu_history)
        )

        # Execution Chain
        a_t, r_t, retrieved_context = await self.intellect_engine.generate(
            user_prompt=prompt_with_date,
            memory_summary=memory_summary, 
            spirit_feedback=spirit_feedback,
            plugin_context=plugin_context_data,
            user_profile_json=current_profile_json,
            user_name=user_name
        )
        
        history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
        new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None

        db.insert_memory_entry(conversation_id, "user", user_prompt)

        if not a_t:
            msg = f"Intellect failed: {self.intellect_engine.last_error or 'Unknown error'}"
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed.", "messageId": message_id }

        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        if D_t == "violation":
            suppression_message = f"🛑 **Blocked**\n\nReason: {E_t}"
            S_p = await self._get_prompt_suggestions(user_prompt, self.profile.get("will_rules", []))
            db.insert_memory_entry(conversation_id, "ai", suppression_message, message_id=message_id, audit_status="complete") 
            self._append_log({"userPrompt": user_prompt, "finalOutput": suppression_message, "willDecision": D_t, "willReason": E_t, "timestamp": datetime.now(timezone.utc).isoformat()})
            return { "finalOutput": suppression_message, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "suggestedPrompts": S_p, "messageId": message_id }

        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        
        snapshot = { "t": int(temp_spirit_memory.get("turn", 0)) + 1, "x_t": user_prompt, "a_t": a_t, "r_t": r_t, "memory_summary": memory_summary, "retrieved_context": retrieved_context }
        
        # FIX: Ensure background threads have access to sync clients (self.groq_client_sync)
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()
        
        if getattr(self.config, "ENABLE_PROFILE_EXTRACTION", False):
            if hasattr(self.config, "SUMMARIZER_MODEL"):
                 threading.Thread(target=self._run_profile_update_thread, args=(user_id, current_profile_json, user_prompt, a_t), daemon=True).start()

        return { 
            "finalOutput": a_t, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, 
            "activeProfile": self.active_profile_name, "activeValues": self.values, "messageId": message_id, "suggestedPrompts": [] 
        }

    def _append_log(self, log_entry: Dict[str, Any]):
        log_path = Path(self.log_dir)
        if self.log_template:
            try:
                ts = datetime.fromisoformat(log_entry.get("timestamp").replace("Z", "+00:00"))
                fname = ts.strftime(self.log_template.format(profile=self.active_profile_name))
                log_path = log_path / fname
            except Exception: pass
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(log_path, "a", encoding="utf-8") as f: 
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception: pass