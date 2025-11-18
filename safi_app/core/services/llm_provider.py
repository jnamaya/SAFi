"""
Defines the LLMProvider service.

This class is the ONLY part of the application that knows how to:
1.  Talk to different LLM providers (OpenAI, Anthropic, Gemini, Groq).
2.  Select the correct API client for a given model.
3.  Inject model-specific parameters (e.g., "reasoning_effort").
4.  Call the `parsing_utils` to sanitize and parse the raw LLM responses.

This isolates all provider-specific and parsing logic from the "faculties."
"""
from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Tuple, Optional

# External provider libraries
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import google.generativeai as genai

# Internal parsing utilities
from .parsing_utils import (
    parse_intellect_response,
    parse_will_response,
    parse_conscience_response
)

class LLMProvider:
    """
    A unified service to handle all LLM calls and response parsing.
    
    It is initialized by the Orchestrator with all necessary API clients
    and model configurations.
    """
    def __init__(
        self,
        clients: Dict[str, Any],
        gemini_models: Dict[str, Any],
        model_configs: Dict[str, str],
        extra_params: Optional[Dict[str, Any]] = None # Accepts model-specific params
    ):
        """
        Initializes the LLM provider service.

        Args:
            clients: A dict of initialized async clients (e.g., {"groq": AsyncOpenAI(...)}).
            gemini_models: A dict of initialized Gemini model instances.
            model_configs: A dict mapping faculties to model names
                           (e.g., {"intellect": "llama3-70b-8192"}).
            extra_params: A dict of model-specific parameters to inject,
                          (e.g., {"qwen/qwen3-32b": {"reasoning_effort": "none"}}).
        """
        self.clients = clients
        self.gemini_models = gemini_models
        self.model_configs = model_configs
        self.extra_params = extra_params or {} # Store the extra params
        self.log = logging.getLogger(self.__class__.__name__)
        self.log.info(f"LLMProvider initialized with clients: {list(self.clients.keys())}")

    def _get_provider_for_model(self, model_name: str) -> str:
        """
        Determines the provider (e.g., "openai", "groq") from the model name.
        """
        if model_name.startswith("gpt-"):
            return "openai"
        elif model_name.startswith("claude-"):
            return "anthropic"
        elif model_name.startswith("gemini-"):
            return "gemini"
        # Default fallback for OpenAI-compatible APIs
        return "groq"

    async def _make_llm_call(self, model: str, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float, json_mode: bool = False) -> str:
        """
        A single, private method to dispatch the API call to the correct provider.
        """
        content = "{}"
        
        # 1. Get the provider and client
        provider = self._get_provider_for_model(model)
        client = self.clients.get(provider)
        
        if client is None:
            # Special case for Gemini, which uses a different client structure
            if provider == "gemini":
                client = self.gemini_models.get(model)
                if client is None:
                     raise ValueError(f"No initialized Gemini model found for '{model}'.")
            elif provider not in self.clients:
                raise ValueError(f"No valid client found for provider '{provider}'. Check your API keys.")
            else:
                client = self.clients[provider]

        # 2. Get model-specific extra parameters
        extra_model_params = self.extra_params.get(model, {})
        if extra_model_params:
            self.log.info(f"Applying extra parameters for model {model}: {extra_model_params}")

        # 3. Make the API call based on the provider
        try:
            if provider == "groq" or provider == "openai":
                if not isinstance(client, AsyncOpenAI):
                    raise TypeError(f"Client for {provider} is not an AsyncOpenAI")
                
                params = {
                    "model": model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }

                # Note: We are not using json_mode=True, as the robust
                # parser is more reliable for models with reasoning logs.
                if json_mode:
                    params["response_format"] = {"type": "json_object"}
                
                if provider == "openai" and (model.startswith("gpt-4o") or model.startswith("gpt-5")):
                    params["max_completion_tokens"] = max_tokens
                else:
                    params["max_tokens"] = max_tokens

                # Pass standard params as keywords, and all non-standard
                # params (like "reasoning_effort") in the `extra_body` dict.
                resp = await client.chat.completions.create(
                    **params,
                    extra_body=extra_model_params
                )
                
                content = resp.choices[0].message.content or "{}"

            elif provider == "anthropic":
                if not isinstance(client, AsyncAnthropic):
                    raise TypeError(f"Client for {provider} is not an AsyncAnthropic")
                
                resp = await client.messages.create(
                    model=model,
                    system=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": user_prompt}],
                    **extra_model_params # Pass extra params directly
                )
                content = resp.content[0].text or "{}"

            elif provider == "gemini":
                # --- FIX: Revert to OLD Gemini syntax ---
                # This fixes the AttributeError: 'module' has no attribute 'Content'
                # by avoiding the new (incompatible) system_instruction parameter.
                
                client = self.gemini_models.get(model) # client is the gemini_model object
                if client is None:
                     raise ValueError(f"No initialized Gemini model found for '{model}'.")

                generation_config = genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
                
                if json_mode:
                    generation_config.response_mime_type = "application/json"

                # Use the old, compatible method of concatenating prompts
                full_prompt = system_prompt + "\n\n---START OF USER PROMPT---\n" + user_prompt
                
                resp = await client.generate_content_async(
                    full_prompt, 
                    generation_config=generation_config
                    # Note: No system_instruction parameter
                )
                content = resp.text or "{}"
                # --- END FIX ---
            
            else:
                raise ValueError(f"Unknown provider '{provider}'")

            return content

        except Exception as e:
            self.log.exception(f"LLM call failed for {provider} model {model}: {e}")
            # Return a string that will safely parse to an error state
            if json_mode:
                return '{"error": "Internal LLM call failed"}'
            else:
                # This format allows the robust parser to still find a reflection
                return f"[LLM call failed: {e}] ---REFLECTION--- {{\"reflection\": \"Internal LLM call failed.\"}}"

    # --- Public Methods for Faculties ---

    async def get_intellect_response(self, system_prompt: str, user_prompt: str, context_for_audit: str) -> Tuple[str, str, str]:
        """
        Gets a structured (answer, reflection) response for the IntellectEngine.
        
        This method uses the reliable text-delimiter-json format and
        does *not* force json_mode, as many open models struggle with it
        (especially when reasoning is enabled).
        """
        model = self.model_configs.get("intellect", "default-intellect-model")
        
        raw_content = await self._make_llm_call(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=4096,
            temperature=1.0,
            json_mode=False # Use text-delimiter-json format
        )
        
        answer, reflection = parse_intellect_response(raw_content, self.log)
        return answer, reflection, context_for_audit

    async def get_will_decision(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        """
        Gets a structured (decision, reason) response for the WillGate.
        
        This method does *not* use json_mode, to allow reasoning logs
        to be present. The parser will strip them.
        """
        model = self.model_configs.get("will", "default-will-model")
        
        raw_content = await self._make_llm_call(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1024,
            temperature=0.0,
            json_mode=False # Use robust text/JSON parsing
        )
        
        decision, reason = parse_will_response(raw_content, self.log)
        return decision, reason

    async def get_conscience_audit(self, system_prompt: str, user_prompt: str) -> List[Dict[str, Any]]:
        """
        Gets a structured [evaluations] list for the ConscienceAuditor.

        This method does *not* use json_mode, to allow reasoning logs
        to be present. The parser will strip them.
        """
        model = self.model_configs.get("conscience", "default-conscience-model")
        
        raw_content = await self._make_llm_call(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=4096,
            temperature=0.1,
            json_mode=False # Use robust text/JSON parsing
        )
        
        evaluations = parse_conscience_response(raw_content, self.log)
        return evaluations