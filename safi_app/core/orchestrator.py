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

# Model clients
from openai import OpenAI
import anthropic

# SAFi faculties and helpers
from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from ..persistence import database as db
from ..utils import dict_sha256


class SAFi:
    """
    Orchestrates Intellect, Will, Conscience, and Spirit.
    Pulls config and profile, routes a prompt through the pipeline,
    persists memory, and writes JSONL logs.
    """

    def __init__(
        self,
        config,
        value_profile_or_list: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        value_set: Optional[List[Dict[str, Any]]] = None,
        initial_memory=None,
    ):
        self.config = config

        # API keys must be present for both providers
        openai_api_key = getattr(config, "OPENAI_API_KEY", None)
        anthropic_api_key = getattr(config, "ANTHROPIC_API_KEY", None)
        if not openai_api_key or not anthropic_api_key:
            raise ValueError("Both OPENAI_API_KEY and ANTHROPIC_API_KEY must be set")

        self.openai_client = OpenAI(api_key=openai_api_key)
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)

        # Value profile can be a dict with "values" or a raw list of {value, weight}
        if value_profile_or_list is not None:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = [{"value": v["value"], "weight": v["weight"]} for v in self.profile["values"]]
            elif isinstance(value_profile_or_list, list):
                self.profile = None
                self.values = list(value_profile_or_list)
            else:
                raise ValueError("value_profile_or_list must be a dict with 'values' or a list")
        elif value_set is not None:
            self.profile = None
            self.values = list(value_set)
        else:
            raise ValueError("Provide either value_profile_or_list or value_set")

        # Sanity check weights
        total = sum(v["weight"] for v in self.values)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Value weights must sum to 1.0, got {total}")

        # Storage and logging
        self.db_name = getattr(config, "DATABASE_NAME", "safi.db")
        self.log_dir = getattr(config, "LOG_DIR", "logs")
        self.log_template = getattr(config, "LOG_FILE_TEMPLATE", None)
        self.legacy_log_file = getattr(config, "LOG_FILE", "safi-spirit-log.jsonl")

        raw_profile_name = (self.profile or {}).get("name") or getattr(config, "DEFAULT_PROFILE", "custom")
        self.active_profile_name = raw_profile_name.lower()

        # Spirit memory vector (per profile)
        dim = max(len(self.values), 1)
        loaded_memory = db.load_spirit_memory(self.db_name, self.active_profile_name)
        self.memory = loaded_memory or {"turn": 0, "mu": np.zeros(dim)}
        if len(self.memory.get("mu", [])) != dim:
            self.memory["mu"] = np.zeros(dim)

        # Wire faculties
        self.intellect_engine = IntellectEngine(
            self.anthropic_client, model=getattr(config, "INTELLECT_MODEL"), profile=self.profile
        )
        self.will_gate = WillGate(
            self.openai_client, model=getattr(config, "WILL_MODEL"), values=self.values, profile=self.profile
        )
        self.conscience = ConscienceAuditor(
            self.openai_client, model=getattr(config, "CONSCIENCE_MODEL"), values=self.values
        )
        self.spirit = SpiritIntegrator(self.values, beta=getattr(config, "SPIRIT_BETA", 0.9))

        print(f"SAFi: profile '{self.active_profile_name}' active.")
        print(f"  - Intellect: {getattr(config, 'INTELLECT_MODEL')}")
        print(f"  - Will: {getattr(config, 'WILL_MODEL')}")
        print(f"  - Conscience: {getattr(config, 'CONSCIENCE_MODEL')}")
        print(f"  - Summarizer: {getattr(config, 'SUMMARIZER_MODEL')}")

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """
        One turn of interaction.
        1) Load rolling conversation summary and history
        2) Generate Intellect draft + reflection
        3) Gate with Will
        4) Return answer immediately
        5) Fire audit and summarization threads
        """
        memory_summary = db.fetch_conversation_summary(self.db_name, conversation_id)
        history = db.fetch_chat_history_for_conversation(self.db_name, conversation_id)
        new_title = db.set_conversation_title_from_first_message(self.db_name, conversation_id, user_prompt) if not history else None

        a_t, r_t = await self.intellect_engine.generate(user_prompt=user_prompt, memory_summary=memory_summary)

        message_id = str(uuid.uuid4())
        db.insert_memory_entry(self.db_name, conversation_id, "user", user_prompt)

        if not a_t:
            err = getattr(self.intellect_engine, "last_error", None) or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            db.insert_memory_entry(self.db_name, conversation_id, "ai", msg, message_id=message_id, audit_status="complete")
            return {
                "finalOutput": msg,
                "newTitle": new_title,
                "willDecision": "violation",
                "willReason": "Intellect failed to produce an answer.",
                "activeProfile": self.active_profile_name,
                "activeValues": self.values,
                "conscienceLedger": [],
                "messageId": message_id,
            }

        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)

        # If Will blocks, we still log and include the full memory for forensics
        if D_t == "violation":
            safe_response = f"This response was suppressed. Reason: {E_t}"
            db.insert_memory_entry(self.db_name, conversation_id, "ai", safe_response, message_id=message_id, audit_status="complete")
            self._append_log(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "t": int(self.memory["turn"]) + 1,
                    "userPrompt": user_prompt,
                    "intellectDraft": a_t,
                    "intellectReflection": r_t or "",
                    "finalOutput": safe_response,
                    "willDecision": D_t,
                    "willReason": E_t,
                    "conscienceLedger": [],
                    "spiritScore": None,
                    "spiritNote": "Suppressed by Will.",
                    "drift": None,
                    "params": {"beta": getattr(self.config, "SPIRIT_BETA", 0.9)},
                    "p_t_vector": [],
                    "mu_t_vector": self.memory.get("mu", np.zeros(len(self.values))).tolist(),
                    # write the entire rolling summary in both shapes
                    "memorySummary": memory_summary,
                    "memory.summary": memory_summary,
                }
            )
            return {
                "finalOutput": safe_response,
                "newTitle": new_title,
                "willDecision": D_t,
                "willReason": E_t,
                "activeProfile": self.active_profile_name,
                "activeValues": self.values,
                "conscienceLedger": [],
                "messageId": message_id,
            }

        # Otherwise we store the draft and audit later
        db.insert_memory_entry(self.db_name, conversation_id, "ai", a_t, message_id=message_id, audit_status="pending")

        # Snapshot for audit: includes the memory and conversation id
        t_next = int(self.memory["turn"]) + 1
        snapshot = {
            "t": t_next,
            "x_t": user_prompt,
            "a_t": a_t,
            "V": self.values,
            "r_t": r_t,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "params": {"beta": getattr(self.config, "SPIRIT_BETA", 0.9)},
            "mode": "conversational",
            "memory_summary": memory_summary,  # full rolling summary
        }
        snap_hash = dict_sha256(snapshot)
        db.upsert_audit_snapshot(self.db_name, t_next, user_id, snap_hash, snapshot)

        # Fire background audit and summarization
        threading.Thread(
            target=self._run_audit_thread, args=(snapshot, snap_hash, D_t, E_t, message_id), daemon=True
        ).start()
        threading.Thread(
            target=self._run_summarization_thread, args=(conversation_id, memory_summary, user_prompt, a_t), daemon=True
        ).start()

        return {
            "finalOutput": a_t,
            "newTitle": new_title,
            "conscienceLedger": [],
            "willDecision": D_t,
            "willReason": E_t,
            "activeProfile": self.active_profile_name,
            "activeValues": self.values,
            "messageId": message_id,
        }

    def _run_audit_thread(
        self, snapshot: Dict[str, Any], snap_hash: str, will_decision: str, will_reason: str, message_id: str
    ):
        """
        Conscience scoring and Spirit update happen here.
        We also write the JSONL log with the full memory included.
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ledger = loop.run_until_complete(
                self.conscience.evaluate(
                    final_output=snapshot["a_t"], user_prompt=snapshot["x_t"], reflection=snapshot["r_t"]
                )
            )
            loop.close()

            S_t, note, mu_new, p_t, drift_val = self.spirit.compute(
                ledger, self.memory.get("mu", np.zeros(len(self.values)))
            )

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
                "spiritNote": note,  # keep clean, no memory snippet added
                "drift": drift_val,
                "params": snapshot["params"],
                "p_t_vector": p_t.tolist(),
                "mu_t_vector": mu_new.tolist(),
                # write the entire rolling summary in both shapes
                "memorySummary": snapshot.get("memory_summary") or "",
                "memory.summary": snapshot.get("memory_summary") or "",
            }
            self._append_log(log_entry)

            # Persist updated spirit memory
            self.memory["turn"] += 1
            self.memory["mu"] = np.array(mu_new)
            db.save_spirit_memory(self.db_name, self.active_profile_name, self.memory)

            # Store audit results on the message row
            db.update_audit_results(self.db_name, message_id, ledger, S_t)

        except Exception as e:
            print(f"--- ERROR IN AUDIT THREAD ---", file=sys.stderr)
            print(f"Message ID: {message_id}", file=sys.stderr)
            print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc(file=sys.stderr)
            print(f"--- END ERROR IN AUDIT THREAD ---", file=sys.stderr)

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        """
        Update the rolling conversation summary after each turn.
        """
        try:
            system_prompt = (
    "You are a memory assistant for an AI. Your task is to maintain a rolling bullet-style memory of the conversation. "
    "Preserve important context from earlier exchanges, but if the conversation has clearly shifted to a new topic, "
    "summarize the earlier topic into a single short bullet before continuing with the new thread. "
    "Do not allow the memory to grow incoherent or overloaded with irrelevant detail. "
    "Format as: 'User asked X → AI answered Y'. "
    "Keep enough history so the AI can remain coherent, but collapse or condense older segments once they are no longer central."
)

            content = (
                f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'This is the beginning of our conversation.'}\n\n"
                f"LATEST EXCHANGE:\nThe user said: \"{user_prompt}\"\nI responded: \"{ai_response}\"\n\n"
                f"UPDATED MEMORY (written from my perspective):"
            )

            response = self.openai_client.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.2,
            )
            new_summary = response.choices[0].message.content.strip()
            db.update_conversation_summary(self.db_name, conversation_id, new_summary)
        except Exception as e:
            print(f"--- ERROR IN SUMMARIZATION THREAD ---", file=sys.stderr)
            print(f"Conversation ID: {conversation_id}", file=sys.stderr)
            print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc(file=sys.stderr)
            print(f"--- END ERROR IN SUMMARIZATION THREAD ---", file=sys.stderr)

    def _append_log(self, log_entry: Dict[str, Any]):
        """
        Append a JSON line to the active log target.
        Uses a daily template if configured, else falls back to a single legacy file.
        """
        log_path = self.legacy_log_file
        if self.log_template:
            try:
                ts_str = log_entry.get("timestamp", datetime.now(timezone.utc).isoformat())
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                profile_log_template = self.log_template.format(profile=self.active_profile_name)
                fname = ts.strftime(profile_log_template)
                p = Path(self.log_dir)
                p.mkdir(parents=True, exist_ok=True)
                log_path = p / fname
            except Exception as e:
                print(f"Could not format daily log path, falling back to legacy. Error: {e}", file=sys.stderr)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Log write error to {log_path}: {e}", file=sys.stderr)
