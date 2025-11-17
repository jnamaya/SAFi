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

from openai import OpenAI, AsyncOpenAI
from anthropic import Anthropic, AsyncAnthropic
import google.generativeai as genai
from google.generativeai import types # Keep for TTS

from collections import deque
from .feedback import build_spirit_feedback
from ..persistence import database as db
from ..utils import dict_sha256
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from .plugins.bible_scholar_readings import handle_bible_scholar_commands
from .plugins.fiduciary_data import handle_fiduciary_commands

# --- NEW: Import the mixins ---
from .orchestrator_mixins.tts import TtsMixin
from .orchestrator_mixins.suggestions import SuggestionsMixin
from .orchestrator_mixins.tasks import BackgroundTasksMixin
# --- END NEW ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- NEW: Add Mixins to the class definition ---
class SAFi(TtsMixin, SuggestionsMixin, BackgroundTasksMixin):
# --- END NEW ---
    """
    Orchestrates Intellect, Will, Conscience, and Spirit
    using multiple model providers.
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
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        
        self.clients = {}
        
        # --- Asynchronous clients for faculties ---
        if config.GROQ_API_KEY:
            self.clients["groq"] = AsyncOpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
            self.groq_client_sync = OpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
        
        if config.OPENAI_API_KEY:
            self.clients["openai"] = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            self.openai_client_sync = OpenAI(api_key=config.OPENAI_API_KEY) # Sync client for TTS
        else:
            self.openai_client_sync = None
        
        if config.ANTHROPIC_API_KEY:
            self.clients["anthropic"] = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            
        # --- Synchronous clients for TTS & Summarization ---
        self.gemini_client = None # Renamed for clarity
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.clients["gemini"] = "configured"
                
                # Initialize a synchronous client for Gemini TTS
                self.gemini_client = genai.GenerativeModel
            except Exception as e:
                self.log.warning(f"Gemini API key configuration failed: {e}. Gemini models will be unavailable.")
        
        prompts_path = Path(__file__).parent / "system_prompts.json"
        try:
            with prompts_path.open("r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except FileNotFoundError:
            self.log.error(f"FATAL: system_prompts.json not found at {prompts_path}")
            self.prompts = {} # Set empty to avoid crash, but log error
        except json.JSONDecodeError:
            self.log.error(f"FATAL: Failed to decode system_prompts.json. Check for syntax errors.")
            self.prompts = {}

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

        if abs(sum(v["weight"] for v in self.values) - 1.0) > 1e-6:
            raise ValueError(f"Value weights must sum to 1.0")

        self.log_dir = getattr(config, "LOG_DIR", "logs")
        self.log_template = getattr(config, "LOG_FILE_TEMPLATE", None)
        self.active_profile_name = (self.profile or {}).get("name", "custom").lower()
        
        self.last_drift = 0.0
        
        self.mu_history = deque(maxlen=5)

        intellect_model_to_use = intellect_model or getattr(config, "INTELLECT_MODEL")
        will_model_to_use = will_model or getattr(config, "WILL_MODEL")
        conscience_model_to_use = conscience_model or getattr(config, "CONSCIENCE_MODEL")

        intellect_client, intellect_provider = self._get_client_and_provider(intellect_model_to_use)
        will_client, will_provider = self._get_client_and_provider(will_model_to_use)
        conscience_client, conscience_provider = self._get_client_and_provider(conscience_model_to_use)

        self.intellect_engine = IntellectEngine(
            intellect_client,
            provider_name=intellect_provider,
            model=intellect_model_to_use, 
            profile=self.profile, 
            prompt_config=self.prompts.get("intellect_engine", {})
        )
        self.will_gate = WillGate(
            will_client, 
            provider_name=will_provider,
            model=will_model_to_use, 
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("will_gate", {})
        )
        self.conscience = ConscienceAuditor(
            conscience_client, 
            provider_name=conscience_provider,
            model=conscience_model_to_use, 
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts.get("conscience_auditor", {})
        )
        self.spirit = SpiritIntegrator(self.values, beta=getattr(config, "SPIRIT_BETA", 0.9))

    def _get_client_and_provider(self, model_name: str) -> (Any, str):
        """
        Returns the correct client instance and provider name based on the model name.
        """
        if model_name.startswith("gpt-"):
            if "openai" in self.clients:
                return self.clients["openai"], "openai"
        elif model_name.startswith("claude-"):
            if "anthropic" in self.clients:
                return self.clients["anthropic"], "anthropic"
        elif model_name.startswith("gemini-"):
            if "gemini" in self.clients:
                return model_name, "gemini" 
        
        if "groq" in self.clients:
            return self.clients["groq"], "groq"
            
        raise ValueError(f"No valid client found for model '{model_name}'. Check your API keys and model names.")

    # --- REMOVED: generate_speech_audio (now in TtsMixin) ---

    # --- REMOVED: _get_prompt_suggestions (now in SuggestionsMixin) ---
    
    # --- REMOVED: _get_follow_up_suggestions (now in SuggestionsMixin) ---

    async def process_prompt(
        self, 
        user_prompt: str, 
        user_id: str, 
        conversation_id: str,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        
        message_id = str(uuid.uuid4())
        plugin_context_data = {}

        # -----------------------------------------------------------------
        # --- Current Date Injection ---
        # -----------------------------------------------------------------
        now_utc = datetime.now(timezone.utc)
        current_date_string = now_utc.strftime("Current Date: %A, %B %d, %Y. Current UTC Time: %H:%M:%S Z")
        
        prompt_with_date = f"{current_date_string}\n\nUSER QUERY: {user_prompt}"
        # -----------------------------------------------------------------
        # --- END ---
        # -----------------------------------------------------------------


        # -----------------------------------------------------------------
        # --- Handle Profile-Specific Commands (Plugin Chain) ---
        # -----------------------------------------------------------------
        
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
            # Add other future plugins here
        ]
        
        plugin_results = await asyncio.gather(*plugin_tasks)
        
        for _prompt, data_payload in plugin_results:
            if data_payload:
                plugin_context_data.update(data_payload)
        
        # -----------------------------------------------------------------
        # --- Start of Core SAFi Process ---
        # -----------------------------------------------------------------
        
        # 1. FETCH MEMORIES
        memory_summary = db.fetch_conversation_summary(conversation_id)
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
        if temp_spirit_memory is None:
             dim = max(len(self.values), 1)
             temp_spirit_memory = {"turn": 0, "mu": np.zeros(dim)}

        spirit_feedback = build_spirit_feedback(
            mu=temp_spirit_memory.get("mu", np.zeros(len(self.values))),
            value_names=[v['value'] for v in self.values],
            drift=self.last_drift,
            recent_mu=list(self.mu_history)
        )

        # 2. INTELLECT (Generate Draft)
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
            err = self.intellect_engine.last_error or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            self.log.error(msg)
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed to produce an answer.", "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id, "suggestedPrompts": [] }

        # 3. WILL (Evaluate Draft)
        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        if D_t == "violation":
            self.log.warning(f"WillGate suppressed response. Reason: {E_t}")
            static_header = "🛑 **The answer was blocked**"
            
            suppression_message = f"""{static_header}
---

**Reason:** {E_t.strip()} """

            # --- NEW: Call from SuggestionsMixin ---
            S_p = await self._get_prompt_suggestions(
                user_prompt, 
                self.profile.get("will_rules", [])
            )
            # --- END NEW ---
            
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

        # 4. STORE & RESPOND (Save draft, run audits in background)
        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        
        snapshot = { 
            "t": int(temp_spirit_memory["turn"]) + 1, 
            "x_t": user_prompt, 
            "a_t": a_t, 
            "r_t": r_t, 
            "memory_summary": memory_summary,
            "retrieved_context": retrieved_context 
        }
        
        # 5. RUN BACKGROUND THREADS (Methods from BackgroundTasksMixin)
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()

        if getattr(self.config, "ENABLE_PROFILE_EXTRACTION", False):
            if hasattr(self.config, "SUMMARIZER_MODEL"): # Check if summarizer is configured
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

    # --- REMOVED: _run_audit_thread (now in BackgroundTasksMixin) ---
    
    # --- REMOVED: _run_summarization_thread (now in BackgroundTasksMixin) ---
    
    # --- REMOVED: _run_profile_update_thread (now in BackgroundTasksMixin) ---

    def _append_log(self, log_entry: Dict[str, Any]):
        """
        Appends a JSON log entry to the configured log file.
        (This method remains here as it's used by both the main
         process_prompt and the background threads)
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
            with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e: 
            self.log.error(f"Failed to write to log file {log_path}: {e}")