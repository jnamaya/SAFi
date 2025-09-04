from __future__ import annotations
import json
import threading
import uuid
import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional
import sys
from pathlib import Path
from openai import OpenAI

# SAFi faculties and helpers
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from ..persistence import database as db
from ..utils import dict_sha256

def _construct_spirit_feedback(mu_vector: np.ndarray, values: List[Dict[str, str]], last_drift: float) -> str:
    """
    Generates a natural-language feedback string from the spirit memory.
    """
    if mu_vector is None or len(mu_vector) == 0 or np.all(mu_vector == 0):
        return "No performance history yet. Strive to align with all declared values."
    strongest_value_index = np.argmax(mu_vector)
    weakest_value_index = np.argmin(mu_vector)
    strongest_value_name = values[strongest_value_index]['value']
    weakest_value_name = values[weakest_value_index]['value']
    feedback_parts = [f"Your long-term performance shows strong alignment with '{strongest_value_name}'."]
    if mu_vector[weakest_value_index] < 0.5:
        feedback_parts.append(f"Focus on improving your alignment with the value of '{weakest_value_name}' in your next response.")
    if last_drift > 0.2:
        feedback_parts.append("Note: Your most recent response showed a significant drift from your established baseline.")
    return " ".join(feedback_parts)


class SAFi:
    """
    Orchestrates Intellect, Will, Conscience, and Spirit using open-source models via Groq.
    """

    def __init__(
        self,
        config,
        value_profile_or_list: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        value_set: Optional[List[Dict[str, Any]]] = None,
    ):
        self.config = config
        groq_api_key = getattr(config, "GROQ_API_KEY", None)
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY must be set in the configuration.")

        self.groq_client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        prompts_path = Path(__file__).parent / "system_prompts.json"
        with prompts_path.open("r", encoding="utf-8") as f:
            self.prompts = json.load(f)

        if value_profile_or_list:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = [{"value": v["value"], "weight": v["weight"]} for v in self.profile["values"]]
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

        # --- CHANGE: Spirit memory is no longer loaded on initialization ---
        # It will be loaded within a database transaction during the audit process
        # to prevent race conditions.
        self.last_drift = 0.0

        self.intellect_engine = IntellectEngine(
            self.groq_client, model=getattr(config, "INTELLECT_MODEL"), profile=self.profile, prompt_config=self.prompts["intellect_engine"]
        )
        self.will_gate = WillGate(
            self.groq_client, model=getattr(config, "WILL_MODEL"), values=self.values, profile=self.profile, prompt_config=self.prompts["will_gate"]
        )
        self.conscience = ConscienceAuditor(
            self.groq_client, model=getattr(config, "CONSCIENCE_MODEL"), values=self.values, profile=self.profile, prompt_config=self.prompts["conscience_auditor"]
        )
        self.spirit = SpiritIntegrator(self.values, beta=getattr(config, "SPIRIT_BETA", 0.9))

        print(f"SAFi: profile '{self.active_profile_name}' active, running on Groq.")

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        memory_summary = db.fetch_conversation_summary(conversation_id)
        
        # --- CHANGE: We can't construct spirit feedback here anymore ---
        # Since spirit memory is loaded inside the audit thread's transaction,
        # we'll fetch it from a non-locking read just for the initial feedback.
        # This is a read-only operation, so it's safe from race conditions.
        temp_spirit_memory = db.load_spirit_memory(self.active_profile_name) # Assuming you create a non-locking version
        if temp_spirit_memory is None:
             dim = max(len(self.values), 1)
             temp_spirit_memory = {"turn": 0, "mu": np.zeros(dim)}

        spirit_feedback = _construct_spirit_feedback(temp_spirit_memory.get("mu"), self.values, self.last_drift)

        a_t, r_t = await self.intellect_engine.generate(user_prompt=user_prompt, memory_summary=memory_summary, spirit_feedback=spirit_feedback)
        message_id = str(uuid.uuid4())
        
        # Determine if this is the first message to create a title
        history_check = db.fetch_chat_history_for_conversation(conversation_id, limit=1)
        new_title = db.set_conversation_title_from_first_message(conversation_id, user_prompt) if not history_check else None

        db.insert_memory_entry(conversation_id, "user", user_prompt)

        if not a_t:
            err = self.intellect_engine.last_error or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            db.insert_memory_entry(conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return { "finalOutput": msg, "newTitle": new_title, "willDecision": "violation", "willReason": "Intellect failed to produce an answer.", "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id }

        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        if D_t == "violation":
            safe_response = f"This response was suppressed. Reason: {E_t}"
            db.insert_memory_entry(conversation_id, "ai", safe_response, message_id=message_id, audit_status="complete")
            self._append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "userPrompt": user_prompt,
                "finalOutput": safe_response,
                "intellectDraft": a_t,
                "willDecision": D_t,
                "willReason": E_t,
                "conscienceLedger": [],
            })
            return { "finalOutput": safe_response, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "conscienceLedger": [], "messageId": message_id }

        db.insert_memory_entry(conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")
        snapshot = { "t": int(temp_spirit_memory["turn"]) + 1, "x_t": user_prompt, "a_t": a_t, "r_t": r_t, "memory_summary": memory_summary }
        threading.Thread(target=self._run_audit_thread, args=(snapshot, D_t, E_t, message_id, spirit_feedback), daemon=True).start()
        threading.Thread(target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True).start()

        return { "finalOutput": a_t, "newTitle": new_title, "willDecision": D_t, "willReason": E_t, "activeProfile": self.active_profile_name, "activeValues": self.values, "messageId": message_id }

    def _run_audit_thread(self, snapshot: Dict[str, Any], will_decision: str, will_reason: str, message_id: str, spirit_feedback: str):
        # --- CHANGE: Implemented transaction handling for spirit memory ---
        # This entire block now runs within a database transaction to prevent
        # the spirit memory update race condition.
        conn = None
        try:
            conn = db.get_db_connection()
            cursor = conn.cursor()

            # Load and lock the spirit memory for the current profile
            memory = db.load_and_lock_spirit_memory(conn, cursor, self.active_profile_name)
            dim = max(len(self.values), 1)
            if memory is None:
                memory = {"turn": 0, "mu": np.zeros(dim)}

            # Perform the audit (CPU-bound, safe within transaction)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ledger = loop.run_until_complete(self.conscience.evaluate(final_output=snapshot["a_t"], user_prompt=snapshot["x_t"], reflection=snapshot["r_t"]))
            loop.close()

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
                "spiritFeedback": spirit_feedback
            }
            self._append_log(log_entry)

            # Update memory state and save it within the transaction
            memory["turn"] += 1
            memory["mu"] = np.array(mu_new)
            db.save_spirit_memory_in_transaction(cursor, self.active_profile_name, memory)
            
            # The audit results update can also happen inside the transaction
            db.update_audit_results(message_id, ledger, S_t, note, self.active_profile_name, self.values)

            # Commit the transaction to release the lock and save changes
            conn.commit()

        except Exception as e:
            # If anything fails, roll back the entire transaction
            if conn:
                conn.rollback()
            print(f"--- ERROR IN AUDIT THREAD ---", file=sys.stderr); import traceback; traceback.print_exc(file=sys.stderr)
        finally:
            # Always ensure the connection is closed
            if conn and conn.is_connected():
                conn.close()

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        try:
            system_prompt = self.prompts["summarizer"]["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")
            response = self.groq_client.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
            )
            new_summary = response.choices[0].message.content.strip()
            db.update_conversation_summary(conversation_id, new_summary)
        except Exception as e:
            print(f"--- ERROR IN SUMMARIZATION THREAD ---", file=sys.stderr); import traceback; traceback.print_exc(file=sys.stderr)

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
            with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e: print(f"Log write error to {log_path}: {e}", file=sys.stderr)
