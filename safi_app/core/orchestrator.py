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
        
        if config.ANTHROPIC_API_KEY:
            self.clients["anthropic"] = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.clients["gemini"] = "configured"
            except Exception as e:
                self.log.warning(f"Gemini API key configuration failed: {e}. Gemini models will be unavailable.")
        
        prompts_path = Path(__file__).parent / "system_prompts.json"
        with prompts_path.open("r", encoding="utf-8") as f:
            self.prompts = json.load(f)

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
            prompt_config=self.prompts["intellect_engine"]
        )
        self.will_gate = WillGate(
            will_client, 
            provider_name=will_provider,
            model=will_model_to_use, 
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts["will_gate"]
        )
        self.conscience = ConscienceAuditor(
            conscience_client, 
            provider_name=conscience_provider,
            model=conscience_model_to_use, 
            values=self.values, 
            profile=self.profile, 
            prompt_config=self.prompts["conscience_auditor"]
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

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        
        plugin_context_data = {}

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
        # --- NEW: Handle Stock Data with Hybrid Display ---
        # -----------------------------------------------------------------
        message_id = str(uuid.uuid4())
        
        if "stock_data" in plugin_context_data:
            stock_data = plugin_context_data["stock_data"]
            
            # Helper to format values
            def format_stock_value(key, value):
                if value is None: return "N/A"
                try:
                    if key == "Dividend Yield":
                        return f"{float(value) * 100:.2f}%"
                    if key in ["P/E Ratio (TTM)", "Beta (5Y Monthly)"]:
                        return f"{float(value):.2f}"
                    if key in ["Market Cap", "Volume", "Average Volume"]:
                         num = int(value)
                         if num > 1_000_000_000_000: return f"{num / 1_000_000_000_000:.2f}T"
                         if num > 1_000_000_000: return f"{num / 1_000_000_000:.2f}B"
                         if num > 1_000_000: return f"{num / 1_000_000:.2f}M"
                         return f"{num:,}"
                    if key == "Current Price":
                        return f"{float(value):,.2f}"
                    if key == "Price Change":
                        change = float(value)
                        sign = "+" if change > 0 else ""
                        return f"{sign}{change:,.2f}"
                except (ValueError, TypeError):
                    pass # Fallback to string
                return str(value)
            
            # --- New Text-Based Formatting ---
            
            company = stock_data.get('Company Name', 'N/A')
            ticker = stock_data.get('Ticker Symbol', 'N/A')
            price_val = stock_data.get('Current Price')
            prev_close_val = stock_data.get('Previous Close') # Key for "yesterday's price"
            volume_val = stock_data.get('Volume')
            avg_volume_val = stock_data.get('Average Volume')
            beta_val = stock_data.get('Beta (5Y Monthly)')
            
            price_str = format_stock_value('Current Price', price_val)
            prev_close_str = format_stock_value('Current Price', prev_close_val) # Use same formatting as price
            volume_str = format_stock_value('Volume', volume_val)
            avg_volume_str = format_stock_value('Average Volume', avg_volume_val)
            beta_str = format_stock_value('Beta (5Y Monthly)', beta_val)
            
            output_lines = [f"Here is the stock information for {company} ({ticker}):"]
            
            if price_str != "N/A":
                output_lines.append(f"- **Today's Price:** ${price_str}")
            
            if prev_close_str != "N/A":
                output_lines.append(f"- **Yesterday's Close:** ${prev_close_str}")

            if volume_str != "N/A":
                output_lines.append(f"- **Volume:** {volume_str}")
            
            if avg_volume_str != "N/A":
                output_lines.append(f"- **Average Volume:** {avg_volume_str}")
            
            if beta_str != "N/A":
                output_lines.append(f"- **Beta (5Y Monthly):** {beta_str}")
            
            disclaimer = "\n\n*This is not financial advice. For investment decisions, please consult with a licensed financial advisor.*"

            data_text = "\n".join(output_lines) + disclaimer
            
            # Get memory for audit/summarization
            memory_summary = db.fetch_conversation_summary(conversation_id)
            temp_spirit_memory = db.load_spirit_memory(self.active_profile_name)
            if temp_spirit_memory is None:
                dim = max(len(self.values), 1)
                temp_spirit_memory = {"turn": 0, "mu": np.zeros(dim)}

            # Set final output to just the data table
            final_output = data_text
            
            # Define variables for audit thread
            r_t = "Stock data display."
            retrieved_context = ""
            spirit_feedback = None # Set to None as it's no longer generated
            
            # Save to database
            history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
            new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None
            
            db.insert_memory_entry(conversation_id, "user", user_prompt)
            db.insert_memory_entry(conversation_id, "ai", final_output, message_id=message_id, audit_status="pending")
            
            # Run audit in background
            snapshot = {
                "t": int(temp_spirit_memory["turn"]) + 1,
                "x_t": user_prompt,
                "a_t": final_output,
                "r_t": r_t,
                "memory_summary": memory_summary,
                "retrieved_context": retrieved_context
            }
            threading.Thread(
                target=self._run_audit_thread,
                args=(snapshot, "approve", "Stock data display", message_id, spirit_feedback),
                daemon=True
            ).start()
            
            if hasattr(self, 'groq_client_sync'):
                threading.Thread(
                    target=self._run_summarization_thread,
                    args=(conversation_id, memory_summary, user_prompt, final_output),
                    daemon=True
                ).start()
            
            return {
                "finalOutput": final_output,
                "newTitle": new_title,
                "willDecision": "approve",
                "willReason": "Stock data display",
                "activeProfile": self.active_profile_name,
                "activeValues": self.values,
                "conscienceLedger": [],
                "messageId": message_id
            }
        
        # -----------------------------------------------------------------
        # --- END OF STOCK DATA HANDLING ---
        # --- Continue with normal processing for non-stock queries ---
        # -----------------------------------------------------------------
        
        memory_summary = db.fetch_conversation_summary(conversation_id)
        
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

        a_t, r_t, retrieved_context = await self.intellect_engine.generate(
            user_prompt=user_prompt, 
            memory_summary=memory_summary, 
            spirit_feedback=spirit_feedback,
            plugin_context=plugin_context_data
        )
        
        history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
        new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None

        db.insert_memory_entry(conversation_id, "user", user_prompt)

        if not a_t:
            err = self.intellect_engine.last_error or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            self.log.error(msg)
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed to produce an answer.", "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id }

        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        if D_t == "violation":
            self.log.warning(f"WillGate suppressed response. Reason: {E_t}")
            static_header = "🛑 **The answer was blocked**"
            suppression_message = f"""{static_header}
---

**Reason:** {E_t.strip()} """

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
            return { "finalOutput": suppression_message, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id }

        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        
        snapshot = { 
            "t": int(temp_spirit_memory["turn"]) + 1, 
            "x_t": user_prompt, 
            "a_t": a_t, 
            "r_t": r_t, 
            "memory_summary": memory_summary,
            "retrieved_context": retrieved_context 
        }
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        
        if hasattr(self, 'groq_client_sync'):
            threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()

        return { "finalOutput": a_t, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "messageId": message_id }

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
        
        try:
            system_prompt = self.prompts["summarizer"]["system_prompt"]
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