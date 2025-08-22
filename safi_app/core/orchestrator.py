import os
import json
import asyncio
import threading
import numpy as np
import openai
from datetime import datetime, timezone
from typing import List, Dict, Any

from .faculties import IntellectEngine, WillGate, ConscienceAuditor, SpiritIntegrator
from ..persistence import database as db
from ..utils import dict_sha256

class SAFi:
    def __init__(self, config, value_set: List[Dict[str, Any]], initial_memory=None):
        self.config = config
        self.api_key = config.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key not found in configuration.")
        
        self.client = openai.OpenAI(api_key=self.api_key)
        self.values = value_set
        self._validate_weights()
        
        self.db_name = config.DATABASE_NAME
        self.log_file = config.LOG_FILE
        
        self.memory = initial_memory or {"turn": 0, "mu": np.zeros(len(self.values))}
        
        self.intellect_engine = IntellectEngine(self.client, config.INTELLECT_MODEL)
        self.will_gate = WillGate(self.client, config.WILL_MODEL, self.values)
        self.conscience = ConscienceAuditor(self.client, config.CONSCIENCE_MODEL, self.values)
        self.spirit = SpiritIntegrator(self.values, beta=config.SPIRIT_BETA)
        
        print("SAFi v1.5 Initialized with modular structure.")

    def _validate_weights(self):
        if not np.isclose(sum(v['weight'] for v in self.values), 1.0):
            raise ValueError("Value weights must sum to 1.0")

    def _log_turn(self, log_entry: Dict[str, Any]):
        mu_vec = log_entry.pop('mu_t_vector', self.memory['mu'].tolist())
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except IOError as e:
            print(f"Log write error: {e}")
        
        self.memory['turn'] += 1
        self.memory['mu'] = np.array(mu_vec)

    async def process_prompt(self, user_prompt: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        history = db.fetch_chat_history_for_conversation(self.db_name, conversation_id)
        new_title = db.set_conversation_title_from_first_message(self.db_name, conversation_id, user_prompt) if not history else None
        memory_summary = db.fetch_recent_user_memory(self.db_name, conversation_id)
        
        a_t, r_t = await self.intellect_engine.generate(user_prompt=user_prompt, memory_summary=memory_summary)
        if not a_t:
            return {"finalOutput": "Sorry, I couldn't generate an answer.", "newTitle": new_title}
        
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
            "user_id": user_id, "params": {"beta": self.config.SPIRIT_BETA}, "mode": "conversational"
        }
        snap_hash = dict_sha256(snapshot)
        db.upsert_audit_snapshot(self.db_name, t_next, user_id, snap_hash, snapshot)
        
        threading.Thread(target=self._run_audit_thread, args=(snapshot, snap_hash, ledger), daemon=True).start()
        
        return {"finalOutput": a_t, "newTitle": new_title, "conscienceLedger": ledger}

    def _run_audit_thread(self, snapshot: Dict[str, Any], snap_hash: str, ledger: List[Dict[str, Any]]):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_audit(snapshot, snap_hash, ledger))
        finally:
            loop.close()

    async def _run_audit(self, snapshot: Dict[str, Any], snap_hash: str, ledger: List[Dict[str, Any]]):
        keys_for_hash = ["t", "x_t", "a_t", "V", "r_t", "user_id", "params", "mode"]
        if dict_sha256({k: snapshot[k] for k in keys_for_hash}) != snap_hash:
            print("Audit snapshot hash mismatch. Aborting audit.")
            return
            
        user_prompt, draft_answer, r_t = snapshot['x_t'], snapshot['a_t'], snapshot['r_t']
        
        S_t, note, mu_new, p_t = self.spirit.compute(ledger, self.memory.get('mu', np.zeros(len(self.values))))
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "t": snapshot['t'],
            "userPrompt": user_prompt, "intellectDraft": draft_answer,
            "intellectReflection": r_t, "finalOutput": draft_answer,
            "willDecision": "approve", "conscienceLedger": ledger,
            "spiritScore": S_t, "spiritNote": note, "params": snapshot['params'],
            "p_t_vector": p_t.tolist(), "mu_t_vector": mu_new.tolist()
        }
        self._log_turn(log_entry)
