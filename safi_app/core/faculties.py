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
    
    This class integrates various inputs (user prompt, memory, ethical feedback, and
    retrieved context) into a single system prompt, queries the language model,
    and parses the response into separate answer and reflection components.
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
        user_profile_json: str, # <-- ADDED
        plugin_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.
        """
        self.last_error = None

        # 1. Get RAG context (from files)
        retrieved_context_string = ""
        if self.retriever:
            retrieved_docs = self.retriever.search(user_prompt)  # <-- Get the List[Dict]

            if not retrieved_docs:
                retrieved_context_string = "[NO DOCUMENTS FOUND]"
            else:
                # Get the formatting string from the persona profile
                format_string = self.profile.get("rag_format_string")
                if not format_string:
                    # Fallback if no format string is defined
                    format_string = "{text_chunk}"

                # Format each doc and join them
                formatted_chunks = []
                for doc in retrieved_docs:
                    try:
                        # Use **doc to unpack the metadata dictionary into the format string
                        formatted_chunks.append(format_string.format(**doc))
                    except KeyError:
                        # Fallback: if format fails (e.g., missing key), just use the text_chunk
                        if "text_chunk" in doc:
                            formatted_chunks.append(doc["text_chunk"])

                retrieved_context_string = "\n\n".join(formatted_chunks)
        
        # 2. Get Plugin context (from APIs, scrapers)
        plugin_context_string = ""
        if plugin_context:
            
            # --- Helper to format one stock data object ---
            def format_stock_table(stock_data: Dict[str, Any]) -> str:
                stock_table_md = f"## {stock_data.get('Company Name', 'N/A')} ({stock_data.get('Ticker Symbol', 'N/A')})\n"
                stock_table_md += f"| Metric | Value |\n"
                stock_table_md += f"| --- | --- |\n"
                
                # Filter to a key set of metrics for context, to avoid overwhelming the prompt
                metrics_to_show = [
                    "Current Price", "Previous Close", "Day's Range", "52-Week Range",
                    "Volume", "Average Volume", "Market Cap", "P/E Ratio (TTM)",
                   "Beta (5Y Monthly)", "Analyst Target Price",
                    "Sector"
                ]
                
                for key in metrics_to_show:
                    value = stock_data.get(key)
                    if value is not None:
                        # Format numbers nicely
                        if isinstance(value, (int, float)):
                            if key == "Dividend Yield":
                                value = f"{value * 100:.2f}%"
                            elif key in ["P/E Ratio (TTM)", "Beta (5Y Monthly)"]:
                                value = f"{value:.2f}"
                            elif key in ["Volume", "Average Volume", "Market Cap"]:
                                value = f"{value:,}"
                            elif key in ["Current Price", "Previous Close", "Analyst Target Price"]:
                                value = f"${value:,.2f}"
                        stock_table_md += f"| {key} | {value} |\n"
                return stock_table_md + "\n"
            
            # --- Format Fiduciary Data (Single) ---
            if "stock_data" in plugin_context:
                plugin_context_string += f"CONTEXT: I have fetched the following financial data as requested:\n\n"
                plugin_context_string += format_stock_table(plugin_context["stock_data"])

            # --- Format Fiduciary Data (Multiple) ---
            elif "stock_data_list" in plugin_context:
                plugin_context_string += f"CONTEXT: I have fetched financial data for multiple companies as requested:\n\n"
                for stock_data in plugin_context["stock_data_list"]:
                    plugin_context_string += format_stock_table(stock_data)
            
            # --- Format Bible Scholar: Individual Reading ---
            if "individual_reading" in plugin_context:
                reading = plugin_context["individual_reading"]
                date = plugin_context.get("date", "Today's Reading")
                
                reading_md = f"CONTEXT: The user requested a specific reading. I have fetched the following text for {date}:\n\n"
                reading_md += f"### {reading.get('title', '')} ({reading.get('citation', '')})\n"
                reading_md += f"{reading.get('text', 'Reading text not available.')}\n\n"
                plugin_context_string += reading_md

            # --- Format Plugin Errors ---
            if "plugin_error" in plugin_context:
                error_md = f"CONTEXT: I encountered an error trying to fetch data for the user.\n"
                error_md += f"Error Message: {plugin_context['plugin_error']}\n"
                error_md += "Please inform the user about this error.\n\n"
                plugin_context_string += error_md


        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")

        # 3. Combine ALL context
        # We prioritize plugin context first, then RAG context
        full_context_injection = "\n\n".join(filter(None, [plugin_context_string, retrieved_context_string]))
        
        # 4. Inject into worldview
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=full_context_injection if full_context_injection else "[NO DOCUMENTS FOUND]"
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

        # --- NEW: INJECT THE USER'S LONG-TERM PROFILE ---
        user_profile_injection = ""
        if user_profile_json and user_profile_json != "{}":
            # Find the template in prompt_config, default to a sensible string if not found
            profile_template = self.prompt_config.get("user_profile_template", 
                "CONTEXT: Here is the user's profile. Use these facts to tailor your educational examples.\n<user_profile>{user_profile_json}</user_profile>")
            
            if profile_template:
                user_profile_injection = profile_template.format(
                    user_profile_json=user_profile_json
                )
        # --- END NEW ---

        formatting_instructions = self.prompt_config.get("formatting_instructions", "")
        # The {persona_style_rules} placeholder is in formatting_instructions
        # We fill it with the persona's style.
        if "{persona_style_rules}" in formatting_instructions:
            formatting_instructions = formatting_instructions.format(
                persona_style_rules=style
            )

        # Build system prompt
        system_prompt = "\n\n".join(
            filter(None, [
                worldview, 
                user_profile_injection, # <-- ADDED
                memory_injection, 
                spirit_injection, 
                formatting_instructions
            ])
        )
        
        # This will be passed to the Conscience for auditing
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")

        obj = {}
        content = "{}"

        try:
            # This is the core change. We branch based on the provider.

            if self.provider == "groq" or self.provider == "openai":
                if not isinstance(self.client, AsyncOpenAI):
                    raise TypeError(
                        f"Client for {self.provider} is not an AsyncOpenAI instance"
                    )

                params = {
                    "model": self.model,
                    "temperature": 1.0,
                    # --- "response_format" is no longer used here ---
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }

                # This catches 'gpt-4o', 'gpt-5', etc.
                if self.provider == "openai" and (
                    self.model.startswith("gpt-4o") or self.model.startswith("gpt-5")
                ):
                    params["max_completion_tokens"] = 4096
                else:
                    # Groq and older OpenAI models use 'max_tokens'
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
                    system=system_prompt,  # Use the base system prompt
                    max_tokens=4096,
                    temperature=1.0,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = resp.content[0].text or "{}"

            elif self.provider == "gemini":
                if not self.gemini_model:
                    raise ValueError("Gemini model was not initialized correctly.")

                generation_config = genai.types.GenerationConfig(
                    temperature=1.0,
                    max_output_tokens=4096,
                )

                # We pass the full prompt (which includes system instructions) as the content.
                full_prompt = (
                    system_prompt + "\n\nUSER_PROMPT:\n" + user_prompt
                )

                resp = await self.gemini_model.generate_content_async(
                    full_prompt, generation_config=generation_config
                )
                content = resp.text or "{}"

            else:
                raise ValueError(
                    f"Unknown provider '{self.provider}' in IntellectEngine"
                )

            # -----------------------------------------------------------------
            # NEW Robust Parsing & Sanitization Block
            # -----------------------------------------------------------------
            
            answer = ""
            reflection = ""
            delimiter_text = "---REFLECTION---" # Check for the text only

            if delimiter_text in content:
                # --- Priority 1: Model used the delimiter text ---
                parts = content.split(delimiter_text)
                answer = parts[0].strip()
                
                # Find the JSON part in the *last* segment
                json_part = ""
                json_part_raw = parts[-1]
                json_match = re.search(r"\{[\s\S]*\}", json_part_raw)
                
                if json_match:
                    json_part = json_match.group(0).strip()
                else:
                    # Maybe the last part *is* the JSON but regex failed?
                    json_part = json_part_raw.strip()

                try:
                    # Sanitize and parse the JSON part
                    # --- FIX: Replace faulty regex with robust find/rfind ---
                    start = json_part.find('{')
                    end = json_part.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        json_text = json_part[start:end+1]
                        # Still sanitize, as it helps with trailing commas
                        json_part_sanitized = re.sub(r",\s*([}\]])", r"\1", json_text.replace("\n", " "))
                        obj = json.loads(json_part_sanitized)
                        reflection = obj.get("reflection", "Parsed reflection from delimiter.").strip()
                    else:
                        raise json.JSONDecodeError("No valid JSON object found", json_part, 0)
                    # --- END FIX ---
                except json.JSONDecodeError as e:
                    self.log.warning(f"Failed to parse JSON after delimiter: {e} | content={json_part[:100]}")
                    reflection = "Failed to parse reflection JSON."
                    # The answer is still good, so we keep it.

            else:
                # --- Priority 2: Model "forgot" delimiter but still sent JSON ---
                self.log.warning(f"Model did not use delimiter. (provider={self.provider})")
                json_match = re.search(r"\{[\s\S]*\}", content) # Use [\s\S] for multiline

                if json_match:
                    json_part = json_match.group(0).strip()
                    answer = content[:json_match.start()].strip() # Everything BEFORE the JSON
                    
                    if not answer:
                        answer = f"[Answer missing, model only sent JSON: {json_part}]"

                    try:
                        # Sanitize and parse
                        # --- FIX: Replace faulty regex with robust find/rfind ---
                        start = json_part.find('{')
                        end = json_part.rfind('}')
                        if start != -1 and end != -1 and end > start:
                            json_text = json_part[start:end+1]
                            json_part_sanitized = re.sub(r",\s*([}\]])", r"\1", json_text.replace("\n", " "))
                            obj = json.loads(json_part_sanitized)
                            reflection = obj.get("reflection", "Parsed reflection from regex search.").strip()
                        else:
                            raise json.JSONDecodeError("No valid JSON object found", json_part, 0)
                        # --- END FIX ---
                    except json.JSONDecodeError as e:
                        self.log.warning(f"Regex JSON parse failed: {e} | content={json_part[:100]}")
                        # Fallthrough to Priority 3...
                        answer = content.strip() # The parse failed, treat all text as answer
                        reflection = "Failed to parse salvaged JSON."

                else:
                    # --- Priority 3: Model sent raw text (Psalm 51 case) ---
                    self.log.warning(f"No JSON found. Salvaging raw text. (provider={self.provider})")
                    answer = content.strip()
                    reflection = "Salvaged raw output; model failed to format as JSON."

            # Final check to prevent empty answers
            if not answer.strip():
                answer = "[Model returned an empty answer]"
                reflection = "Model returned empty answer."

            return (
                answer.replace("\\n", "\n"),
                reflection.replace("\\n", "\n"),
                final_context_for_audit, # Pass all context to be audited
            )

        except Exception as e:
            self.last_error = (
                f"{type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            )
            self.log.exception(f"Intellect generation failed (provider={self.provider}, model={self.model})") 
            return None, None, final_context_for_audit


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

    # --- MODIFIED: WillGate.evaluate now returns a tuple of 2 values ---
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
                    error_msg = (
                        f"Will exception: JSONDecodeError: {e2} (provider={self.provider}, model={self.model}) | "
                        f"content={sanitized[:500]}"
                    )
                    self.log.error(error_msg) # Log the parse error
                    # --- MODIFIED: Return two values on internal error ---
                    return ("violation", "Internal evaluation error")

            decision = str(obj.get("decision") or "").strip().lower()
            reason = (obj.get("reason") or "").strip()
            
            if decision not in {"approve", "violation"}:
                decision = "violation"
                
            if not reason:
                reason = (
                    "Decision explained by Will policies and the active value set."
                )

            # --- MODIFIED: Return two values now ---
            tup = (decision, reason)
            self.cache[key] = tup
            return decision, reason
        except Exception as e:
            error_msg = (
                f"Will exception: {type(e).__name__}: {e} (provider={self.provider}, model={self.model})"
            )
            self.log.exception(f"WillGate evaluation failed (provider={self.provider})") # Log the full exception
            # --- MODIFIED: Return two values on exception ---
            return ("violation", "Internal evaluation error")


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


class SpiritIntegrator:
    """
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    This class performs mathematical operations to update the AI's ethical alignment over time.
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
