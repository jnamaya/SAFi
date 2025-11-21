"""
Defines the IntellectEngine class.

Core cognitive faculty for generating responses.
"""
from __future__ import annotations
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import re
import logging

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai

# Relative imports adjusted for the new directory structure
from ...utils import normalize_text, dict_sha256
from ..retriever import Retriever


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
            # NOTE: Adjusted import path for retriever
            self.retriever = Retriever(knowledge_base_name=kb_name)

    async def generate(
        self,
        *,
        user_prompt: str,
        memory_summary: str,
        spirit_feedback: str,
        user_profile_json: str,
        user_name: Optional[str] = None,
        plugin_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.
        """
        self.last_error = None

        # --- NEW GENERIC LOGIC BLOCK ---

        # 1. Determine the correct query for the RAG
        query_for_rag = user_prompt
        if plugin_context and plugin_context.get("rag_query_override"):
            query_for_rag = plugin_context["rag_query_override"]
            self.log.info(f"Plugin provided RAG override. New query: {query_for_rag}")

        # 2. Get RAG context (from files) using the correct query
        retrieved_context_string = ""
        if self.retriever:
            # This now uses the correct query: "Luke 18:35-43" or "What about Job?"
            retrieved_docs = self.retriever.search(query_for_rag)
            
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
        
        # 3. Get pre-formatted Plugin context
        plugin_context_string = ""
        if plugin_context:
            
            # --- This block is now GENERIC ---
            # Any plugin can return this key to add context.
            if plugin_context.get("preformatted_context_string"):
                plugin_context_string += plugin_context["preformatted_context_string"]
            
            # --- This block is now GENERIC ---
            if "plugin_error" in plugin_context:
                error_md = f"CONTEXT: I encountered an error trying to fetch data for the user.\n"
                error_md += f"Error Message: {plugin_context['plugin_error']}\n"
                error_md += "Please inform the user about this error.\n\n"
                plugin_context_string += error_md
        
        # --- END NEW GENERIC LOGIC BLOCK ---

        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")

        # 4. Combine ALL context
        # Now, retrieved_context_string has the *correct* Bible text (if citation)
        # and plugin_context_string has the generic pre-formatted string.
        full_context_injection = "\n\n".join(filter(None, [plugin_context_string, retrieved_context_string]))
        
        # 5. Inject into worldview
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

        # --- INJECT THE USER'S NAME ---
        user_name_injection = ""
        if user_name:
            # Find the template in prompt_config, default to a sensible string if not found
            name_template = self.prompt_config.get("user_name_template", 
                "CONTEXT: You are speaking to a user named {user_name}. Use their name when appropriate (e.g., 'Hi {user_name}, ...').")
            
            if name_template:
                user_name_injection = name_template.format(
                    user_name=user_name
                )

        # --- INJECT THE USER'S LONG-TERM PROFILE ---
        user_profile_injection = ""
        if user_profile_json and user_profile_json != "{}":
            # Find the template in prompt_config, default to a sensible string if not found
            profile_template = self.prompt_config.get("user_profile_template", 
                "CONTEXT: Here is the user's profile. Use these facts to tailor your educational examples.\n<user_profile>{user_profile_json}</user_profile>")
            
            if profile_template:
                user_profile_injection = profile_template.format(
                    user_profile_json=user_profile_json
                )

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
                user_name_injection,
                user_profile_injection,
                memory_injection, 
                spirit_injection, 
                formatting_instructions
            ])
        )
        
        # ---The "P.S." Reminder ---
        formatting_reminder = self.prompt_config.get("formatting_reminder", "")
        
        final_user_message = user_prompt + formatting_reminder
        
        # This will be passed to the Conscience for auditing
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")

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
                    "temperature": 1.0,
                    # --- "response_format" is no longer used here ---
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": final_user_message}, # USE FINAL MESSAGE
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
                    system=system_prompt,
                    max_tokens=4096,
                    temperature=1.0,
                    messages=[{"role": "user", "content": final_user_message}], # USE FINAL MESSAGE
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
                    system_prompt + "\n\nUSER_PROMPT:\n" + final_user_message # USE FINAL MESSAGE
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
            # Robust Parsing & Sanitization Block
            # -----------------------------------------------------------------
            
            answer = ""
            reflection = ""
            delimiter_text = "---REFLECTION---"

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
                    json_part = json_part_raw.strip()

                try:
                    # Sanitize and parse the JSON part
                    start = json_part.find('{')
                    end = json_part.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        json_text = json_part[start:end+1]
                        json_part_sanitized = re.sub(r",\s*([}\]])", r"\1", json_text.replace("\n", " "))
                        obj = json.loads(json_part_sanitized)
                        reflection = obj.get("reflection", "Parsed reflection from delimiter.").strip()
                    else:
                        raise json.JSONDecodeError("No valid JSON object found", json_part, 0)
                except json.JSONDecodeError as e:
                    self.log.warning(f"Failed to parse JSON after delimiter: {e} | content={json_part[:100]}")
                    reflection = "Failed to parse reflection JSON."

            else:
                # --- Priority 2: Model "forgot" delimiter but still sent JSON ---
                self.log.warning(f"Model did not use delimiter. (provider={self.provider})")
                json_match = re.search(r"\{[\s\S]*\}", content)

                if json_match:
                    json_part = json_match.group(0).strip()
                    answer = content[:json_match.start()].strip() # Everything BEFORE the JSON
                    
                    if not answer:
                        answer = f"[Answer missing, model only sent JSON: {json_part}]"

                    try:
                        # Sanitize and parse
                        start = json_part.find('{')
                        end = json_part.rfind('}')
                        if start != -1 and end != -1 and end > start:
                            json_text = json_part[start:end+1]
                            json_part_sanitized = re.sub(r",\s*([}\]])", r"\1", json_text.replace("\n", " "))
                            obj = json.loads(json_part_sanitized)
                            reflection = obj.get("reflection", "Parsed reflection from regex search.").strip()
                        else:
                            raise json.JSONDecodeError("No valid JSON object found", json_part, 0)
                    except json.JSONDecodeError as e:
                        self.log.warning(f"Regex JSON parse failed: {e} | content={json_part[:100]}")
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