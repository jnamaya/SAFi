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
from concurrent.futures import ThreadPoolExecutor

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
# --- Import Refactored Services ---
from .services import LLMProvider, RAGService, MCPManager

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
        conscience_model: Optional[str] = None,
        spirit_beta: Optional[float] = None
    ):
        """
        Initializes the SAFi orchestration system.
        """
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        
        # --- PRODUCTION FIX: ThreadPool for Background Tasks ---
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="SafiWorker")

        # --- Helper: Auto-detect Provider ---
        def detect_provider(model_name: str) -> str:
            if not model_name: return "groq"
            model_lower = model_name.lower()
            if model_lower.startswith("gpt-") or model_lower.startswith("o1-"): return "openai"
            if model_lower.startswith("claude-"): return "anthropic"
            if model_lower.startswith("gemini-"): return "gemini"
            if model_lower.startswith("deepseek-"): return "deepseek"
            if model_lower.startswith("mistral-") or model_lower.startswith("codestral-") or model_lower.startswith("open-mi"): return "mistral"
            return "groq" 

        i_model = intellect_model or getattr(config, "INTELLECT_MODEL")
        w_model = will_model or getattr(config, "WILL_MODEL")
        c_model = conscience_model or getattr(config, "CONSCIENCE_MODEL")

        # --- 1. Construct LLM Configuration ---
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
                "deepseek": {
                    "type": "openai",
                    "api_key": getattr(config, "DEEPSEEK_API_KEY", ""),
                    "base_url": "https://api.deepseek.com"
                },
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
        
        self.llm_provider = LLMProvider(llm_config)
        self.clients = self.llm_provider.clients

        # --- 2. RESTORE SYNC CLIENTS ---
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
        
        # --- LOGGING FIX: Use 'key' if available, else sanitized 'name' ---
        raw_key = (self.profile or {}).get("key")
        raw_name = (self.profile or {}).get("name", "custom")
        
        if raw_key:
             self.active_profile_name = raw_key
        else:
             import re
             # Sanitize name: replace non-alphanumeric with underscore
             self.active_profile_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', raw_name).lower()

        self.last_drift = 0.0
        self.mu_history = deque(maxlen=5)

        self.rag_service = RAGService(
            knowledge_base_name=(self.profile or {}).get("rag_knowledge_base")
        )

        # Initialize MCP Manager
        # We assume specific tools are enabled via config or default
        mcp_config = getattr(config, "MCP_CONFIG", {})
        self.mcp_manager = MCPManager(mcp_config)
        
        self.intellect_engine = IntellectEngine(
            llm_provider=self.llm_provider,
            profile=self.profile, 
            prompt_config=self.prompts.get("intellect_engine", {}),
            mcp_manager=self.mcp_manager
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

        beta_val = spirit_beta if spirit_beta is not None else getattr(config, "SPIRIT_BETA", 0.9)
        self.spirit = SpiritIntegrator(self.values, beta=beta_val)

    def __del__(self):
        try:
            self.executor.shutdown(wait=False)
        except Exception:
            pass

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
        plugin_client = self.clients.get("groq") 
        
        plugin_tasks = [
            handle_bible_scholar_commands(user_prompt, self.active_profile_name, self.log),
            # handle_fiduciary_commands(user_prompt, self.active_profile_name, self.log, plugin_client)  # Disabled for MCP
        ]
        plugin_results = await asyncio.gather(*plugin_tasks)
        for _, data in plugin_results:
            if data: plugin_context_data.update(data)
        
        # Memories
        memory_summary = db.fetch_conversation_summary(conversation_id)
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
        if temp_spirit_memory is None:
             temp_spirit_memory = {}
        
        # --- FIX: Resolve Vector from Memory (Dict or List) for Feedback ---
        mu_memory = temp_spirit_memory.get("mu", {})

        current_mu = np.zeros(len(self.values))
        
        if isinstance(mu_memory, (list, np.ndarray)):
            # Legacy: Padding/Truncation
            old_arr = np.array(mu_memory)
            common_len = min(len(current_mu), old_arr.shape[0])
            current_mu[:common_len] = old_arr[:common_len]
        else:
            # Modern: Key Lookup
            # Sanitize value names for lookup
            from .faculties.utils import _norm_label
            for i, v in enumerate(self.values):
                v_name = v.get("value") or v.get("name") or "Unknown"
                current_mu[i] = mu_memory.get(_norm_label(v_name), 0.0)

        spirit_feedback = build_spirit_feedback(
            mu=current_mu,
            value_names=[v.get('value') or v.get('name') for v in self.values],
            drift=self.last_drift,
            recent_mu=list(self.mu_history)
        )

        # --- 1. First Pass: Intellect Generation ---
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

        # --- 2. First Pass: Will Evaluation ---
        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        # --- Retry Metadata Tracking ---
        retry_metadata = {
            "was_retried": False,
            "original_draft": None,
            "violation_reason": None
        }

        # --- 3. Reflexion Loop (Single Retry) ---
        if D_t == "violation":
            self.log.info(f"Will blocked first draft. Reason: {E_t}. Attempting Reflexion Retry.")
            
            # Record that we are retrying
            retry_metadata["was_retried"] = True
            retry_metadata["original_draft"] = a_t
            retry_metadata["violation_reason"] = E_t

            retry_template = self.prompts.get("will_retry", {}).get("template")
            if not retry_template:
                retry_template = (
                    "{original_prompt_with_date}\n\n"
                    "--- INTERNAL GOVERNANCE FEEDBACK ---\n"
                    "Your previous draft response was blocked by the 'Will' gatekeeper.\n"
                    "Your Blocked Draft:\n\"\"\"\n{blocked_draft}\n\"\"\"\n\n"
                    "Violation Reason:\n{violation_reason}\n\n"
                    "INSTRUCTION: Rewrite your response to be fully compliant with the persona values and rules. "
                    "Analyze your blocked draft to understand what triggered the violation. "
                    "Address the user's intent safely. Do not mention this internal system correction or the block."
                )
            
            retry_prompt = retry_template.format(
                original_prompt_with_date=prompt_with_date,
                blocked_draft=a_t,
                violation_reason=E_t
            )

            a_t_retry, r_t_retry, context_retry = await self.intellect_engine.generate(
                user_prompt=retry_prompt, 
                memory_summary=memory_summary,
                spirit_feedback=spirit_feedback,
                plugin_context=plugin_context_data, 
                user_profile_json=current_profile_json,
                user_name=user_name
            )
            
            if a_t_retry:
                D_t_retry, E_t_retry = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t_retry)
                
                if D_t_retry == "approve":
                    self.log.info("Reflexion Retry Successful. Proceeding with safe response.")
                    a_t = a_t_retry
                    r_t = r_t_retry
                    retrieved_context = context_retry
                    D_t = D_t_retry
                    E_t = E_t_retry
                else:
                    self.log.info(f"Reflexion Retry Failed. Still blocked. Reason: {E_t_retry}")
                    E_t = f"Original violation: {E_t}. Retry violation: {E_t_retry}"
            else:
                self.log.warning("Reflexion Retry failed to generate text.")

        # --- 4. Final Decision (Block or Allow) ---
        if D_t == "violation":
            suppression_message = f"🛑 **Blocked**\n\nReason: {E_t}"
            S_p = await self._get_prompt_suggestions(user_prompt, (self.profile or {}).get("will_rules", []))
            db.insert_memory_entry(conversation_id, "ai", suppression_message, message_id=message_id, audit_status="complete") 
            self._append_log({
                "userPrompt": user_prompt, 
                "blockedDraft": a_t,
                "finalOutput": suppression_message, 
                "willDecision": D_t, 
                "willReason": E_t, 
                "willReason": E_t, 
                "retryMetadata": retry_metadata, 
                "policyId": (self.profile or {}).get("policy_id"),
                "orgId": (self.profile or {}).get("org_id"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return { "finalOutput": suppression_message, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "suggestedPrompts": S_p, "messageId": message_id }

        # --- 5. Success: Save and Audit ---
        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        
        snapshot = { "t": int(temp_spirit_memory.get("turn", 0)) + 1, "x_t": user_prompt, "a_t": a_t, "r_t": r_t, "memory_summary": memory_summary, "retrieved_context": retrieved_context }
        
        # Pass retry_metadata to the audit thread
        self.executor.submit(self._run_audit_thread, snapshot, D_t, E_t, message_id, spirit_feedback, retry_metadata)
        
        if hasattr(self, 'groq_client_sync'):
            self.executor.submit(self._run_summarization_thread, conversation_id, memory_summary, user_prompt, a_t)
        
        if getattr(self.config, "ENABLE_PROFILE_EXTRACTION", False):
            if hasattr(self.config, "SUMMARIZER_MODEL"):
                 self.executor.submit(self._run_profile_update_thread, user_id, current_profile_json, user_prompt, a_t)

        return { 
            "finalOutput": a_t, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, 
            "activeProfile": self.active_profile_name, "activeValues": self.values, "messageId": message_id, "suggestedPrompts": [] 
        }

    def _append_log(self, log_entry: Dict[str, Any]):
        log_path = Path(self.log_dir)
        if self.log_template:
            try:
                # Mock timestamp matching format in Orchestrator
                ts = datetime.fromisoformat(log_entry.get("timestamp").replace("Z", "+00:00"))
                fname = ts.strftime(self.log_template.format(profile=self.active_profile_name))
                log_path = log_path / fname
            except Exception as e:
                self.log.error(f"Failed to generate log filename for {self.active_profile_name}: {e}")
                return

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f: 
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            self.log.error(f"Failed to write log entry to {log_path}: {e}")
