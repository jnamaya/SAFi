"""
Defines the LLMProvider service.

This is the "Universal Client". It centralizes all API interactions.
It supports OpenAI, Anthropic, and Gemini natively, and generic OpenAI-compatible
providers (like DeepSeek, Groq, Mistral, Ollama) via configuration.
"""
from __future__ import annotations
import json
import logging
import asyncio
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
    A unified service to handle all LLM calls.
    Faculties call this service by 'route' (e.g., 'intellect'), not by model name.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: A dictionary defining providers and routes.
        """
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.clients = {}
        self._initialize_clients()

    def _initialize_clients(self):
        """Initializes API clients based on the provider config."""
        providers = self.config.get("providers", {})
        
        for name, details in providers.items():
            p_type = details.get("type")
            api_key = details.get("api_key")
            
            # Allow skipping provider if key is empty/None
            if not api_key:
                self.log.debug(f"Skipping provider '{name}': No API key provided.")
                continue

            try:
                if p_type == "openai":
                    self.clients[name] = AsyncOpenAI(
                        api_key=api_key,
                        base_url=details.get("base_url") # Handles Groq, DeepSeek, Mistral
                    )
                elif p_type == "anthropic":
                    self.clients[name] = AsyncAnthropic(api_key=api_key)
                elif p_type == "gemini":
                    genai.configure(api_key=api_key)
                    self.clients[name] = "gemini_configured" # Client created on demand
                else:
                    self.log.error(f"Unknown provider type '{p_type}' for '{name}'")
            except Exception as e:
                self.log.error(f"Failed to initialize provider '{name}': {e}")

    async def _chat_completion(self, route: str, system_prompt: str, user_prompt: str, temperature: float = 1.0, max_tokens: int = 4096) -> str:
        """
        Internal generic handler that routes the request to the correct provider.
        """
        route_config = self.config.get("routes", {}).get(route)
        if not route_config:
            raise ValueError(f"No route configuration found for '{route}'")

        provider_name = route_config["provider"]
        model_name = route_config["model"]
        
        # Get provider details
        provider_details = self.config.get("providers", {}).get(provider_name)
        if not provider_details:
             raise ValueError(f"Provider '{provider_name}' defined in route '{route}' not found in providers config.")

        provider_type = provider_details["type"]
        client = self.clients.get(provider_name)

        if not client:
            raise RuntimeError(f"Client for provider '{provider_name}' is not initialized. Check API Key.")

        # --- Dispatch based on Type ---
        
        # 1. OpenAI / DeepSeek / Groq / Mistral
        if provider_type == "openai":
            params = {
                "model": model_name,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            }
            # Handle o1/o3 reasoning models
            if "o1" in model_name or "o3" in model_name:
                # o1 models do not support 'system' role in current API versions
                params["messages"] = [{"role": "user", "content": f"System Instruction: {system_prompt}\n\nUser Query: {user_prompt}"}]
                # o1 models do not support temperature
                params.pop("temperature", None) 
                # o1 uses max_completion_tokens
                params.pop("max_tokens", None) 
                params["max_completion_tokens"] = max_tokens
            else:
                 params["max_tokens"] = max_tokens

            resp = await client.chat.completions.create(**params)
            return resp.choices[0].message.content or "{}"

        # 2. Anthropic (Claude)
        elif provider_type == "anthropic":
            resp = await client.messages.create(
                model=model_name,
                system=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": user_prompt}]
            )
            return resp.content[0].text or "{}"

        # 3. Google Gemini
        elif provider_type == "gemini":
            gemini_model = genai.GenerativeModel(model_name)
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            full_prompt = f"{system_prompt}\n\nUSER PROMPT:\n{user_prompt}"
            
            resp = await gemini_model.generate_content_async(
                full_prompt, 
                generation_config=generation_config
            )
            
            # --- GEMINI FIX: Safe Text Access ---
            try:
                return resp.text or "{}"
            except ValueError:
                # This catches the "Invalid operation: ... valid Part ... none were returned" error
                self.log.warning(f"Gemini returned empty response. Finish Reason: {resp.candidates[0].finish_reason if resp.candidates else 'Unknown'}")
                # Return empty JSON to trigger downstream error handling gracefully
                return "{}"

        else:
            raise ValueError(f"Unsupported provider type '{provider_type}'")


    # --- Public Faculty Interfaces ---

    async def run_intellect(self, system_prompt: str, user_prompt: str, context_for_audit: str) -> Tuple[str, str, str]:
        """Runs the configured Intellect model and parses the result."""
        try:
            raw_content = await self._chat_completion(
                route="intellect",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=1.0,
                max_tokens=4096
            )
            answer, reflection = parse_intellect_response(raw_content, self.log)
            return answer, reflection, context_for_audit
        except Exception as e:
            self.log.exception("Intellect execution failed")
            return None, None, context_for_audit

    async def run_will(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        """Runs the configured Will model and parses the result."""
        try:
            raw_content = await self._chat_completion(
                route="will",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=1024
            )
            decision, reason = parse_will_response(raw_content, self.log)
            return decision, reason
        except Exception as e:
            self.log.exception("Will execution failed")
            return "violation", f"System Error: {e}"

    async def run_conscience(self, system_prompt: str, user_prompt: str) -> List[Dict[str, Any]]:
        """Runs the configured Conscience model and parses the result."""
        try:
            raw_content = await self._chat_completion(
                route="conscience",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=4096
            )
            return parse_conscience_response(raw_content, self.log)
        except Exception as e:
            self.log.exception("Conscience execution failed")
            return []