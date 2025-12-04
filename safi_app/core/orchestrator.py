"""
Defines the SAFi class, the main orchestrator for the application.

This module brings together all the faculties (Intellect, Will, Conscience, Spirit)
and services (LLM, RAG) to process a user's prompt. It handles the 
initialization of all components, manages the flow of data between them,
and orchestrates background tasks like logging, auditing, and summarization.
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
import httpx
import re
from bs4 import BeautifulSoup
import hashlib # Keep for TTS cache
import os # Keep for TTS cache
import time # Keep for TTS cache

# --- Import Provider SDKs ---
from openai import OpenAI, AsyncOpenAI
from anthropic import Anthropic, AsyncAnthropic
import google.generativeai as genai
from google.generativeai import types # Keep for TTS

# --- Import App-Specific Core Modules ---
from collections import deque
from .feedback import build_spirit_feedback
from ..persistence import database as db
from ..utils import dict_sha256
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
        
        # --- 1. Initialize API Clients ---
        self.clients = {} # For async clients used by LLMProvider
        self.gemini_models = {} # For Gemini models used by LLMProvider
        
        # Async Groq client
        if config.GROQ_API_KEY:
            self.clients["groq"] = AsyncOpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
            # Sync client for summarization threads
            self.groq_client_sync = OpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
        
        # Async OpenAI client
        if config.OPENAI_API_KEY:
            self.clients["openai"] = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            self.openai_client_sync = OpenAI(api_key=config.OPENAI_API_KEY) # Sync client for TTS
        else:
            self.openai_client_sync = None
        
        # Async Anthropic client
        if config.ANTHROPIC_API_KEY:
            self.clients["anthropic"] = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            
        # Gemini client (special handling)
        self.gemini_client = None # For sync TTS
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.clients["gemini"] = "configured" # Flag for LLMProvider
                self.gemini_client = genai.GenerativeModel # For sync TTS
            except Exception as e:
                self.log.warning(f"Gemini API key configuration failed: {e}. Gemini models will be unavailable.")
        
        # --- 2. Load System Prompts ---
        prompts_path = Path(__file__).parent / "system_prompts.json"
        try:
            with prompts_path.open("r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except FileNotFoundError:
            self.log.error(f"FATAL: system_prompts.json not found at {prompts_path}")
            self.prompts = {}
        except json.JSONDecodeError:
            self.log.error(f"FATAL: Failed to decode system_prompts.json. Check for syntax errors.")
            self.prompts = {}

        # --- 3. Load Persona and Values ---
        if value_profile_or_list:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = self.profile["values"]
            elif isinstance(value_profile_or_list, list):
                self.profile, self.values = None, list(value_profile_or_list)
            else:
                raise ValueError("value_profile_or_list must be a dict with 'values' or a list")
        elif value_set:
            self.profile, self.values = None, list(value_set)
        else:
            raise ValueError("Provide either value_profile_or_list or value_set")

        # Validate that value weights sum to 1.0
        if abs(sum(v["weight"] for v in self.values) - 1.0) > 1e-6:
            # Warn but don't crash
            self.log.warning(f"Value weights do not sum to 1.0 (sum={sum(v['weight'] for v in self.values)})")

        # --- 4. Configure Logging and State ---
        self.log_dir = getattr(config, "LOG_DIR", "logs")
        self.log_template = getattr(config, "LOG_FILE_TEMPLATE", None)
        self.active_profile_name = (self.profile or {}).get("name", "custom").lower()
        self.last_drift = 0.0
        self.mu_history = deque(maxlen=5) # History of recent spirit vectors

        # --- 5. Determine Model Selection ---
        intellect_model_to_use = intellect_model or getattr(config, "INTELLECT_MODEL")
        will_model_to_use = will_model or getattr(config, "WILL_MODEL")
        conscience_model_to_use = conscience_model or getattr(config, "CONSCIENCE_MODEL")

        self.model_configs = {
            "intellect": intellect_model_to_use,
            "will": will_model_to_use,
            "conscience": conscience_model_to_use
        }
        
        self.model_extra_params = {
            "qwen/qwen3-32b": { "reasoning_format": "hidden" },
            "openai/gpt-oss-120b": {},
            "openai/gpt-oss-20b": {},
            "llama-3.3-70b-versatile": {},
            "llama-3.1-8b-instant": {}
        }
        
        # --- 6. Initialize Gemini Models for LLMProvider ---
        if "gemini" in self.clients:
            for role, model_name in self.model_configs.items():
                if model_name.startswith("gemini-") and model_name not in self.gemini_models:
                    try:
                        self.gemini_models[model_name] = genai.GenerativeModel(model_name)
                        self.log.info(f"Initialized Gemini model: {model_name} for role: {role}")
                    except Exception as e:
                        self.log.error(f"Error initializing Gemini model {model_name} for {role}: {e}")
        
        # --- 7. Instantiate Services ---
        self.llm_provider = LLMProvider(
            clients=self.clients,
            gemini_models=self.gemini_models,
            model_configs=self.model_configs,
            extra_params=self.model_extra_params
        )
        
        self.rag_service = RAGService(
            knowledge_base_name=self.profile.get("rag_knowledge_base")
        )
        
        # --- 8. Instantiate Faculties (FIXED) ---
        # We must manually resolve the client and provider for each faculty,
        # because the faculty classes expect (client, provider, model), not (llm_provider).

        def resolve_resources(model_name):
            """Helper to get (client, provider_name) for a given model."""
            provider = self.llm_provider._get_provider_for_model(model_name)
            if provider == "gemini":
                # For Gemini, the faculty initializes its own GenerativeModel using the name
                return None, provider
            
            client = self.clients.get(provider)
            if not client:
                self.log.error(f"Missing client for provider '{provider}' needed by model '{model_name}'")
            return client, provider

        # Init Intellect
        i_client, i_provider = resolve_resources(self.model_configs["intellect"])
        self.intellect_engine = IntellectEngine(
            client=i_client,
            provider_name=i_provider,
            model=self.model_configs["intellect"],
            profile=self.profile, 
            prompt_config=self.prompts.get("intellect_engine", {})
        )
        # Inject services needed by intellect (RAG)
        self.intellect_engine.retriever = self.rag_service.retriever

        # Init Will
        w_client, w_provider = resolve_resources(self.model_configs["will"])
        self.will_gate = WillGate(
            client=w_client,
            provider_name=w_provider,
            model=self.model_configs["will"],
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("will_gate", {})
        )

        # Init Conscience
        c_client, c_provider = resolve_resources(self.model_configs["conscience"])
        self.conscience = ConscienceAuditor(
            client=c_client,
            provider_name=c_provider,
            model=self.model_configs["conscience"],
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("conscience_auditor", {})
        )

        # Init Spirit
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
        
        # --- 1. Pre-processing and Plugin Chain ---
        now_utc = datetime.now(timezone.utc)
        current_date_string = now_utc.strftime("Current Date: %A, %B %d, %Y. Current UTC Time: %H:%M:%S Z")
        prompt_with_date = f"{current_date_string}\n\nUSER QUERY: {user_prompt}"
        
        plugin_context_data = {}
        groq_client = self.clients.get("groq") 
        
        plugin_tasks = [
            handle_bible_scholar_commands(
                user_prompt, 
                self.active_profile_name, 
                self.log
            ),
            handle_fiduciary_commands(
                user_prompt,
                self.active_profile_name,
                self.log,
                groq_client
            )
        ]
        plugin_results = await asyncio.gather(*plugin_tasks)
        
        for _prompt, data_payload in plugin_results:
            if data_payload:
                plugin_context_data.update(data_payload)
        
        # --- 2. Fetch Memories ---
        memory_summary = db.fetch_conversation_summary(conversation_id)
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
        if temp_spirit_memory is None:
             dim = max(len(self.values), 1)
             temp_spirit_memory = {"turn": 0, "mu": np.zeros(dim)} 

        # --- MIGRATION FIX: Handle Dimension Mismatch ---
        # If the profile definition changed (different number of values), reset memory.
        current_mu = temp_spirit_memory.get("mu", np.zeros(len(self.values)))
        if len(current_mu) != len(self.values):
            self.log.warning(f"Spirit dimension mismatch for {self.active_profile_name} (Loaded: {len(current_mu)}, Required: {len(self.values)}). Resetting Spirit Memory.")
            current_mu = np.zeros(len(self.values))
            temp_spirit_memory["mu"] = current_mu
            temp_spirit_memory["turn"] = 0
        # ------------------------------------------------

        spirit_feedback = build_spirit_feedback(
            mu=current_mu,
            value_names=[v['value'] for v in self.values],
            drift=self.last_drift,
            recent_mu=list(self.mu_history)
        )

        # --- 3. Intellect (Generate Draft) ---
        a_t, r_t, retrieved_context = await self.intellect_engine.generate(
            user_prompt=prompt_with_date,
            memory_summary=memory_summary, 
            spirit_feedback=spirit_feedback,
            plugin_context=plugin_context_data,
            user_profile_json=current_profile_json,
            user_name=user_name
        )
        
        # --- 4. Store User Message and Handle Title ---
        history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
        new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None

        db.insert_memory_entry(conversation_id, "user", user_prompt)

        if not a_t:
            err = self.intellect_engine.last_error or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            self.log.error(msg)
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed to produce an answer.", "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id, "suggestedPrompts": [] }

        # --- 5. Will (Evaluate Draft) ---
        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        if D_t == "violation":
            self.log.warning(f"WillGate suppressed response. Reason: {E_t}")
            static_header = "🛑 **The answer was blocked**"
            suppression_message = f"{static_header}\n---\n\n**Reason:** {E_t.strip()}"

            S_p = await self._get_prompt_suggestions(
                user_prompt, 
                self.profile.get("will_rules", [])
            )
            
            db.insert_memory_entry(conversation_id, "ai", suppression_message, message_id=message_id, audit_status="complete") 

            self._append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "userPrompt": user_prompt,
                "finalOutput": suppression_message,
                "intellectDraft": a_t,
                "willDecision": D_t,
                "willReason": E_t,
                "conscienceLedger": [],
            })
            return { 
                "finalOutput": suppression_message, 
                "newTitle": new_title, 
                "willDecision": D_t, 
                "willReason": E_t, 
                "activeProfile": self.active_profile_name, 
                "activeValues": self.values, 
                "conscienceLedger": [], 
                "messageId": message_id,
                "suggestedPrompts": S_p
            }

        # --- 6. Store & Respond (Draft Approved) ---
        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        
        snapshot = { 
            "t": int(temp_spirit_memory["turn"]) + 1, 
            "x_t": user_prompt, 
            "a_t": a_t, 
            "r_t": r_t, 
            "memory_summary": memory_summary,
            "retrieved_context": retrieved_context 
        }
        
        # --- 7. Run Background Tasks ---
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()

        if getattr(self.config, "ENABLE_PROFILE_EXTRACTION", False):
            if hasattr(self.config, "SUMMARIZER_MODEL"):
                threading.Thread(target=self._run_profile_update_thread, args=(user_id, current_profile_json, user_prompt, a_t), daemon=True).start()

        return { 
            "finalOutput": a_t, 
            "newTitle": new_title, 
            "willDecision": D_t, 
            "willReason": E_t, 
            "activeProfile": self.active_profile_name, 
            "activeValues": self.values, 
            "messageId": message_id,
            "suggestedPrompts": [] 
        }

    def _append_log(self, log_entry: Dict[str, Any]):
        """
        Appends a JSON log entry to the configured log file.
        """
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
        except Exception as e: 
            self.log.error(f"Failed to write to log file {log_path}: {e}")