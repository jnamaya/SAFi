from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import re
import unicodedata
import sys

# --- MODIFICATION: Import new clients/types ---
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai
# --- END MODIFICATION ---

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
    def __init__(
        self, 
        client: Any, # Client can be any type now
        provider_name: str, # We'll use this to know *what* client is
        model: str, 
        profile: Optional[Dict[str, Any]] = None, 
        prompt_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initializes the IntellectEngine.

        Args:
            client: The API client (e.g., AsyncOpenAI, AsyncAnthropic) or model name (for Gemini).
            provider_name: The name of the provider (e.g., "groq", "openai", "anthropic", "gemini").
            model: The name of the model to use for generation.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts and instructions.
        """
        self.client = client
        self.provider = provider_name
        self.model = model
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.last_error: Optional[str] = None
        
        # --- MODIFICATION: Handle Gemini client init ---
        if self.provider == "gemini":
            try:
                # client is actually the model name string
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                print(f"Error initializing Gemini model {self.model}: {e}", file=sys.stderr)
                self.gemini_model = None
        # --- END MODIFICATION ---

        self.retriever = None
        # --- DYNAMIC RAG INITIALIZATION ---
        kb_name = self.profile.get("rag_knowledge_base")
        if kb_name:
            self.retriever = Retriever(knowledge_base_name=kb_name)
        # ----------------------------------

    async def generate(
        self, *,
        user_prompt: str,
        memory_summary: str,
        spirit_feedback: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.
        """
        self.last_error = None
        
        # --- MODIFICATION: RAG context is formatted and injected into the worldview ---
        retrieved_context_string = ""
        if self.retriever:
            print(f"Performing RAG search for prompt: '{user_prompt[:50]}...'")
            retrieved_docs = self.retriever.search(user_prompt) # <-- Get the List[Dict]
            
            if not retrieved_docs:
                retrieved_context_string = "[NO DOCUMENTS FOUND]"
            else:
                # Get the formatting string from the persona profile
                format_string = self.profile.get("rag_format_string")
                if not format_string:
                    # Fallback if no format string is defined
                    print("--- WARNING: No 'rag_format_string' in profile. Defaulting to raw text_chunk. ---")
                    format_string = "{text_chunk}"

                # Format each doc and join them
                formatted_chunks = []
                for doc in retrieved_docs:
                    try:
                        # Use **doc to unpack the metadata dictionary into the format string
                        formatted_chunks.append(format_string.format(**doc))
                    except KeyError as e:
                        # --- THIS IS THE FIX ---
                        # Fallback: if format fails (e.g., missing key), just use the text_chunk
                        print(f"--- WARNING: RAG metadata missing key {e} for format string. Using fallback. Doc: {doc} ---")
                        if 'text_chunk' in doc:
                            formatted_chunks.append(doc['text_chunk'])
                        # --- END FIX ---
                
                retrieved_context_string = "\n\n".join(formatted_chunks)
                
            print(f"RAG search complete. Context length: {len(retrieved_context_string)}")
        
        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")

        # Inject RAG context into worldview if placeholder exists
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(retrieved_context=retrieved_context_string) # <-- Inject the formatted string
        # --- END MODIFICATION ---

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
        # The {persona_style_rules} placeholder is in formatting_instructions
        # We fill it with the persona's style.
        if "{persona_style_rules}" in formatting_instructions:
            formatting_instructions = formatting_instructions.format(persona_style_rules=style)


        # Build system prompt
        system_prompt = "\n\n".join(filter(None, [
            worldview, memory_injection, spirit_injection, formatting_instructions
        ]))

        obj = {}
        content = "{}"

        try:
            # --- MODIFICATION: The "Adapter" logic ---
            # This is the core change. We branch based on the provider.
            
            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(f"Client for {self.provider} is not an AsyncOpenAI instance")
                
                # --- FIX: Handle different parameter names ---
                params = {
                    "model": self.model,
                    "temperature": 1.0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                }
                
                # --- FIX 2: Changed '==' to 'startswith' ---
                # This catches 'gpt-5', 'gpt-5-nano', 'gpt-5-turbo', etc.
                if self.provider == "openai" and (self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")):
                    params["max_completion_tokens"] = 4096
                else:
                    # Groq and older OpenAI models use 'max_tokens'
                    params["max_tokens"] = 4096
                
                resp = await self.client.chat.completions.create(**params)
                # --- END FIX ---

                content = resp.choices[0].message.content or "{}"
            
            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(f"Client for {self.provider} is not an AsyncAnthropic instance")

                # Anthropic uses `system` param and needs JSON instruction in prompt
                system_prompt_with_json = system_prompt + \
                    "\n\n" + \
                    "You MUST respond in JSON format, with keys 'answer' and 'reflection'."
                
                resp = await self.client.messages.create(
                    model=self.model,
                    system=system_prompt_with_json,
                    max_tokens=4096,
                    temperature=1.0,
                    messages=[
                        {"role": "user", "content": user_prompt}
                    ]
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                     raise ValueError("Gemini model was not initialized correctly.")

                # Gemini needs JSON instruction
                system_prompt_with_json = system_prompt + \
                    "\n\n" + \
                    "You MUST respond in JSON format, with keys 'answer' and 'reflection'."

                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=1.0
                )
                
                # Gemini doesn't have a separate system prompt API for async generate
                full_prompt = system_prompt_with_json + "\n\nUSER_PROMPT:\n" + user_prompt
                
                resp = await self.gemini_model.generate_content_async(
                    full_prompt,
                    generation_config=generation_config
                )
                content = resp.text or "{}"
                
            else:
                raise ValueError(f"Unknown provider '{self.provider}' in IntellectEngine")

            # --- END MODIFICATION ---
            
            # Universal JSON parsing logic
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            obj = json.loads(content)

            answer = obj.get("answer", "").replace("\\n", "\n").strip()
            reflection = obj.get("reflection", "").replace("\\n", "\n").strip()

            # --- MODIFICATION: Pass back the *formatted string* context for auditing ---
            return answer, reflection, retrieved_context_string if self.retriever else ""
            
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            print(f"--- ERROR IN INTELLECT ---: {self.last_error}", file=sys.stderr)
            # --- MODIFICATION: Pass back the *formatted string* context even on failure ---
            return None, None, retrieved_context_string if self.retriever else ""


class WillGate:
    """
    An ethical gatekeeper that evaluates a draft response against a set of values.
    It decides whether to 'approve' or declare a 'violation'.
    """
    def __init__(
        self, 
        client: Any, # Client can be any type
        provider_name: str, # We'll use this to know *what* client is
        model: str, 
        *, 
        values: List[Dict[str, Any]], 
        profile: Optional[Dict[str, Any]] = None, 
        prompt_config: Optional[Dict[str, Any]] = None
    ):
        """Initializes the WillGate."""
        self.client = client
        self.provider = provider_name
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.cache: Dict[str, Tuple[str, str]] = {}
        
        if self.provider == "gemini":
            try:
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                print(f"Error initializing Gemini model {self.model}: {e}", file=sys.stderr)
                self.gemini_model = None


    def _key(self, x_t: str, a_t: str) -> str:
        """Creates a unique cache key for a given prompt and answer."""
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    async def evaluate(self, *, user_prompt: str, draft_answer: str) -> Tuple[str, str]:
        """
        Evaluates a draft answer for alignment with ethical rules and values.
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

        obj = {}
        content = "{}"
        
        try:
            # --- MODIFICATION: Apply the "Adapter" pattern ---
            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(f"Client for {self.provider} is not an AsyncOpenAI instance")
                
                # --- FIX: Handle different parameter names ---
                params = {
                    "model": self.model,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": policy},
                        {"role": "user", "content": prompt}
                    ]
                }
                
                # --- FIX 2: Changed '==' to 'startswith' ---
                if self.provider == "openai" and (self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")):
                    params["max_completion_tokens"] = 1024 # WillGate can be smaller
                else:
                    params["max_tokens"] = 1024
                
                resp = await self.client.chat.completions.create(**params)
                # --- END FIX ---
                
                content = resp.choices[0].message.content or "{}"

            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(f"Client for {self.provider} is not an AsyncAnthropic instance")
                
                resp = await self.client.messages.create(
                    model=self.model,
                    system=policy, # Policy already includes JSON instruction
                    max_tokens=1024,
                    temperature=0.0,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                     raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
                full_prompt = policy + "\n\nUSER_PROMPT_AND_DRAFT:\n" + prompt
                
                resp = await self.gemini_model.generate_content_async(
                    full_prompt,
                    generation_config=generation_config
                )
                content = resp.text or "{}"

            else:
                raise ValueError(f"Unknown provider '{self.provider}' in WillGate")

            # Universal JSON parsing
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            obj = json.loads(content)
            # --- END MODIFICATION ---

            decision = str(obj.get("decision") or "").strip().lower()
            reason = (obj.get("reason") or "").strip()
            if decision not in {"approve", "violation"}: decision = "violation"
            if not reason: reason = "Decision explained by Will policies and the active value set."
            
            tup = (decision, reason)
            self.cache[key] = tup
            return tup
        except Exception as e:
            error_msg = f"Will exception: {type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            print(f"--- ERROR IN WILL ---: {error_msg}", file=sys.stderr)
            return ("violation", error_msg)


class ConscienceAuditor:
    """
    Audits the final, user-facing output for alignment with a set of values.
    This provides the data used for long-term ethical steering (Spirit).
    """
    def __init__(
        self, 
        client: Any, # Client can be any type
        provider_name: str, # We'll use this to know *what* client is
        model: str, 
        values: List[Dict[str, Any]], 
        profile: Optional[Dict[str, Any]] = None, 
        prompt_config: Optional[Dict[str, Any]] = None
    ):
        """Initializes the ConscienceAuditor."""
        self.client = client
        self.provider = provider_name
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        
        if self.provider == "gemini":
            try:
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                print(f"Error initializing Gemini model {self.model}: {e}", file=sys.stderr)
                self.gemini_model = None

    async def evaluate(self, *, final_output: str, user_prompt: str, reflection: str, retrieved_context: str) -> List[Dict[str, Any]]:
        """
        Scores the final output against each configured value using detailed rubrics.
        
        Args:
            final_output: The final AI answer shown to the user.
            user_prompt: The user's original prompt.
            reflection: The AI's internal 'thought' from the Intellect step.
            retrieved_context: The raw RAG context that was retrieved (if any). 
                                (This is now the formatted string)
        """
        prompt_template = self.prompt_config.get("prompt_template")
        if not prompt_template:
            print("--- ERROR IN CONSCIENCE: 'prompt_template' not found in system_prompts.json ---", file=sys.stderr)
            return []

        worldview = self.profile.get("worldview", "")
        
        # --- CHANGE: Inject context into worldview for the audit ---
        # This lets the auditor see the same worldview as the intellect.
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(retrieved_context=retrieved_context if retrieved_context else "[NO DOCUMENTS FOUND]")
        # --- END CHANGE ---

        worldview_injection = ""
        if worldview:
            worldview_template = self.prompt_config.get("worldview_template", "")
            if worldview_template:
                worldview_injection = worldview_template.format(worldview=worldview)

        rubrics = []
        for v in self.values:
            if 'rubric' in v:
                rubrics.append({
                    "value": v['value'],
                    "description": v['rubric'].get('description', ''),
                    "scoring_guide": v['rubric'].get('scoring_guide', [])
                })
        rubrics_str = json.dumps(rubrics, indent=2)

        sys_prompt = prompt_template.format(
            worldview_injection=worldview_injection,
            rubrics_str=rubrics_str
        )
        
        # --- CHANGE: Pass retrieved_context to the auditor ---
        body = (
            f"USER PROMPT:\n{user_prompt}\n\n"
            f"AI's INTERNAL REFLECTION:\n{reflection}\n\n"
            f"DOCUMENTS RETRIEVED BY RAG:\n{retrieved_context if retrieved_context else 'None'}\n\n"
            f"AI's FINAL OUTPUT TO USER:\n{final_output}"
        )
        # --- END CHANGE ---
        
        obj = {}
        content = "{}"
        
        try:
            # --- MODIFICATION: Apply the "Adapter" pattern ---
            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(f"Client for {self.provider} is not an AsyncOpenAI instance")
                
                # --- FIX: Handle different parameter names ---
                params = {
                    "model": self.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": body}
                    ]
                }
                
                # --- FIX 2: Changed '==' to 'startswith' ---
                if self.provider == "openai" and (self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")):
                    params["max_completion_tokens"] = 4096
                else:
                    params["max_tokens"] = 4096
                
                resp = await self.client.chat.completions.create(**params)
                # --- END FIX ---

                content = resp.choices[0].message.content or "{}"
            
            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(f"Client for {self.provider} is not an AsyncAnthropic instance")
                
                resp = await self.client.messages.create(
                    model=self.model,
                    system=sys_prompt, # Prompt already includes JSON instruction
                    max_tokens=4096,
                    temperature=0.1,
                    messages=[
                        {"role": "user", "content": body}
                    ]
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                     raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
                full_prompt = sys_prompt + "\n\nUSER_PROMPT_AND_RESPONSE:\n" + body
                
                resp = await self.gemini_model.generate_content_async(
                    full_prompt,
                    generation_config=generation_config
                )
                content = resp.text or "{}"
                
            else:
                raise ValueError(f"Unknown provider '{self.provider}' in ConscienceAuditor")

            # Universal JSON parsing
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            obj = json.loads(content)
            # --- END MODIFICATION ---
            
            return obj.get("evaluations", [])
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            print(f"--- ERROR IN CONSCIENCE AUDITOR ---: {error_msg}", file=sys.stderr)
            return []


class SpiritIntegrator:
    """
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    This class performs mathematical operations to update the AI's ethical alignment over time.
    """
    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        """Initializes the SpiritIntegrator."""
        self.values = values
        self.beta = beta
        self.value_weights = np.array([v['weight'] for v in self.values]) if self.values else np.array([1.0])
        self._norm_values = [_norm_label(v['value']) for v in self.values] if self.values else []
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        """
        Updates the spirit memory vector based on the latest audit ledger.
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

