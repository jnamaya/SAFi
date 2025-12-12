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

        prompt_config = self.prompts.get("suggestion_engine")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'suggestion_engine' prompt found.")
            return []

        suggestion_model = getattr(self.config, "BACKEND_MODEL", "llama-3.1-8b-instant")

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
        Uses the SYNC Groq client to avoid Event Loop crashes.
        """
        # Use the Sync client for background threads
        suggestion_client = getattr(self, "groq_client_sync", None)
        if not suggestion_client:
            self.log.warning("Groq client (Sync) not configured. Cannot generate follow-up suggestions.")
            return []

        prompt_config = self.prompts.get("follow_up_suggester")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'follow_up_suggester' prompt found.")
            return []

        suggestion_model = getattr(self.config, "BACKEND_MODEL", "llama-3.1-8b-instant")

        try:
            system_prompt = prompt_config["system_prompt"]
            
            content = (
                f"**Here is the user's prompt:**\n{user_prompt}\n\n"
                f"**Here is the AI's answer:**\n{ai_response}\n\n"
                "Please provide relevant follow-up questions."
            )

            # Sync call
            response = suggestion_client.chat.completions.create(
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
            self.log.error(f"Failed to get follow-up suggestions: {e}")
            return []

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