"""
Mixin for background task management (audits, summarization, etc.).
"""
from __future__ import annotations
import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any
from ...persistence import database as db

class BackgroundTasksMixin:
    """Mixin for background task management (audits, summarization)."""

    def _run_audit_thread(self, snapshot: Dict[str, Any], will_decision: str, will_reason: str, message_id: str, spirit_feedback: str):
        """
        Runs the Conscience and Spirit faculties in a background thread.
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

            # 2. Run Conscience (This is Async, so we need a loop for THIS part only)
            try:
                ledger = asyncio.run(self.conscience.evaluate(
                    final_output=snapshot["a_t"], 
                    user_prompt=snapshot["x_t"], 
                    reflection=snapshot["r_t"],
                    retrieved_context=snapshot.get("retrieved_context", "")
                ))
            except Exception:
                self.log.exception("ConscienceAuditor.evaluate() failed in audit thread")
                ledger = []
            
            # 3. Get Follow-up Suggestions (SYNC call now - no asyncio.run needed)
            S_p = []
            try:
                # Direct synchronous call to avoid Event Loop issues
                S_p = self._get_follow_up_suggestions(
                    user_prompt=snapshot["x_t"],
                    ai_response=snapshot["a_t"]
                )
            except Exception:
                self.log.exception("Follow-up suggester failed in audit thread")

            # 4. Compute Spirit
            S_t, note, mu_new, p_t, drift_val = self.spirit.compute(ledger, memory["mu"])
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