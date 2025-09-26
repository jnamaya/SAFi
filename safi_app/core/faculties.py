from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from openai import OpenAI
import re
import unicodedata

from ..utils import normalize_text, dict_sha256
from .retriever import Retriever

# Define various Unicode dash characters for normalization.
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
    Core cognitive faculty for generating responses.
    
    This class integrates various inputs (user prompt, memory, ethical feedback, and
    retrieved context) into a single system prompt, queries the language model,
    and parses the response into separate answer and reflection components.
    """
    def __init__(self, client: OpenAI, model: str, profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        """
        Initializes the IntellectEngine.

        Args:
            client: The OpenAI API client.
            model: The name of the model to use for generation.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts and instructions.
        """
        self.client = client
        self.model = model
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.last_error: Optional[str] = None
        
        # Initialize the Retriever for RAG if the current profile is the 'SAFi'.
        # This prevents loading the model and index unnecessarily for other profiles.
        self.retriever = None
        if self.profile.get("name") == "SAFi":
            self.retriever = Retriever()

    async def generate(
        self, *,
        user_prompt: str,
        memory_summary: str,
        spirit_feedback: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.

        Args:
            user_prompt: The user's input.
            memory_summary: A summary of the conversation history.
            spirit_feedback: Coaching notes based on ethical performance.

        Returns:
            A tuple containing the generated answer and reflection, or (None, None) on error.
        """
        self.last_error = None
        
        context_injection = ""
        if self.retriever:
            print(f"Performing RAG search for prompt: '{user_prompt[:50]}...'")
            retrieved_context = self.retriever.search(user_prompt)
            
            if retrieved_context:
                rag_template = self.prompt_config.get("rag_context_injection", "")
                if rag_template:
                    context_injection = rag_template.format(retrieved_context=retrieved_context)
                    print("Successfully injected context from RAG index.")
                else:
                    print("Warning: RAG context injection template not found in prompt config.")
            else:
                print("No relevant context found in RAG index.")

        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")

        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far. Use it to inform your answer.\n"
            f"<summary>{memory_summary}</summary>" if memory_summary else ""
        )
        
        spirit_injection = ""
        if spirit_feedback:
            coaching_note_template = self.prompt_config.get("coaching_note", "")
            if coaching_note_template:
                spirit_injection = coaching_note_template.format(spirit_feedback=spirit_feedback)

        formatting_instructions = self.prompt_config.get("formatting_instructions", "")

        system_prompt = "\n\n".join(filter(None, [
            context_injection, worldview, style, memory_injection, spirit_injection, formatting_instructions
        ]))

        try:
            resp = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                max_tokens=4096,
                temperature=1.0,
                response_format={"type": "json_object"}, # Use JSON mode for reliable output
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
            )
            content = resp.choices[0].message.content or "{}"
            obj = json.loads(content)
            
            answer = obj.get("answer")
            reflection = obj.get("reflection", "")
            # Clean escaped newlines
            answer = answer.replace("\\n", "\n").strip()
            reflection = reflection.replace("\\n", "\n").strip()

            return answer, reflection
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e} (model={self.model})"
            return None, None


class WillGate:
    """
    An ethical gatekeeper that evaluates a draft response against a set of values.
    It decides whether to 'approve' or declare a 'violation'.
    """
    def __init__(self, client: OpenAI, model: str, *, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        """Initializes the WillGate."""
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.cache: Dict[str, Tuple[str, str]] = {}

    def _key(self, x_t: str, a_t: str) -> str:
        """Creates a unique cache key for a given prompt and answer."""
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    async def evaluate(self, *, user_prompt: str, draft_answer: str) -> Tuple[str, str]:
        """
        Evaluates a draft answer for alignment with ethical rules and values.

        Args:
            user_prompt: The original user prompt.
            draft_answer: The draft answer generated by the IntellectEngine.

        Returns:
            A tuple containing the decision ('approve' or 'violation') and a reason.
        """
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
    Audits the final, user-facing output for alignment with a set of values.
    This provides the data used for long-term ethical steering (Spirit).
    """
    def __init__(self, client: OpenAI, model: str, values: List[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None, prompt_config: Optional[Dict[str, Any]] = None):
        """Initializes the ConscienceAuditor."""
        self.client = client
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str) -> List[Dict[str, Any]]:
        """
        Scores the final output against each configured value.

        Args:
            final_output: The answer that was shown to the user.
            user_prompt: The original user prompt.
            reflection: The internal reflection from the IntellectEngine.

        Returns:
            A list of evaluation dictionaries, one for each value.
        """
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
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    This class performs mathematical operations to update the AI's ethical alignment over time.
    """
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        """
        Initializes the SpiritIntegrator.

        Args:
            values: A list of value dictionaries, including names and weights.
            beta: The decay factor for the exponential moving average (controls memory length).
        """
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values]) if self.values else np.array([1.0])
        self._norm_values = [_norm_label(v['value']) for v in self.values] if self.values else []
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        """
        Updates the spirit memory vector based on the latest audit ledger.

        Args:
            ledger: The list of evaluations from the ConscienceAuditor.
            mu_tm1: The previous spirit memory vector (mu_t-1).

        Returns:
            A tuple containing the spirit score, a status note, the new memory vector (mu_new),
            the vector of the current turn (p_t), and the drift value.
        """
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        lmap: Dict[str, Dict[str, Any]] = { _norm_label(row.get('value')): row for row in ledger if row.get('value') }
        sorted_rows: List[Optional[Dict[str, Any]]] = [lmap.get(nkey) for nkey in self._norm_values]

        if any(r is None for r in sorted_rows):
            missing = [self.values[i]['value'] for i, r in enumerate(sorted_rows) if r is None]
            note = f"Ledger missing values: {', '.join(missing)}"
            return 1, note, mu_tm1, np.zeros_like(mu_tm1), None

        scores = np.array([float(r.get('score', 0.0)) for r in sorted_rows], dtype=float)
        confidences = np.array([float(r.get('confidence', 0.0)) for r in sorted_rows], dtype=float)

        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        p_t = self.value_weights * scores
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift

