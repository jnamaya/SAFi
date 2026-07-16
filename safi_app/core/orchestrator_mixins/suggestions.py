"""
Mixin for generating contextual suggestions.
"""
from __future__ import annotations
from typing import List
import json
import logging

class SuggestionsMixin:
    """Mixin for generating prompt suggestions."""

    async def _get_prompt_suggestions(self, user_prompt: str, will_rules: List[str]) -> List[str]:
        """
        [ASYNC] Called from the MAIN loop (Orchestrator.process_prompt).
        Uses the ASYNC Groq client.
        """
        # Use the Async client for the main loop
        suggestion_client = self.clients.get("groq")
        if not suggestion_client:
            self.log.warning("Groq client (Async) not configured. Cannot generate prompt suggestions.")
            return []

        # Direct Groq dispatch — honor the org provider allow-list (skip, never reroute).
        from ..services.provider_governance import assert_provider_allowed, ProviderNotAllowedError
        try:
            assert_provider_allowed("groq", context="suggestion_engine")
        except ProviderNotAllowedError as e:
            self.log.warning(f"[Governance] Prompt suggestions skipped: {e}")
            return []

        prompt_config = self.prompts.get("suggestion_engine")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'suggestion_engine' prompt found.")
            return []

        suggestion_model = getattr(self.config, "BACKEND_MODEL", "openai/gpt-oss-20b")

        try:
            system_prompt = prompt_config["system_prompt"]
            rules_string = "\n".join(f"- {r}" for r in will_rules)
            
            content = (
                f"**Here are the rules the user violated:**\n{rules_string}\n\n"
                f"**Here is the user's original (blocked) prompt:**\n{user_prompt}\n\n"
                "Please provide compliant suggestions."
            )

            response = await suggestion_client.chat.completions.create(
                model=suggestion_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=0.7,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            
            return self._parse_suggestions(response.choices[0].message.content)

        except Exception as e:
            self.log.error(f"Failed to get prompt suggestions: {e}")
            return []

    def _get_follow_up_suggestions(self, user_prompt: str, ai_response: str) -> List[str]:
        """
        [SYNC] Called from the BACKGROUND THREAD (BackgroundTasksMixin._run_audit_thread).
        Provider-routed via _backend_json_completion so it follows BACKEND_MODEL
        (Groq, Gemini, etc.) instead of being pinned to the Groq client.
        """
        prompt_config = self.prompts.get("follow_up_suggester")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'follow_up_suggester' prompt found.")
            return []

        system_prompt = prompt_config["system_prompt"]
        content = (
            f"**Here is the user's prompt:**\n{user_prompt}\n\n"
            f"**Here is the AI's answer:**\n{ai_response}\n\n"
            "Please provide relevant follow-up questions."
        )

        raw = self._backend_json_completion(system_prompt, content, temperature=0.7)
        return self._parse_suggestions(raw)

    def _parse_suggestions(self, response_json: str) -> List[str]:
        """Helper to parse the JSON response safely."""
        try:
            if not response_json: return []
            start = response_json.find('{')
            end = response_json.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_text = response_json[start:end+1]
                obj = json.loads(json_text)
                suggestions = obj.get("suggestions", [])
                if isinstance(suggestions, list):
                    return [str(s) for s in suggestions]
            return []
        except Exception:
            return []