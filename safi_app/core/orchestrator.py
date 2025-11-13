from __future__ import annotations
import json
import threading
import uuid
import asyncio
import numpy as np
from datetime import datetime, timezone # <-- ADDED datetime import
from typing import List, Dict, Any, Union, Optional
from pathlib import Path
import logging
import httpx
import re
from bs4 import BeautifulSoup
import hashlib # <-- ADDED FOR CACHING
import os # <-- ADDED FOR CACHING
import time # <-- ADDED FOR CACHING

from openai import OpenAI, AsyncOpenAI
from anthropic import Anthropic, AsyncAnthropic
import google.generativeai as genai

from collections import deque
from .feedback import build_spirit_feedback
from ..persistence import database as db
from ..utils import dict_sha256
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from .plugins.bible_scholar_readings import handle_bible_scholar_commands
from .plugins.fiduciary_data import handle_fiduciary_commands

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class SAFi:
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
            self.openai_client_sync = OpenAI(api_key=config.OPENAI_API_KEY) # <-- ADDED SYNC CLIENT FOR TTS

        else:
            self.openai_client_sync = None
        
        if config.ANTHROPIC_API_KEY:
            self.clients["anthropic"] = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.clients["gemini"] = "configured"
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

    # --- NEW METHOD: TTS Audio Generation with Caching ---
    def generate_speech_audio(self, text: str) -> Optional[bytes]:
        """
        Generates MP3 audio for the given text using OpenAI TTS, with local caching.
        Returns the audio content as bytes, or None on failure.
        """
        if not self.openai_client_sync:
            self.log.error("OpenAI synchronous client not initialized. Cannot use TTS.")
            return None

        tts_model = self.config.TTS_MODEL
        tts_voice = self.config.TTS_VOICE
        cache_dir = self.config.TTS_CACHE_DIR

        # 1. Create a unique cache key (hash of text + model + voice)
        cache_key_data = f"{text}|{tts_model}|{tts_voice}"
        cache_hash = hashlib.sha256(cache_key_data.encode('utf-8')).hexdigest()
        cache_path = Path(cache_dir) / f"{cache_hash}.mp3"
        
        # 2. Check Cache
        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    self.log.info(f"TTS Cache hit for text: {text[:30]}...")
                    return f.read()
            except IOError as e:
                self.log.error(f"Failed to read cached MP3 file {cache_path}: {e}")
                # Continue to re-generate if reading fails

        self.log.info(f"TTS Cache miss for text: {text[:30]}... Calling OpenAI API.")

        # 3. Generate Audio via OpenAI API
        try:
            # Ensure the cache directory exists before writing
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            
            response = self.openai_client_sync.audio.speech.create(
                model=tts_model,
                voice=tts_voice,
                input=text,
                response_format="mp3" # Standard high-quality MP3
            )

            # 4. Save to Cache and return content
            audio_content = response.content # The response object has the audio data directly
            
            with open(cache_path, "wb") as f:
                f.write(audio_content)
            
            self.log.info(f"TTS audio saved to cache: {cache_path}")
            return audio_content

        except Exception as e:
            self.log.error(f"OpenAI TTS API call failed: {e}")
            return None
    # --- END NEW METHOD ---

    async def _get_prompt_suggestions(self, user_prompt: str, will_rules: List[str]) -> List[str]:
        """
        Uses a fast model (Groq) to generate prompt suggestions after a violation.
        """
        suggestion_client = self.clients.get("groq")
        if not suggestion_client:
            self.log.warning("Groq client not configured. Cannot generate prompt suggestions.")
            return []

        prompt_config = self.prompts.get("suggestion_engine")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'suggestion_engine' prompt found. Cannot generate suggestions.")
            return []

        # Use the model name from the user's request, or a fast default
        suggestion_model = "llama-3.1-8b-instant" 

        try:
            system_prompt = prompt_config["system_prompt"]
            rules_string = "\n".join(f"- {r}" for r in will_rules)
            
            content = (
                f"**Here are the rules the user violated:**\n{rules_string}\n\n"
                f"**Here is the user's original (blocked) prompt:**\n{user_prompt}\n\n"
                "Please provide compliant suggestions."
            )

            # --- ADDED LOGGING ---
            self.log.info(f"Sending prompt to suggestion engine (model: {suggestion_model}):\nSystem: {system_prompt}\nUser Content: {content}")
            # --- END ADDED LOGGING ---

            response = await suggestion_client.chat.completions.create(
                model=suggestion_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=0.7, # A bit of creativity
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            
            response_json = response.choices[0].message.content or "{}"
            
            # --- NEW: Log the raw response ---
            self.log.info(f"Raw response from suggestion engine: {response_json}")
            # --- END NEW ---

            # --- FIX: Replace greedy regex with robust find/rfind ---
            start = response_json.find('{')
            end = response_json.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                json_text = response_json[start:end+1]
            else:
                self.log.warning(f"Suggestion engine returned non-JSON: {response_json}")
                return []
            
            obj = json.loads(json_text)
            # --- END FIX ---
            
            suggestions = obj.get("suggestions", [])
            
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return suggestions
            else:
                self.log.warning(f"Suggestion engine returned invalid data: {response_json}")
                return []

        except Exception as e:
            self.log.error(f"Failed to get prompt suggestions: {e}")
            return []
    # --- END NEW METHOD ---

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        
        message_id = str(uuid.uuid4())
        plugin_context_data = {}

        # -----------------------------------------------------------------
        # --- NEW: Current Date Injection ---
        # -----------------------------------------------------------------
        # Get the current UTC date and time
        now_utc = datetime.now(timezone.utc)
        current_date_string = now_utc.strftime("Current Date: %A, %B %d, %Y. Current UTC Time: %H:%M:%S Z")
        
        # We inject this into the spirit feedback string to be processed by IntellectEngine
        # IntellectEngine.generate expects `spirit_feedback` to be the coaching note, 
        # so we will prepend the current date string to the *user_prompt* for simplicity,
        # or update IntellectEngine.generate to accept a dedicated date parameter.
        # Since IntellectEngine.generate currently only accepts `user_prompt`, `memory_summary`, 
        # and `spirit_feedback`, we'll modify the `user_prompt` here for the quickest fix, 
        # assuming the `spirit_feedback` isn't designed to hold real-time data.
        
        prompt_with_date = f"{current_date_string}\n\nUSER QUERY: {user_prompt}"
        # -----------------------------------------------------------------
        # --- END NEW: Current Date Injection ---
        # -----------------------------------------------------------------


        # -----------------------------------------------------------------
        # --- Handle Profile-Specific Commands (Plugin Chain) ---
        # -----------------------------------------------------------------
        
        # 1. Check for Bible Scholar commands
        _, readings_data = await handle_bible_scholar_commands(
            user_prompt, 
            self.active_profile_name, 
            self.log
        )
        if readings_data:
            plugin_context_data.update(readings_data)
            
        # 2. Check for Fiduciary commands
        groq_client = self.clients.get("groq")
        
        _, fiduciary_data = await handle_fiduciary_commands(
            user_prompt,
            self.active_profile_name,
            self.log,
            groq_client
        )
        if fiduciary_data:
            plugin_context_data.update(fiduciary_data)
        
        # -----------------------------------------------------------------
        # --- Start of Core SAFi Process ---
        # -----------------------------------------------------------------
        
        # 1. FETCH MEMORIES
        # Get short-term (conversation) memory
        memory_summary = db.fetch_conversation_summary(conversation_id)
        
        # Get long-term (user) memory
        current_profile_json = db.fetch_user_profile_memory(user_id)
        
        # Get spirit (ethical) memory
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
            user_prompt=prompt_with_date, # <-- Use the prompt with the current date
            memory_summary=memory_summary, 
            spirit_feedback=spirit_feedback,
            plugin_context=plugin_context_data,
            user_profile_json=current_profile_json
        )
        
        history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
        new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None

        db.insert_memory_entry(conversation_id, "user", user_prompt)

        if not a_t:
            err = self.intellect_engine.last_error or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            self.log.error(msg)
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            # --- MODIFIED: Ensure suggestedPrompts (empty list) is present ---
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed to produce an answer.", "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id, "suggestedPrompts": [] }

        # 3. WILL (Evaluate Draft)
        # --- MODIFIED: Expect two return values ---
        # Note: We must pass the *original* user prompt here, not the one with the date injection.
        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)
        # S_p (suggested_prompts) is no longer returned here

        if D_t == "violation":
            self.log.warning(f"WillGate suppressed response. Reason: {E_t}")
            static_header = "🛑 **The answer was blocked**"
            
            suppression_message = f"""{static_header}
---

**Reason:** {E_t.strip()} """

            # --- NEW: Call the fast suggestion engine ---
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
            # --- MODIFIED: Include suggestedPrompts from the new function ---
            return { 
                "finalOutput": suppression_message, 
                "newTitle": new_title, 
                "willDecision": D_t, 
                "willReason": E_t, 
                "activeProfile": self.active_profile_name, 
                "activeValues": self.values, 
                "conscienceLedger": [], 
                "messageId": message_id,
                "suggestedPrompts": S_p # <-- NEWLY GENERATED FIELD
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
        
        # 5. RUN BACKGROUND THREADS
        # Run Conscience & Spirit audit
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        
        # Run short-term memory (summarizer)
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()

        # Run long-term memory (profile extractor)
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_profile_update_thread, args=(user_id, current_profile_json, user_prompt, a_t), daemon=True).start()

        # --- MODIFIED: Include empty suggestedPrompts list for approved responses ---
        return { 
            "finalOutput": a_t, 
            "newTitle": new_title, 
            "willDecision": D_t, 
            "willReason": E_t, 
            "activeProfile": self.active_profile_name, 
            "activeValues": self.values, 
            "messageId": message_id,
            "suggestedPrompts": [] # <-- FIELD IS PRESENT BUT EMPTY
        }

    def _run_audit_thread(self, snapshot: Dict[str, Any], will_decision: str, will_reason: str, message_id: str, spirit_feedback: str):
        """
        Runs the Conscience and Spirit faculties in a background thread.
        """
        conn = None
        try:
            conn = db.get_db_connection()
            cursor = conn.cursor()

            memory = db.load_and_lock_spirit_memory(conn, cursor, self.active_profile_name)
            dim = max(len(self.values), 1)
            if memory is None:
                memory = {"turn": 0, "mu": np.zeros(dim)}

            try:
                ledger = asyncio.run(self.conscience.evaluate(
                    final_output=snapshot["a_t"], 
                    user_prompt=snapshot["x_t"], 
                    reflection=snapshot["r_t"],
                    retrieved_context=snapshot.get("retrieved_context", "")
                ))
            except Exception as e:
                self.log.exception("ConscienceAuditor.evaluate() failed in audit thread")
                ledger = []
            
            S_t, note, mu_new, p_t, drift_val = self.spirit.compute(ledger, memory.get("mu", np.zeros(len(self.values))))
            self.last_drift = drift_val if drift_val is not None else 0.0
            
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "t": snapshot["t"],
                "userPrompt": snapshot["x_t"],
                "intellectDraft": snapshot["a_t"],
                "intellectReflection": snapshot["r_t"] or "",
                "finalOutput": snapshot["a_t"],
                "willDecision": will_decision,
                "willReason": will_reason,
                "conscienceLedger": ledger,
                "spiritScore": S_t,
                "spiritNote": note,
                "drift": drift_val,
                "p_t_vector": p_t.tolist(),
                "mu_t_vector": mu_new.tolist(),
                "memorySummary": snapshot.get("memory_summary") or "",
                "spiritFeedback": spirit_feedback,
                "retrievedContext": snapshot.get("retrieved_context", "")
            }
            self._append_log(log_entry)

            memory["turn"] += 1
            memory["mu"] = np.array(mu_new)
            db.save_spirit_memory_in_transaction(cursor, self.active_profile_name, memory)
            
            self.mu_history.append(mu_new)
            
            db.update_audit_results(message_id, ledger, S_t, note, self.active_profile_name, self.values)

            conn.commit()

        except Exception as e:
            self.log.exception("Unhandled exception in _run_audit_thread")
            if conn:
                conn.rollback()
        finally:
            if conn and conn.is_connected():
                conn.close()

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        """
        Runs the summarization logic in a background thread.
        """
        if not hasattr(self, 'groq_client_sync'):
            return
            
        summarizer_prompt_config = self.prompts.get("summarizer")
        if not summarizer_prompt_config or "system_prompt" not in summarizer_prompt_config:
            self.log.warning("No 'summarizer' prompt found. Skipping summarization.")
            return

        try:
            system_prompt = summarizer_prompt_config["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")
            
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
            )

            new_summary = response.choices[0].message.content.strip()
            db.update_conversation_summary(conversation_id, new_summary)
        except Exception as e:
            self.log.warning(f"Summarization thread failed: {e}")

    def _run_profile_update_thread(self, user_id: str, current_profile_json: str, user_prompt: str, ai_response: str):
        """
        Runs the long-term user profile update logic in a background thread.
        """
        if not hasattr(self, 'groq_client_sync'):
            return
            
        profile_prompt_config = self.prompts.get("profile_extractor")
        if not profile_prompt_config or "system_prompt" not in profile_prompt_config:
            self.log.warning("No 'profile_extractor' prompt found. Skipping profile update.")
            return

        try:
            system_prompt = profile_prompt_config["system_prompt"]
            
            # Create the prompt for the extractor
            content = (
                f"CURRENT_PROFILE_JSON:\n{current_profile_json}\n\n"
                f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
                "Return the new, updated JSON object."
            )
            
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL"), # Use the fast summarizer model
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            new_profile_json = response.choices[0].message.content.strip()
            
            # Save the new profile to the database
            db.upsert_user_profile_memory(user_id, new_profile_json)
            self.log.info(f"Successfully updated user profile for {user_id}")

        except Exception as e:
            self.log.warning(f"User profile update thread failed: {e}")

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
            with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e: 
            self.log.error(f"Failed to write to log file {log_path}: {e}")