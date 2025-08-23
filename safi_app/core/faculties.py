from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from openai import OpenAI

from ..utils import normalize_text, dict_sha256


class IntellectEngine:
    def __init__(self, client: OpenAI, model: str, profile: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model or "gpt-4o-mini"
        self.profile = profile or {}
        self.last_error: Optional[str] = None

    async def generate(self, *, user_prompt: str, memory_summary: str) -> Tuple[Optional[str], Optional[str]]:
        self.last_error = None
        memory_injection = f"MEMORY SUMMARY:\n{memory_summary}" if memory_summary else ""
        worldview = self.profile.get("worldview")
        style = self.profile.get("style")

        if worldview or style:
            sys_lines = [ln for ln in [worldview, style, memory_injection] if ln]
            system_prompt = "\n\n".join(sys_lines)
        else:
            system_prompt = ("You are an ethical assistant speaking in a natural, conversational tone. "
                             "Give a direct answer first.\n\n" + memory_injection)

        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        candidates = [self.model, "gpt-4o-mini", "gpt-4o"]
        tried = set()
        for m in candidates:
            if not m or m in tried:
                continue
            tried.add(m)
            try:
                resp = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=m,
                    temperature=1.0,
                    messages=msgs,
                )
                text = resp.choices[0].message.content or ""
                parts = text.split('<REFLECTION>')
                draft = parts[0].strip()
                reflection = parts[1].replace('</REFLECTION>', '').strip() if len(parts) > 1 else ""
                self.model = m
                return draft, reflection
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e} (model={m})"
                continue

        return None, None


class WillGate:
    def __init__(self, client: OpenAI, model: str, *, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model or "gpt-4o-mini"
        self.values = values
        self.profile = profile or {}
        self.cache: Dict[str, Tuple[str, str]] = {}

    def _key(self, x_t: str, a_t: str) -> str:
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    async def evaluate(self, *, user_prompt: str, draft_answer: str) -> Tuple[str, str]:
        key = self._key(user_prompt, draft_answer)
        if key in self.cache:
            return self.cache[key]

        rules = self.profile.get("will_rules") or [
            "Do not approve content that promotes or beautifies violations of the values.",
        ]
        safety = self.profile.get("safety_overrides") or []
        name = self.profile.get("name", "")

        lines = [
            "You are Will, the ethical gatekeeper. Decide if the draft aligns with the value set.",
            f"Tradition: {name}" if name else "",
            "Rules:",
            *[f"- {r}" for r in rules],
            "Return JSON {decision: 'approve'|'violation', reason: string}.",
            f"Value Set:\n{json.dumps(self.values, indent=2)}",
        ]
        if safety:
            lines.insert(-2, "Safety:")
            lines[lines.index("Safety:")+1:1] = [f"- {s}" for s in safety]
        policy = "\n".join([x for x in lines if x])
        prompt = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"

        try:
            resp = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": policy},
                    {"role": "user", "content": prompt},
                ],
            )
            content = resp.choices[0].message.content or "{}"
            try:
                obj = json.loads(content)
            except Exception:
                obj = {}

            decision = obj.get("decision", "violation")
            reason = obj.get("reason", "No reason")
            tup = (decision, reason)
            self.cache[key] = tup
            return tup
        except Exception as e:
            return ("violation", f"Will exception: {type(e).__name__}: {e}")


class ConscienceAuditor:
    def __init__(self, client: OpenAI, model: str, values: List[Dict[str, Any]]):
        self.client = client
        self.model = model or "gpt-4o-mini"
        self.values = values

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str) -> List[Dict[str, Any]]:
        values_str = "\n".join([f"- {v['value']}" for v in self.values])
        sys_prompt = (
            "You are Conscience. Score the ANSWER's alignment with each value (not the behavior discussed). "
            "Use scores in {-1, 0, 0.5, 1} and confidence in [0,1]. Return JSON {evaluations:[{value,score,confidence,reason}...]}."
        )
        body = (
            f"VALUES:\n{values_str}\n\nPROMPT:\n{user_prompt}\n\nOUTPUT:\n{final_output}\n\nREFLECTION:\n{reflection}"
        )
        try:
            resp = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": body},
                ],
            )
            content = resp.choices[0].message.content or "{}"
            try:
                obj = json.loads(content)
            except Exception:
                obj = {}
            return obj.get("evaluations", [])
        except Exception:
            return []


class SpiritIntegrator:
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values]) if self.values else np.array([1.0])

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        if not self.values or not ledger or len(ledger) != len(self.values):
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1)

        lmap = {row['value']: row for row in ledger}
        sorted_rows = [lmap.get(v['value']) for v in self.values]
        if any(r is None for r in sorted_rows):
            return 1, "Ledger missing values", mu_tm1, np.zeros_like(mu_tm1)

        scores = np.array([float(r['score']) for r in sorted_rows])
        confidences = np.array([float(r['confidence']) for r in sorted_rows])

        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        p_t = self.value_weights * scores
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        denom = (np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = 0.0 if denom == 0 else (1 - float(np.dot(p_t, mu_tm1) / denom))
        note = f"Coherence {spirit_score}/10, drift {drift:.2f}."
        return spirit_score, note, mu_new, p_t