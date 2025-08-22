import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple
from pydantic import ValidationError

from ..models import WillResponse, ConscienceResponse
from ..utils import normalize_text, dict_sha256

class IntellectEngine:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    @staticmethod
    def _json_call(client, model, messages, temperature=1.0) -> Dict[str, Any] | None:
        try:
            resp = client.chat.completions.create(model=model, temperature=temperature, messages=messages, response_format={"type": "json_object"})
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"Intellect JSON call failed: {e}")
            return None

    async def generate(self, *, user_prompt: str, memory_summary: str) -> Tuple[str | None, str | None]:
        memory_injection = f"MEMORY SUMMARY:\n{memory_summary}" if memory_summary else ""
        system_prompt = (
            "You are an ethical assistant speaking in a natural, conversational tone. "
            "Give a direct answer first, keep structure tight, avoid listing values as headings. "
            "Include a short hidden reflection inside <REFLECTION> tags.\n\n"
            f"{memory_injection}"
        )
        
        obj = await asyncio.to_thread(self._json_call, self.client, self.model, [{"role": "system", "content": system_prompt + "\nReturn JSON with keys: draft_answer, reflection."}, {"role": "user", "content": user_prompt}], 1.0)
        if obj and "draft_answer" in obj:
            return obj.get("draft_answer"), obj.get("reflection")

        try:
            comp = await asyncio.to_thread(self.client.chat.completions.create, model=self.model, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=1.0)
            text = comp.choices[0].message.content or ""
            parts = text.split('<REFLECTION>')
            draft = parts[0].strip()
            reflection = parts[1].replace('</REFLECTION>', '').strip() if len(parts) > 1 else ""
            return draft, reflection
        except Exception as e:
            print(f"Intellect text fallback failed: {e}")
            return None, None

class WillGate:
    def __init__(self, client, model: str, values: List[Dict[str, Any]]):
        self.client = client
        self.model = model
        self.values = values
        self.cache: Dict[str, Tuple[str, str]] = {}

    def _key(self, x_t: str, a_t: str) -> str:
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    @staticmethod
    def _json_call(client, model, messages, temperature=0.2) -> Dict[str, Any] | None:
        try:
            resp = client.chat.completions.create(model=model, temperature=temperature, messages=messages, response_format={"type": "json_object"})
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"Will JSON call failed: {e}")
            return None

    async def evaluate(self, *, user_prompt: str, draft_answer: str) -> Tuple[str, str]:
        key = self._key(user_prompt, draft_answer)
        if key in self.cache: return self.cache[key]
        
        policy = (
            "You are Will, the ethical gatekeeper. Decide if the draft answer morally aligns with the value set.\n"
            "Rules: do not approve content that promotes or beautifies violations of the values.\n"
            "Return JSON {decision: 'approve'|'violation', reason: string}.\n\n"
            f"Value Set:\n{json.dumps(self.values, indent=2)}"
        )
        prompt = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"
        
        obj = await asyncio.to_thread(self._json_call, self.client, self.model, [{"role": "system", "content": policy}, {"role": "user", "content": prompt}], 0.2)
        
        try:
            parsed = WillResponse.model_validate(obj or {})
            tup = (parsed.decision, parsed.reason)
            self.cache[key] = tup
            return tup
        except (ValidationError, TypeError):
            return ("violation", "Schema or validation failure")

class ConscienceAuditor:
    def __init__(self, client, model: str, values: List[Dict[str, Any]]):
        self.client = client
        self.model = model
        self.values = values

    @staticmethod
    def _json_call(client, model, messages, temperature=0.2) -> Dict[str, Any] | None:
        try:
            resp = client.chat.completions.create(model=model, temperature=temperature, messages=messages, response_format={"type": "json_object"})
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"Conscience JSON call failed: {e}")
            return None

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str) -> List[Dict[str, Any]]:
        values_str = "\n".join([f"- {v['value']}" for v in self.values])
        sys_prompt = "You are Conscience. For each value score s∈{-1,0,0.5,1}, confidence c∈[0,1], and give a short reason. Return JSON {evaluations:[{value,score,confidence,reason}...]}."
        user_prompt_full = f"VALUES:\n{values_str}\n\nPROMPT:\n{user_prompt}\n\nOUTPUT:\n{final_output}\n\nREFLECTION:\n{reflection}"
        
        obj = await asyncio.to_thread(self._json_call, self.client, self.model, [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt_full}], 0.2)
        
        try:
            return [e.model_dump() for e in ConscienceResponse.model_validate(obj or {}).evaluations]
        except (ValidationError, TypeError):
            return []

class SpiritIntegrator:
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values])

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray) -> Tuple[int, str, np.ndarray, np.ndarray]:
        if not ledger or len(ledger) != len(self.values):
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1)
        
        lmap = {row['value']: row for row in ledger}
        sorted_rows = [lmap.get(v['value']) for v in self.values]
        
        if any(r is None for r in sorted_rows):
            return 1, "Ledger/value mismatch", mu_tm1, np.zeros_like(mu_tm1)
            
        scores = np.array([float(r['score']) for r in sorted_rows])
        confidences = np.array([float(r['confidence']) for r in sorted_rows])
        
        raw_score = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(np.round((raw_score + 1) / 2 * 9 + 1))
        
        p_t = self.value_weights * scores
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t
        
        denom = (np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = 0.0 if denom == 0 else (1 - float(np.dot(p_t, mu_tm1) / denom))
        
        note = f"Coherence {spirit_score}/10, drift {drift:.2f}."
        return spirit_score, note, mu_new, p_t
