"""
Mixin for background task management (summarization, profile extraction).
"""
from __future__ import annotations
from ...persistence import database as db

class BackgroundTasksMixin:
    """Mixin for background task management (summarization, profile extraction)."""

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        """Runs the summarization logic in a background thread using Sync client."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return
            
        summarizer_prompt_config = self.prompts.get("summarizer")
        if not summarizer_prompt_config: return

        try:
            system_prompt = summarizer_prompt_config["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")
            
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
            )
            db.update_conversation_summary(conversation_id, response.choices[0].message.content.strip())
        except Exception as e:
            self.log.warning(f"Summarization thread failed: {e}")

    def _run_profile_update_thread(self, user_id: str, current_profile_json: str, user_prompt: str, ai_response: str):
        """Runs the long-term user profile update logic in a background thread."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return
            
        profile_prompt_config = self.prompts.get("profile_extractor")
        if not profile_prompt_config: return

        try:
            system_prompt = profile_prompt_config["system_prompt"]
            content = (
                f"CURRENT_PROFILE_JSON:\n{current_profile_json}\n\n"
                f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
                "Return the new, updated JSON object."
            )
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            db.upsert_user_profile_memory(user_id, response.choices[0].message.content.strip())
            self.log.info(f"Successfully updated user profile for {user_id}")
        except Exception as e:
            self.log.warning(f"User profile update thread failed: {e}")