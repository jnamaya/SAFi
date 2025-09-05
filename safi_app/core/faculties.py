from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from openai import OpenAI

from ..utils import normalize_text, dict_sha256

# --- Robust label normalization to prevent first-run ledger mismatches ---
import re
import unicodedata
DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]  # hyphen, nb-hyphen, figure dash, en, em, minus

def _norm_label(s: str) -> str:
    """Normalize labels for safe matching across Unicode variants and spacing."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    for d in DASHES:
        s = s.replace(d, "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


class IntellectEngine:
    """
    - Builds a system prompt including worldview, style, memory, and Spirit feedback.
    - Requests the model to output <ANSWER> and <REFLECTION> sections.
    - Returns both parts separately.
    """
    def __init__(self, client: OpenAI, model: str, profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
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

        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far. Use it to inform your answer.\n"
            f"<summary>{memory_summary}</summary>" if memory_summary else ""
        )
        
        # --- FIX: Re-applied the logic to use the external coaching note prompt ---
        # This section now correctly loads the coaching note template from the prompt
        # configuration and formats it with the dynamic feedback data.
        spirit_injection = ""
        if spirit_feedback:
            coaching_note_template = self.prompt_config.get("coaching_note", "")
            if coaching_note_template:
                spirit_injection = coaching_note_template.format(spirit_feedback=spirit_feedback)

        formatting_instructions = self.prompt_config.get("formatting_instructions", "")

        system_prompt = "\n\n".join(filter(None, [
            worldview, style, memory_injection, spirit_injection, formatting_instructions
        ]))

        try:
            resp = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                max_tokens=4096,
                temperature=1.0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
            )
            text = resp.choices[0].message.content or ""

            answer = text.split("<ANSWER>", 1)[1].split("</ANSWER>", 1)[0].strip() if "<ANSWER>" in text else text.split("<REFLECTION>")[0].strip()
            reflection = text.split("<REFLECTION>", 1)[1].split("</REFLECTION>", 1)[0].strip() if "<REFLECTION>" in text else ""

            return (answer or None), (reflection or "")
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e} (model={self.model})"
            return None, None


class WillGate:
    """
    Uses an OpenAI-compatible client to act as a gatekeeper. No changes needed to internal logic.
    """
    def __init__(self, client: OpenAI, model: str, *, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
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

        policy_parts = [
            self.prompt_config.get("header", "You are Will, the ethical gatekeeper."),
            f"Tradition: {name}" if name else "", "Rules:", *[f"- {r}" for r in rules],
            "Value Set:", json.dumps(self.values, indent=2),
            self.prompt_config.get("footer", "Return a single JSON object with keys: decision, reason."),
        ]
        policy = "\n".join(filter(None, policy_parts))
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
    Uses an OpenAI-compatible client to audit the final output. No changes needed to internal logic.
    """
    def __init__(self, client: OpenAI, model: str, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str) -> List[Dict[str, Any]]:
        values_str = "\n".join([f"- {v['value']}" for v in self.values])
        worldview = self.profile.get("worldview", "")
        worldview_injection = f"You must adopt the following worldview when performing your audit:\n<worldview>\n{worldview}\n</worldview>\n\n" if worldview else ""
        
        base_prompt = self.prompt_config.get("base_prompt", "You are Conscience, an ethical auditor.")
        sys_prompt = f"{worldview_injection}{base_prompt}"

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
    Pure math, with robust label handling and safer drift calculation.
    """
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values]) if self.values else np.array([1.0])
        # Normalized label index (prevents Unicode hyphen and spacing mismatches)
        self._norm_values = [_norm_label(v['value']) for v in self.values] if self.values else []
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        # Basic guard
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        # Normalize ledger labels and build a map
        lmap: Dict[str, Dict[str, Any]] = {}
        for row in ledger:
            key = _norm_label(row.get('value'))
            if key:  # keep last occurrence if duplicates
                lmap[key] = row

        # Reorder to the configured values; collect missing
        sorted_rows: List[Optional[Dict[str, Any]]] = []
        missing_human: List[str] = []
        for i, nkey in enumerate(self._norm_values):
            row = lmap.get(nkey)
            if row is None:
                missing_human.append(self.values[i]['value'])
                sorted_rows.append(None)
            else:
                sorted_rows.append(row)

        if any(r is None for r in sorted_rows):
            note = f"Ledger missing values: {', '.join(missing_human)}"
            return 1, note, mu_tm1, np.zeros_like(mu_tm1), None

        # Build vectors in canonical order
        scores = np.array([float(r.get('score', 0.0)) for r in sorted_rows], dtype=float)
        confidences = np.array([float(r.get('confidence', 0.0)) for r in sorted_rows], dtype=float)

        # Weighted sum with clipping → 1..10 score
        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        # Directional vector for memory update (kept parity with existing behavior)
        p_t = self.value_weights * scores

        # Exponential moving average (mu update)
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        # Cosine drift with epsilon guard against near-zero norms
        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        if denom < eps:
            drift = None
        else:
            drift = 1.0 - float(np.dot(p_t, mu_tm1) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift
