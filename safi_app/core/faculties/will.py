"""
Defines the WillGate class.

An ethical gatekeeper that evaluates a draft response against a set of values.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any, Tuple, Optional
import re
import logging

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai

# Relative imports adjusted for the new directory structure
from ...utils import normalize_text, dict_sha256


class WillGate:
    """
    An ethical gatekeeper that evaluates a draft response against a set of values.
    It decides whether to 'approve' or declare a 'violation'.
    """

    def __init__(
        self,
        client: Any,  # Client can be any type
        provider_name: str,  # We'll use this to know *what* client is
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
        self.log = logging.getLogger(self.__class__.__name__)  # Add logger

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
        Returns: (decision, reason)
        """
        key = self._key(user_prompt, draft_answer)
        if key in self.cache:
            decision, reason = self.cache[key]
            return decision, reason

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
                # The footer is now simplified
                "Return a single JSON object with keys: decision, reason.",
            ),
        ]
        policy = "\n".join(filter(None, policy_parts))
        prompt = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"

        obj = {}
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
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": policy},
                        {"role": "user", "content": prompt},
                    ],
                }

                if self.provider == "openai" and (
                    self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")
                ):
                    params["max_completion_tokens"] = 1024  # WillGate can be smaller
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
                    # response_mime_type="application/json", # NOT used
                    temperature=0.0,
                    max_output_tokens=1024,  # Add token limit
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
                json_text = content[start:end+1]
            else:
                json_text = content # Fallback to old content

            try:
                obj = json.loads(json_text)
            except json.JSONDecodeError:
                # Fallback to sanitization if primary parse fails
                sanitized = json_text.replace("\r", " ").replace("\n", " ")
                sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
                sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
                try:
                    obj = json.loads(sanitized)
                except json.JSONDecodeError as e2:
                    error_msg = (
                        f"Will exception: JSONDecodeError: {e2} (provider={self.provider}, model={self.model}) | "
                        f"content={sanitized[:500]}"
                    )
                    self.log.error(error_msg) # Log the parse error
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
            return decision, reason
        except Exception as e:
            error_msg = (
                f"Will exception: {type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            )
            self.log.exception(f"WillGate evaluation failed (provider={self.provider})") # Log the full exception
            return ("violation", "Internal evaluation error")