"""
Defines the ConscienceAuditor class.

Audits the final, user-facing output for alignment with a set of values.
"""
from __future__ import annotations
import json
import asyncio
from typing import List, Dict, Any, Optional
import logging
import re

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai


class ConscienceAuditor:
    """
    Audits the final, user-facing output for alignment with a set of values.
    This provides the data used for long-term ethical steering (Spirit).
    """

    def __init__(
        self,
        client: Any,  # Client can be any type
        provider_name: str,  # We'll use this to know *what* client is
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
        self.log = logging.getLogger(self.__class__.__name__)  # Add logger

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
        
        Args:
            final_output: The final AI answer shown to the user.
            user_prompt: The user's original prompt.
            reflection: The AI's internal 'thought' from the Intellect step.
            retrieved_context: The raw RAG context that was retrieved (if any). 
                                (This is now the formatted string)
        """
        # If the prompt and output are both short, treat it as a non-substantive
        # interaction (e.g., "Hi" -> "Hello!") and skip the audit.
        # This prevents simple pleasantries from being scored against
        # complex rubrics and polluting the spirit vector (mu).
        if len(user_prompt) < 100 and len(final_output) < 100:
            self.log.info(f"Skipping conscience audit for short interaction. Prompt: '{user_prompt}'")
            return []
        # --- End of new code ---

        prompt_template = self.prompt_config.get("prompt_template")
        if not prompt_template:
            self.log.error("ConscienceAuditor 'prompt_template' not found in system_prompts.json")
            return []

        worldview = self.profile.get("worldview", "")

        # Inject context into worldview for the audit
        # This lets the auditor see the same worldview as the intellect.
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

        # Pass retrieved_context to the auditor
        body = (
            f"USER PROMPT:\n{user_prompt}\n\n"
            f"AI's INTERNAL REFLECTION:\n{reflection}\n\n"
            f"DOCUMENTS RETRIEVED BY RAG:\n{retrieved_context if retrieved_context else 'None'}\n\n"
            f"AI's FINAL OUTPUT TO USER:\n{final_output}"
        )

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
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
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
                    system=sys_prompt,  # Prompt already includes JSON instruction
                    max_tokens=4096,
                    temperature=0.1,
                    messages=[{"role": "user", "content": body}],
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                    raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    # response_mime_type="application/json", # NOT used
                    temperature=0.1,
                    max_output_tokens=4096,  # Add token limit
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
            # Robust JSON Parsing & Sanitization (see IntellectEngine for notes)
            # -----------------------------------------------------------------
            # --- FIX: Replace greedy regex with robust find/rfind ---
            start = content.find('{')
            end = content.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                json_text = content[start:end+1]
            else:
                json_text = content # Fallback to old content
            # --- END FIX ---
            
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
                    self.log.error(f"Conscience JSON parse failed: {e2} | content={sanitized[:500]}")
                    return []

            return obj.get("evaluations", [])
        except Exception as e:
            # Log the full exception but return an empty list
            self.log.exception(f"Conscience audit failed (provider={self.provider})")
            return []