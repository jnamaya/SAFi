"""
Mixin for generating contextual suggestions.
"""
from __future__ import annotations
from typing import List
import json
import re

class SuggestionsMixin:
    """Mixin for generating prompt suggestions."""

    async def _get_prompt_suggestions(self, user_prompt: str, will_rules: List[str]) -> List[str]:
        """
        Uses a fast model (Groq) to generate prompt suggestions after a violation.
        """
        suggestion_client = self.clients.get("groq")
        if not suggestion_client:
            self.log.warning("Groq client not configured. Cannot generate prompt suggestions.")
            return []

        prompt_config = self.prompts.get("suggestion_engine")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'suggestion_engine' prompt found. Cannot generate suggestions.")
            return []

        suggestion_model = self.config.BACKEND_MODEL

        try:
            system_prompt = prompt_config["system_prompt"]
            rules_string = "\n".join(f"- {r}" for r in will_rules)
            
            content = (
                f"**Here are the rules the user violated:**\n{rules_string}\n\n"
                f"**Here is the user's original (blocked) prompt:**\n{user_prompt}\n\n"
                "Please provide compliant suggestions."
            )

            self.log.info(f"Sending prompt to suggestion engine (model: {suggestion_model}):\nSystem: {system_prompt}\nUser Content: {content}")

            response = await suggestion_client.chat.completions.create(
                model=suggestion_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=0.7, # A bit of creativity
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            
            response_json = response.choices[0].message.content or "{}"
            
            self.log.info(f"Raw response from suggestion engine: {response_json}")

            start = response_json.find('{')
            end = response_json.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                json_text = response_json[start:end+1]
            else:
                self.log.warning(f"Suggestion engine returned non-JSON: {response_json}")
                return []
            
            obj = json.loads(json_text)
            
            suggestions = obj.get("suggestions", [])
            
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return suggestions
            else:
                self.log.warning(f"Suggestion engine returned invalid data: {response_json}")
                return []

        except Exception as e:
            self.log.error(f"Failed to get prompt suggestions: {e}")
            return []

    async def _get_follow_up_suggestions(self, user_prompt: str, ai_response: str) -> List[str]:
        """
        Uses a fast model (Groq) to generate follow-up suggestions for an approved answer.
        """
        suggestion_client = self.clients.get("groq")
        if not suggestion_client:
            self.log.warning("Groq client not configured. Cannot generate follow-up suggestions.")
            return []

        prompt_config = self.prompts.get("follow_up_suggester")
        if not prompt_config or "system_prompt" not in prompt_config:
            self.log.warning("No 'follow_up_suggester' prompt found. Cannot generate suggestions.")
            return []

        suggestion_model = self.config.BACKEND_MODEL

        try:
            system_prompt = prompt_config["system_prompt"]
            
            content = (
                f"**Here is the user's prompt:**\n{user_prompt}\n\n"
                f"**Here is the AI's answer:**\n{ai_response}\n\n"
                "Please provide relevant follow-up questions."
            )

            self.log.info(f"Sending prompt to follow-up suggester (model: {suggestion_model})")

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
            
            response_json = response.choices[0].message.content or "{}"
            self.log.info(f"Raw response from follow-up suggester: {response_json}")

            start = response_json.find('{')
            end = response_json.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                json_text = response_json[start:end+1]
            else:
                self.log.warning(f"Follow-up suggester returned non-JSON: {response_json}")
                return []
            
            obj = json.loads(json_text)
            suggestions = obj.get("suggestions", [])
            
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return suggestions
            else:
                self.log.warning(f"Follow-up suggester returned invalid data: {response_json}")
                return []

        except Exception as e:
            self.log.error(f"Failed to get follow-up suggestions: {e}")
            return []