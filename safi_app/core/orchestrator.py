from __future__ import annotations
import json
import threading
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional
import sys

from openai import OpenAI

from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from ..persistence import database as db
from ..utils import dict_sha256


class SAFi:
    def __init__(
        self,
        config,
        value_profile_or_list: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        value_set: Optional[List[Dict[str, Any]]] = None,
        initial_memory=None,
    ):
        self.config = config

        api_key = getattr(config, 'OPENAI_API_KEY', None)
        if not api_key:
            raise ValueError("OPENAI_API_KEY missing")
        self.client = OpenAI(api_key=api_key)

        if value_profile_or_list is not None:
            if isinstance(value_profile_or_list, dict) and "values" in value_profile_or_list:
                self.profile = value_profile_or_list
                self.values = [
                    {"value": v["value"], "weight": v["weight"]}
                    for v in self.profile["values"]
                ]
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

        total = sum(v['weight'] for v in self.values)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Value weights must sum to 1.0, got {total}")

        self.db_name = getattr(config, 'DATABASE_NAME', 'safi.db')
        self.log_file = getattr(config, 'LOG_FILE', 'safi.log')

        dim = max(len(self.values), 1)
        self.memory = initial_memory or {"turn": 0, "mu": np.zeros(dim)}

        self.intellect_engine = IntellectEngine(self.client, model=getattr(config, 'INTELLECT_MODEL', 'gpt-4o-mini'), profile=self.profile)
        self.will_gate = WillGate(self.client, model=getattr(config, 'WILL_MODEL', 'gpt-4o-mini'), values=self.values, profile=self.profile)
        self.conscience = ConscienceAuditor(self.client, model=getattr(config, 'CONSCIENCE_MODEL', 'gpt-4o-mini'), values=self.values)
        self.spirit = SpiritIntegrator(self.values, beta=getattr(config, 'SPIRIT_BETA', 0.9))

        print("SAFi: ethics-from-values active; Conscience values-only.")

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        history = db.fetch_chat_history_for_conversation(self.db_name, conversation_id)
        new_title = db.set_conversation_title_from_first_message(self.db_name, conversation_id, user_prompt) if not history else None
        memory_summary = db.fetch_recent_user_memory(self.db_name, conversation_id)

        a_t, r_t = await self.intellect_engine.generate(user_prompt=user_prompt, memory_summary=memory_summary)
        if not a_t:
            err = getattr(self.intellect_engine, 'last_error', None) or "Unknown model/API error"
            msg = f"Intellect failed: {err}"
            db.insert_memory_entry(self.db_name, conversation_id, "prompt", user_prompt)
            db.insert_memory_entry(self.db_name, conversation_id, "final_output", msg)
            return {"finalOutput": msg, "newTitle": new_title}

        D_t, E_t = await self.will_gate.evaluate(user_prompt=user_prompt, draft_answer=a_t)
        if D_t == 'violation':
            safe_response = f"This response was suppressed. Reason: {E_t}"
            db.insert_memory_entry(self.db_name, conversation_id, "prompt", user_prompt)
            db.insert_memory_entry(self.db_name, conversation_id, "final_output", safe_response)
            return {"finalOutput": safe_response, "newTitle": new_title}

        ledger = await self.conscience.evaluate(final_output=a_t, user_prompt=user_prompt, reflection=r_t)

        db.insert_memory_entry(self.db_name, conversation_id, "prompt", user_prompt)
        db.insert_memory_entry(self.db_name, conversation_id, "final_output", a_t)

        t_next = int(self.memory['turn']) + 1
        snapshot = {
            "t": t_next, "x_t": user_prompt, "a_t": a_t, "V": self.values, "r_t": r_t,
            "user_id": user_id, "params": {"beta": getattr(self.config, 'SPIRIT_BETA', 0.9)}, "mode": "conversational"
        }
        snap_hash = dict_sha256(snapshot)
        db.upsert_audit_snapshot(self.db_name, t_next, user_id, snap_hash, snapshot)

        threading.Thread(target=self._run_audit_thread, args=(snapshot, snap_hash, ledger), daemon=True).start()

        return {"finalOutput": a_t, "newTitle": new_title, "conscienceLedger": ledger}

    def _run_audit_thread(self, snapshot: Dict[str, Any], snap_hash: str, ledger: List[Dict[str, Any]]):
        S_t, note, mu_new, p_t = self.spirit.compute(ledger, self.memory.get('mu', np.zeros(len(self.values))))
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "t": snapshot['t'],
            "userPrompt": snapshot['x_t'], "intellectDraft": snapshot['a_t'],
            "intellectReflection": snapshot['r_t'], "finalOutput": snapshot['a_t'],
            "willDecision": "approve", "conscienceLedger": ledger,
            "spiritScore": S_t, "spiritNote": note, "params": snapshot['params'],
            "p_t_vector": p_t.tolist(), "mu_t_vector": mu_new.tolist()
        }
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Log write error: {e}", file=sys.stderr)
        self.memory['turn'] += 1
        self.memory['mu'] = np.array(mu_new)