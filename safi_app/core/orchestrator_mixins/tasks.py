"""
Mixin for background task management (audits, summarization, etc.).
"""
from __future__ import annotations
import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from ...persistence import database as db
from ..services import LLMProvider 
# FIX: Updated import path. ConscienceAuditor is inside 'faculties', not 'core'.
from ..faculties import ConscienceAuditor

class BackgroundTasksMixin:
    """Mixin for background task management (audits, summarization)."""

    def _run_audit_thread(
        self, 
        snapshot: Dict[str, Any], 
        will_decision: str, 
        will_reason: str, 
        message_id: str, 
        spirit_feedback: str,
        retry_metadata: Optional[Dict[str, Any]] = None # New argument
    ):
        """
        Runs the Conscience and Spirit faculties in a background thread.
        CRITICAL FIX: Instantiates FRESH faculties to ensure thread-safety of Async Clients.
        """
        conn = None
        try:
            conn = db.get_db_connection()
            cursor = conn.cursor()

            memory = db.load_and_lock_spirit_memory(conn, cursor, self.active_profile_name)
            
            # 1. Ensure Dimension Compatibility
            required_dim = len(self.values)
            if memory is None:
                memory = {"turn": 0, "mu": np.zeros(required_dim)}
            else:
                current_mu = memory.get("mu")
                if current_mu is None or len(current_mu) != required_dim:
                    self.log.warning(f"Spirit dimension mismatch. Resetting Spirit Memory.")
                    memory = {"turn": 0, "mu": np.zeros(required_dim)}

            # 2. Run Conscience (THREAD SAFE REFACTOR)
            def detect_provider(model_name: str) -> str:
                if not model_name: return "groq"
                model_lower = model_name.lower()
                if model_lower.startswith("gpt-") or model_lower.startswith("o1-"): return "openai"
                if model_lower.startswith("claude-"): return "anthropic"
                if model_lower.startswith("gemini-"): return "gemini"
                if model_lower.startswith("deepseek-"): return "deepseek"
                if model_lower.startswith("mistral-") or model_lower.startswith("codestral-") or model_lower.startswith("open-mi"): return "mistral"
                return "groq"
            
            c_model = self.conscience.prompt_config.get("model") or getattr(self.config, "CONSCIENCE_MODEL") 
            
            thread_llm_config = {
                "providers": {
                    "openai": { "type": "openai", "api_key": self.config.OPENAI_API_KEY },
                    "groq": { "type": "openai", "api_key": self.config.GROQ_API_KEY, "base_url": "https://api.groq.com/openai/v1" },
                    "anthropic": { "type": "anthropic", "api_key": self.config.ANTHROPIC_API_KEY },
                    "gemini": { "type": "gemini", "api_key": self.config.GEMINI_API_KEY },
                },
                "routes": {
                    "conscience": {
                        "provider": getattr(self.config, "CONSCIENCE_PROVIDER", detect_provider(c_model)),
                        "model": c_model
                    }
                }
            }
            
            # Create fresh instances
            thread_provider = LLMProvider(thread_llm_config)
            thread_conscience = ConscienceAuditor(
                llm_provider=thread_provider,
                values=self.values,
                profile=self.profile,
                prompt_config=self.prompts.get("conscience_auditor", {})
            )
            
            async def run_conscience_safely():
                try:
                    return await thread_conscience.evaluate(
                        final_output=snapshot["a_t"], 
                        user_prompt=snapshot["x_t"], 
                        reflection=snapshot["r_t"],
                        retrieved_context=snapshot.get("retrieved_context", "")
                    )
                finally:
                    # Explicitly close clients to prevent "Event loop is closed" errors
                    # Iterate through clients in the provider and close them if they have a close method
                    for name, client in thread_provider.clients.items():
                        if hasattr(client, 'close'):
                            await client.close()
                        elif hasattr(client, 'aclose'): # httpx clients use aclose
                            await client.aclose()

            try:
                ledger = asyncio.run(run_conscience_safely())
            except Exception as e:
                self.log.exception(f"ConscienceAuditor.evaluate() failed in audit thread: {e}")
                ledger = []
            
            # 3. Get Follow-up Suggestions (SYNC call)
            S_p = []
            try:
                S_p = self._get_follow_up_suggestions(
                    user_prompt=snapshot["x_t"],
                    ai_response=snapshot["a_t"]
                )
            except Exception:
                self.log.exception("Follow-up suggester failed in audit thread")

            # 4. Compute Spirit
            S_t, note, mu_new, p_t, drift_val, mu_new_vector = self.spirit.compute(ledger, memory["mu"])
            self.last_drift = drift_val if drift_val is not None else 0.0
            
            # 5. Log and Save
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
                "p_t_vector": p_t.tolist() if hasattr(p_t, 'tolist') else p_t,
                "mu_t_vector": mu_new.tolist() if hasattr(mu_new, 'tolist') else mu_new,
                "memorySummary": snapshot.get("memory_summary") or "",
                "spiritFeedback": spirit_feedback,
                "retrievedContext": snapshot.get("retrieved_context", ""),
                "retryMetadata": retry_metadata, # Added metadata
                "policyId": (self.profile or {}).get("policy_id"),
                "orgId": snapshot.get("org_id") or (self.profile or {}).get("org_id"),
                "userId": snapshot.get("user_id")
            }
            self._append_log(log_entry)

            memory["turn"] += 1
            memory["mu"] = mu_new
            db.save_spirit_memory_in_transaction(cursor, self.active_profile_name, memory)
            self.mu_history.append(mu_new_vector)
            
            db.update_audit_results(message_id, ledger, S_t, note, self.active_profile_name, self.values, S_p)

            conn.commit()

        except Exception:
            self.log.exception("Unhandled exception in _run_audit_thread")
            if conn: conn.rollback()
        finally:
            if conn and conn.is_connected(): conn.close()

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        """Runs the summarization logic in a background thread using Sync client."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return
            
        summarizer_prompt_config = self.prompts.get("summarizer")
        if not summarizer_prompt_config: return

        try:
            system_prompt = summarizer_prompt_config["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")
            
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
            )
            db.update_conversation_summary(conversation_id, response.choices[0].message.content.strip())
        except Exception as e:
            self.log.warning(f"Summarization thread failed: {e}")

    def _run_profile_update_thread(self, user_id: str, current_profile_json: str, user_prompt: str, ai_response: str):
        """Runs the long-term user profile update logic in a background thread."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return
            
        profile_prompt_config = self.prompts.get("profile_extractor")
        if not profile_prompt_config: return

        try:
            system_prompt = profile_prompt_config["system_prompt"]
            content = (
                f"CURRENT_PROFILE_JSON:\n{current_profile_json}\n\n"
                f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
                "Return the new, updated JSON object."
            )
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            db.upsert_user_profile_memory(user_id, response.choices[0].message.content.strip())
            self.log.info(f"Successfully updated user profile for {user_id}")
        except Exception as e:
            self.log.warning(f"User profile update thread failed: {e}")