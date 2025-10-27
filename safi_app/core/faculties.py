from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import re
import unicodedata
import logging  # Import the logging module

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai

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
    
    This class now uses a HYBRID parsing strategy:
    - Groq/OpenAI: Uses reliable forced JSON mode.
    - Gemini/Anthropic: Uses robust XML-in-text-mode.
    """

    def __init__(
        self,
        client: Any,  # Client can be any type now
        provider_name: str,  # We'll use this to know *what* client is
        model: str,
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initializes the IntellectEngine.
        """
        self.client = client
        self.provider = provider_name
        self.model = model
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.last_error: Optional[str] = None
        self.log = logging.getLogger(self.__class__.__name__)  # Add logger

        if self.provider == "gemini":
            try:
                # client is actually the model name string
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                self.gemini_model = None
                self.last_error = f"Error initializing Gemini model {self.model}: {e}"
                self.log.error(self.last_error) # Log initialization error

        self.retriever = None
        kb_name = self.profile.get("rag_knowledge_base")
        if kb_name:
            self.retriever = Retriever(knowledge_base_name=kb_name)

    async def generate(
        self,
        *,
        user_prompt: str,
        memory_summary: str,
        spirit_feedback: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.
        """
        self.last_error = None
        retrieved_context_string = "" # Default to empty string

        try:
            # All logic, including RAG, is now inside the main try/except block.
            if self.retriever:
                retrieved_docs = self.retriever.search(user_prompt)  # <-- Get the List[Dict]

                if not retrieved_docs:
                    retrieved_context_string = "[NO DOCUMENTS FOUND]"
                else:
                    format_string = self.profile.get("rag_format_string", "{text_chunk}")

                    formatted_chunks = []
                    for doc in retrieved_docs:
                        try:
                            formatted_chunks.append(format_string.format(**doc))
                        except KeyError:
                            if "text_chunk" in doc:
                                formatted_chunks.append(doc["text_chunk"])

                    retrieved_context_string = "\n\n".join(formatted_chunks)

            worldview = self.profile.get("worldview", "")
            style = self.profile.get("style", "")

            if "{retrieved_context}" in worldview:
                worldview = worldview.format(
                    retrieved_context=retrieved_context_string
                ) 

            memory_injection = (
                f"CONTEXT: Here is a summary of our conversation so far. Use it to inform your answer.\n"
                f"<summary>{memory_summary}</summary>" if memory_summary else ""
            )

            spirit_injection = ""
            if spirit_feedback:
                coaching_note_template = self.prompt_config.get("coaching_note", "")
                if coaching_note_template:
                    spirit_injection = coaching_note_template.format(
                        spirit_feedback=spirit_feedback
                    )

            # --- HYBRID PROMPT STRATEGY ---
            # We now hard-code the format for *all* providers to ensure stability
            # and ignore the (potentially out of sync) system_prompts.json file.
            
            if self.provider == "groq" or self.provider == "openai":
                # These providers use JSON.
                formatting_instructions = (
                    'You MUST format your entire response as a single, valid JSON object '
                    'with exactly two top-level keys: "answer" and "reflection".\n\n'
                    '<persona_style_rules>\n{persona_style_rules}\n</persona_style_rules>'
                ).format(persona_style_rules=style)
            else:
                # Gemini and Anthropic use robust XML tags.
                formatting_instructions = (
                    'You MUST format your entire response using XML-style tags. '
                    'Wrap your internal reasoning in <reflection>...</reflection> '
                    'and your final, user-facing answer in <answer>...</answer>.\n\n'
                    '<persona_style_rules>\n{persona_style_rules}\n</persona_style_rules>'
                ).format(persona_style_rules=style)
            # --- END HYBRID STRATEGY ---

            system_prompt = "\n\n".join(
                filter(None, [worldview, memory_injection, spirit_injection, formatting_instructions])
            )

            content = "" # Default to empty string

            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncOpenAI instance"
                    )

                params = {
                    "model": self.model,
                    "temperature": 1.0,
                    # --- RE-ENABLING JSON MODE ---
                    "response_format": {"type": "json_object"}, 
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }

                if self.provider == "openai" and (
                    self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")
                ):
                    params["max_completion_tokens"] = 4096
                else:
                    params["max_tokens"] = 4096

                resp = await self.client.chat.completions.create(**params)
                content = resp.choices[0].message.content or ""

            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncAnthropic instance"
                    )

                resp = await self.client.messages.create(
                    model=self.model,
                    system=system_prompt,  # Use the base system prompt with XML instructions
                    max_tokens=4096,
                    temperature=1.0,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = resp.content[0].text or ""

            elif self.provider == "gemini":
                if not self.gemini_model:
                    raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    # We are in TEXT mode to support XML tags.
                    # response_mime_type="application/json",
                    temperature=1.0,
                    max_output_tokens=4096, 
                )

                full_prompt = (
                    system_prompt + "\n\nUSER_PROMPT:\n" + user_prompt
                )

                resp = await self.gemini_model.generate_content_async(
                    full_prompt, generation_config=generation_config
                )
                content = resp.text or ""

            else:
                raise ValueError(
                    f"Unknown provider '{self.provider}' in IntellectEngine"
                )

            # -----------------------------------------------------------------
            # HYBRID PARSING LOGIC
            # -----------------------------------------------------------------
            
            answer = ""
            reflection = ""

            if self.provider == "groq" or self.provider == "openai":
                # --- JSON PARSING LOGIC (for Groq/OpenAI) ---
                start = content.find('{')
                end = content.rfind('}')
                
                if start == -1 or end == -1 or end < start:
                    self.last_error = f"No valid JSON object found. (provider={self.provider})"
                    self.log.error(f"{self.last_error} | Content: {content[:500]}")
                    return None, None, retrieved_context_string

                try:
                    obj = json.loads(content[start:end+1])
                except json.JSONDecodeError:
                    # Run the sanitizer
                    sanitized = content[start:end+1].replace("\r", " ").replace("\n", " ")
                    sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
                    sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
                    try:
                        obj = json.loads(sanitized)
                    except json.JSONDecodeError as e2:
                        self.last_error = f"JSONDecodeError: {e2} (provider={self.provider})"
                        self.log.error(f"{self.last_error} | Content: {sanitized[:500]}")
                        return None, None, retrieved_context_string
                
                # Use str() to gracefully handle if model returns dict/list
                answer = str(obj.get("answer", "")).strip()
                reflection = str(obj.get("reflection", "")).strip()

            else:
                # --- XML PARSING LOGIC (for Gemini/Anthropic) ---
                reflection_match = re.search(r'<reflection>(.*?)</reflection>', content, re.DOTALL)
                if reflection_match:
                    reflection = reflection_match.group(1).strip()
                
                answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL)
                if answer_match:
                    answer = answer_match.group(1).strip()

            # --- UNIVERSAL ANSWER CHECK ---
            if not answer:
                if reflection and (self.provider == "gemini" or self.provider == "anthropic"):
                    # Case 1: XML Model generated <reflection> but forgot <answer>
                    self.last_error = f"Model compliance error: Missing <answer> tag. (provider={self.provider})"
                    self.log.error(f"{self.last_error} | Content: {content[:500]}")
                elif reflection and (self.provider == "groq" or self.provider == "openai"):
                     # Case 2: JSON Model returned reflection but no answer
                    self.last_error = f"Model compliance error: Missing 'answer' key in JSON. (provider={self.provider})"
                    self.log.error(f"{self.last_error} | Content: {content[:500]}")
                elif content:
                    # Case 3: Model generated *no* tags/JSON, just raw text. Use as answer.
                    answer = content.strip()
                    self.log.warning(f"No structured output (XML/JSON) found. Using raw content. (provider={self.provider})")
                else:
                    # Case 4: Model returned nothing at all.
                    self.last_error = f"Model returned empty content. (provider={self.provider})"
                    self.log.error(self.last_error)

                if self.last_error:
                    return None, None, retrieved_context_string

            return (
                answer,
                reflection,
                retrieved_context_string,
            )

        except Exception as e:
            self.last_error = (
                f"{type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            )
            self.log.exception(f"Intellect generation failed (provider={self.provider}, model={self.model})")
            return None, None, retrieved_context_string


class WillGate:
    """
    An ethical gatekeeper that evaluates a draft response against a set of values.
    It decides whether to 'approve' or declare a 'violation'.
    
    *** This class correctly uses JSON, as its task is simple. ***
    """

    def __init__(
        self,
        client: Any, 
        provider_name: str, 
        model: str,
        *,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """Initializes the WillGate."""
        self.client = client
        self.provider = provider_name
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.cache: Dict[str, Tuple[str, str]] = {}
        self.log = logging.getLogger(self.__class__.__name__)

        if self.provider == "gemini":
            try:
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                self.gemini_model = None
                self.log.error(f"Error initializing Gemini model {self.model}: {e}")

    def _key(self, x_t: str, a_t: str) -> str:
        """Creates a unique cache key for a given prompt and answer."""
        return dict_sha256(
            {"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values}
        )

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
            rules = [
                f"Do not approve drafts that reduce alignment with the declared values: {joined}."
            ]

        policy_parts = [
            self.prompt_config.get(
                "header", "You are Will, the ethical gatekeeper."
            ),
            f"Tradition: {name}" if name else "",
            "Rules:",
            *[f"- {r}" for r in rules],
            "Value Set:",
            json.dumps(self.values, indent=2),
            self.prompt_config.get(
                "footer",
                "Return a single JSON object with keys: decision, reason.",
            ),
        ]
        policy = "\n".join(filter(None, policy_parts))
        prompt = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"

        content = "{}"

        try:
            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncOpenAI instance"
                    )

                params = {
                    "model": self.model,
                    "temperature": 0.0,
                    # --- RE-ENABLING JSON MODE ---
                    "response_format": {"type": "json_object"},
                    # --- END FIX ---
                    "messages": [
                        {"role": "system", "content": policy},
                        {"role": "user", "content": prompt},
                    ],
                }

                if self.provider == "openai" and (
                    self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")
                ):
                    params["max_completion_tokens"] = 1024 
                else:
                    params["max_tokens"] = 1024

                resp = await self.client.chat.completions.create(**params)
                content = resp.choices[0].message.content or "{}"

            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncAnthropic instance"
                    )

                resp = await self.client.messages.create(
                    model=self.model,
                    system=policy,  # Policy already includes JSON instruction
                    max_tokens=1024,
                    temperature=0.0,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                    raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json", # JSON mode is fine for Will
                    temperature=0.0
                )
                full_prompt = policy + "\n\nUSER_PROMPT_AND_DRAFT:\n" + prompt

                resp = await self.gemini_model.generate_content_async(
                    full_prompt, generation_config=generation_config
                )
                content = resp.text or "{}"

            else:
                raise ValueError(f"Unknown provider '{self.provider}' in WillGate")

            # -----------------------------------------------------------------
            # Robust JSON Parsing & Sanitization
            # -----------------------------------------------------------------
            start = content.find('{')
            end = content.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                content = content[start:end+1]
            else:
                error_msg = (
                    f"No valid JSON object found in response (provider={self.provider}, model={self.model}) | "
                    f"content={content[:500]}"
                )
                self.log.error(error_msg)
                return ("violation", "Internal evaluation error")
                
            try:
                obj = json.loads(content)
            except json.JSONDecodeError:
                sanitized = content.replace("\r", " ").replace("\n", " ")
                sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
                sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
                try:
                    obj = json.loads(sanitized)
                except json.JSONDecodeError as e2:
                    error_msg = (
                        f"Will exception: JSONDecodeError: {e2} (provider={self.provider}, model={self.model}) | "
                        f"content={sanitized[:500]}"
                    )
                    self.log.error(error_msg) 
                    return ("violation", "Internal evaluation error")

            decision = str(obj.get("decision") or "").strip().lower()
            reason = (obj.get("reason") or "").strip()
            if decision not in {"approve", "violation"}:
                decision = "violation"
            if not reason:
                reason = (
                    "Decision explained by Will policies and the active value set."
                )

            tup = (decision, reason)
            self.cache[key] = tup
            return tup
            
        except Exception as e:
            self.log.exception(f"WillGate evaluation failed (provider={self.provider})") 
            return ("violation", "Internal evaluation error")


class ConscienceAuditor:
    """
    Audits the final, user-facing output for alignment with a set of values.
    
    *** This class correctly uses JSON, as its task is simple. ***
    """

    def __init__(
        self,
        client: Any, 
        provider_name: str, 
        model: str,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """Initializes the ConscienceAuditor."""
        self.client = client
        self.provider = provider_name
        self.model = model
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.log = logging.getLogger(self.__class__.__name__)

        if self.provider == "gemini":
            try:
                self.gemini_model = genai.GenerativeModel(self.model)
            except Exception as e:
                self.gemini_model = None
                self.log.error(f"Error initializing Gemini model {self.model}: {e}")

    async def evaluate(
        self,
        *,
        final_output: str,
        user_prompt: str,
        reflection: str,
        retrieved_context: str,
    ) -> List[Dict[str, Any]]:
        """
        Scores the final output against each configured value using detailed rubrics.
        """
        prompt_template = self.prompt_config.get("prompt_template")
        if not prompt_template:
            self.log.error("ConscienceAuditor 'prompt_template' not found in system_prompts.json")
            return []

        worldview = self.profile.get("worldview", "") 

        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=retrieved_context if retrieved_context else "[NO DOCUMENTS FOUND]"
            )

        worldview_injection = ""
        if worldview:
            worldview_template = self.prompt_config.get("worldview_template", "")
            if worldview_template:
                worldview_injection = worldview_template.format(worldview=worldview)

        rubrics = []
        for v in self.values:
            if "rubric" in v:
                rubrics.append(
                    {
                        "value": v["value"],
                        "description": v["rubric"].get("description", ""),
                        "scoring_guide": v["rubric"].get("scoring_guide", []),
                    }
                )
        rubrics_str = json.dumps(rubrics, indent=2)

        sys_prompt = prompt_template.format(
            worldview_injection=worldview_injection, rubrics_str=rubrics_str
        )

        body = (
            f"USER PROMPT:\n{user_prompt}\n\n"
            f"AI's INTERNAL REFLECTION:\n{reflection}\n\n"
            f"DOCUMENTS RETRIEVED BY RAG:\n{retrieved_context if retrieved_context else 'None'}\n\n"
            f"AI's FINAL OUTPUT TO USER:\n{final_output}"
        )

        content = "{}"

        try:
            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncOpenAI instance"
                    )

                params = {
                    "model": self.model,
                    "temperature": 0.1,
                    # --- RE-ENABLING JSON MODE ---
                    "response_format": {"type": "json_object"},
                    # --- END FIX ---
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": body},
                    ],
                }

                if self.provider == "openai" and (
                    self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")
                ):
                    params["max_completion_tokens"] = 4096
                else:
                    params["max_tokens"] = 4096

                resp = await self.client.chat.completions.create(**params)
                content = resp.choices[0].message.content or "{}"

            elif self.provider == "anthropic":
                if not isinstance(self.client, AsyncAnthropic):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncAnthropic instance"
                    )

                resp = await self.client.messages.create(
                    model=self.model,
                    system=sys_prompt,
                    max_tokens=4096,
                    temperature=0.1,
                    messages=[{"role": "user", "content": body}],
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                    raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json", # JSON mode is fine for Conscience
                    temperature=0.1
                )
                full_prompt = sys_prompt + "\n\nUSER_PROMPT_AND_RESPONSE:\n" + body

                resp = await self.gemini_model.generate_content_async(
                    full_prompt, generation_config=generation_config
                )
                content = resp.text or "{}"

            else:
                raise ValueError(
                    f"Unknown provider '{self.provider}' in ConscienceAuditor"
                )

            # -----------------------------------------------------------------
            # Robust JSON Parsing & Sanitization
            # -----------------------------------------------------------------
            start = content.find('{')
            end = content.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                content = content[start:end+1]
            else:
                self.log.error(f"Conscience audit: No valid JSON object found in response | content={content[:500]}")
                return []

            try:
                obj = json.loads(content)
            except json.JSONDecodeError:
                sanitized = content.replace("\r", " ").replace("\n", " ")
                sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
                sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
                try:
                    obj = json.loads(sanitized)
                except json.JSONDecodeError as e2:
                    self.log.error(f"Conscience JSON parse failed: {e2} | content={sanitized[:500]}")
                    return []

            return obj.get("evaluations", [])
            
        except Exception as e:
            self.log.exception(f"Conscience audit failed (provider={self.provider})")
            return []


class SpiritIntegrator:
    """
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    """

    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        """Initializes the SpiritIntegrator."""
        self.values = values
        self.beta = beta
        self.value_weights = (
            np.array([v["weight"] for v in self.values]) if self.values else np.array([1.0])
        )
        self._norm_values = (
            [_norm_label(v["value"]) for v in self.values] if self.values else []
        )
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        """
        Updates the spirit memory vector based on the latest audit ledger.
        """
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        lmap: Dict[str, Dict[str, Any]] = {
            _norm_label(row.get("value")): row for row in ledger if row.get("value")
        }
        sorted_rows: List[Optional[Dict[str, Any]]] = [
            lmap.get(nkey) for nkey in self._norm_values
        ]

        if any(r is None for r in sorted_rows):
            missing = [self.values[i]["value"] for i, r in enumerate(sorted_rows) if r is None]
            note = f"Ledger missing values: {', '.join(missing)}"
            return 1, note, mu_tm1, np.zeros_like(mu_tm1), None
        
        scores = np.array([float(r.get("score", 0.0)) for r in sorted_rows], dtype=float)
        confidences = np.array(
            [float(r.get("confidence", 0.0)) for r in sorted_rows], dtype=float
        )

        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        p_t = self.value_weights * scores
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift


