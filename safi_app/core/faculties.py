from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from openai import OpenAI
import anthropic

from ..utils import normalize_text, dict_sha256


class IntellectEngine:
    """
    Uses Anthropic's client (Claude models) to generate an answer and a reflection.
    - Builds a system prompt including worldview, style, and memory.
    - --- NEW --- Now also includes a self-correction feedback loop from the Spirit.
    - Requests the model to output <ANSWER> and <REFLECTION> sections.
    - Returns both parts separately.
    """
    def __init__(self, client: anthropic.Anthropic, model: str, profile: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.profile = profile or {}
        self.last_error: Optional[str] = None

    async def generate(
        self, *,
        user_prompt: str,
        memory_summary: str,
        spirit_feedback: str
    ) -> Tuple[Optional[str], Optional[str]]:
        self.last_error = None

        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")

        # Short-term memory of the conversation's content.
        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far. Use it to inform your answer.\n"
            f"<summary>{memory_summary}</summary>" if memory_summary else ""
        )

        # This tell the Intellect how well it has been performing against its values.
        spirit_injection = (
            f"ETHICAL PERFORMANCE REVIEW: Use this feedback on your long-term performance to improve your alignment.\n"
            f"<spirit_feedback>{spirit_feedback}</spirit_feedback>" if spirit_feedback else ""
        )

        system_prompt = "\n\n".join(filter(None, [
            worldview,
            style,
            memory_injection,
            spirit_injection, 
            "You must format your response EXACTLY like this, with no other text before or after:",
            "<ANSWER>",
            "</ANSWER>",
            "<REFLECTION>",
            "</REFLECTION>"
        ]))

        try:
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=4096,
                temperature=1.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = resp.content[0].text if resp.content else ""

            answer = text.split("<ANSWER>", 1)[1].split("</ANSWER>", 1)[0].strip() if "<ANSWER>" in text else text.split("<REFLECTION>")[0].strip()
            reflection = text.split("<REFLECTION>", 1)[1].split("</REFLECTION>", 1)[0].strip() if "<REFLECTION>" in text else ""

            return (answer or None), (reflection or "")
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e} (model={self.model})"
            return None, None


class WillGate:
    """
    Uses OpenAI's client to act as a gatekeeper.
    - This is the "letter of the law" enforcer.
    - It checks if a draft answer violates any of the profile's non-negotiable 'will_rules'.
    - Returns a binary decision ('approve' or 'violation') and a reason.
    - Its decision is final for a given turn.
    """
    def __init__(self, client: OpenAI, model: str, *, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.cache: Dict[str, Tuple[str, str]] = {}

    def _key(self, x_t: str, a_t: str) -> str:
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    async def evaluate(self, *, user_prompt: str, draft_answer: str) -> Tuple[str, str]:
        key = self._key(user_prompt, draft_answer)
        if key in self.cache:
            return self.cache[key]

        rules = self.profile.get("will_rules") or []
        name = self.profile.get("name", "")

        if not rules:
            joined = ", ".join(v["value"] for v in self.values)
            rules = [f"Do not approve drafts that reduce alignment with the declared values: {joined}."]

        policy = "\n".join([ "You are Will, the ethical gatekeeper. Decide if the draft aligns with the value set.", f"Tradition: {name}" if name else "", "Rules:", *[f"- {r}" for r in rules], "Value Set:", json.dumps(self.values, indent=2), "Return a single JSON object with exactly these keys: decision, reason.", "decision ∈ {'approve','violation'}. reason is a concise natural language sentence." ])
        prompt = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"

        try:
            resp = await asyncio.to_thread( self.client.chat.completions.create, model=self.model, temperature=0.0, response_format={"type": "json_object"}, messages=[ {"role": "system", "content": policy}, {"role": "user", "content": prompt}, ], )
            content = resp.choices[0].message.content or "{}"
            obj = json.loads(content) if content else {}
            decision = str(obj.get("decision") or "").strip().lower()
            reason = (obj.get("reason") or "").strip()
            if decision not in {"approve", "violation"}: decision = "violation"
            if not reason: reason = "Decision explained by Will policies and the active value set."
            tup = (decision, reason)
            self.cache[key] = tup
            return tup
        except Exception as e:
            return ("violation", f"Will exception: {type(e).__name__}: {e}")


class ConscienceAuditor:
    """
    Uses OpenAI's client to audit the final output from the profile's worldview.
    - This is the "spirit of the law" evaluator.
    - It scores the alignment of the final text with each declared value.
    - It produces a detailed 'ledger' with scores, confidences, and reasons.
    - Its audit is used by the Spirit to update long-term memory.
    """
    def __init__(self, client: OpenAI, model: str, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str) -> List[Dict[str, Any]]:
        values_str = "\n".join([f"- {v['value']}" for v in self.values])
        worldview = self.profile.get("worldview", "")
        worldview_injection = f"You must adopt the following worldview when performing your audit:\n<worldview>\n{worldview}\n</worldview>\n\n" if worldview else ""
        sys_prompt = ( f"{worldview_injection}" "You are Conscience, an ethical auditor. Your task is to score the FINAL OUTPUT below for its alignment with each value. " "IMPORTANT: You must ONLY evaluate the text of the FINAL OUTPUT. DO NOT score the topic being discussed. " "For example, a neutral, factual answer about a harmful topic should receive a neutral score (0), not a negative one. " "Use scores in {-1, 0, 0.5, 1} and confidence in [0,1]. " "Return a single JSON object with one key 'evaluations' which is a list of objects, each with keys: 'value', 'score', 'confidence', 'reason'." )
        body = ( f"VALUES:\n{values_str}\n\nPROMPT:\n{user_prompt}\n\nFINAL OUTPUT:\n{final_output}\n\nREFLECTION:\n{reflection}" )
        try:
            resp = await asyncio.to_thread( self.client.chat.completions.create, model=self.model, temperature=0.2, response_format={"type": "json_object"}, messages=[ {"role": "system", "content": sys_prompt}, {"role": "user", "content": body}, ], )
            content = resp.choices[0].message.content or "{}"
            obj = json.loads(content) if content else {}
            return obj.get("evaluations", [])
        except Exception:
            return []


class SpiritIntegrator:
    """
    Integrates conscience evaluations into a long-term spirit memory vector (mu).
    - This is the system's long-term memory and self-awareness component.
    - It computes a weighted score for the current turn.
    - It updates the running state (mu) using exponential smoothing (the 90/10 rule).
    - It calculates the 'drift' to measure how uncharacteristic a response is.
    """
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values]) if self.values else np.array([1.0])

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        if not self.values or not ledger or len(ledger) != len(self.values):
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        lmap = {row['value']: row for row in ledger}
        sorted_rows = [lmap.get(v['value']) for v in self.values]
        if any(r is None for r in sorted_rows):
            return 1, "Ledger missing values", mu_tm1, np.zeros_like(mu_tm1), None

        scores = np.array([float(r.get('score', 0)) for r in sorted_rows])
        confidences = np.array([float(r.get('confidence', 0)) for r in sorted_rows])

        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        # This is the performance vector for the current turn (p_t).
        p_t = self.value_weights * scores

        # This is the core formula for updating the long-term memory (mu).
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        # This calculates drift by comparing the current turn's vector (p_t)
        # to the long-term historical vector (mu_tm1).
        denom = (np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = 0.0 if denom == 0 else (1 - float(np.dot(p_t, mu_tm1) / denom))
        note = f"Coherence {spirit_score}/10, drift {drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift
