"""
Defines the IntellectEngine class.
"""
from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Tuple, Optional

# --- Import sibling (faculties) and parent (core) utilities ---
# Note: The original file imported `dict_sha256` from `...utils`,
# which maps to `safi_app/utils.py`. We keep that structure.
from ...utils import dict_sha256
from .utils import _norm_label as normalize_text


# --- Import services for type hinting and runtime ---
from typing import TYPE_CHECKING
from ..services.llm_provider import LLMProvider
from ..services.rag_service import RAGService


class IntellectEngine:
    """
    Core cognitive faculty for generating responses.
    
    This class is responsible for *assembling the prompt* by integrating
    various inputs (user prompt, memory, ethical feedback, and context)
    and then *delegating* the LLM call and RAG search to the appropriate services.
    It no longer makes direct API or RAG calls.
    """

    def __init__(
        self,
        llm_provider: "LLMProvider",
        rag_service: "RAGService",
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initializes the IntellectEngine.

        Args:
            llm_provider: An instance of the LLMProvider service.
            rag_service: An instance of the RAGService.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts and instructions.
        """
        self.llm_provider = llm_provider
        self.rag_service = rag_service
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.last_error: Optional[str] = None
        self.log = logging.getLogger(self.__class__.__name__)

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
        Generates a response by building a prompt and delegating to services.
        
        Args:
            user_prompt: The user's raw prompt (with date prepended).
            memory_summary: A summary of the conversation history.
            spirit_feedback: Coaching notes based on the spirit vector (mu).
            user_profile_json: A JSON string of the user's profile.
            user_name: The user's name, if known.
            plugin_context: A dictionary of context data from plugins.

        Returns:
            A tuple of (answer, reflection, retrieved_context_for_audit).
            Returns (None, None, retrieved_context_for_audit) on failure.
        """
        self.last_error = None

        # --- 1. RAG Context Retrieval ---
        # Determine the correct query for RAG (either the prompt or a plugin override)
        query_for_rag = user_prompt
        if plugin_context and plugin_context.get("rag_query_override"):
            query_for_rag = plugin_context["rag_query_override"]
            self.log.info(f"Plugin provided RAG override. New query: {query_for_rag}")

        # Delegate the RAG search to the RAGService
        retrieved_context_string = await self.rag_service.get_context(
            query=query_for_rag,
            format_string=self.profile.get("rag_format_string", "{text_chunk}")
        )
        
        # --- 2. Plugin Context Assembly ---
        plugin_context_string = ""
        if plugin_context:
            if plugin_context.get("preformatted_context_string"):
                plugin_context_string += plugin_context["preformatted_context_string"]
            
            if "plugin_error" in plugin_context:
                error_md = (
                    f"CONTEXT: I encountered an error trying to fetch data for the user.\n"
                    f"Error Message: {plugin_context['plugin_error']}\n"
                    f"Please inform the user about this error.\n\n"
                )
                plugin_context_string += error_md
        
        # --- 3. System Prompt Assembly ---
        
        # Combine all retrieved context
        full_context_injection = "\n\n".join(filter(None, [plugin_context_string, retrieved_context_string]))
        
        # Inject context into the persona's worldview template
        worldview = self.profile.get("worldview", "")
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=full_context_injection if full_context_injection else "[NO DOCUMENTS FOUND]"
            )

        # Inject conversation summary
        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far. Use it to inform your answer.\n"
            f"<summary>{memory_summary}</summary>" if memory_summary else ""
        )

        # Inject spirit (ethical alignment) feedback
        spirit_injection = ""
        if spirit_feedback:
            coaching_note_template = self.prompt_config.get("coaching_note", "")
            if coaching_note_template:
                spirit_injection = coaching_note_template.format(
                    spirit_feedback=spirit_feedback
                )

        # Inject user's name
        user_name_injection = ""
        if user_name:
            name_template = self.prompt_config.get("user_name_template", 
                "CONTEXT: You are speaking to a user named {user_name}. Use their name when appropriate (e.g., 'Hi {user_name}, ...').")
            if name_template:
                user_name_injection = name_template.format(user_name=user_name)

        # Inject user's profile
        user_profile_injection = ""
        if user_profile_json and user_profile_json != "{}":
            profile_template = self.prompt_config.get("user_profile_template", 
                "CONTEXT: Here is the user's profile. Use these facts to tailor your educational examples.\n<user_profile>{user_profile_json}</user_profile>")
            if profile_template:
                user_profile_injection = profile_template.format(
                    user_profile_json=user_profile_json
                )

        # Inject formatting and style instructions
        formatting_instructions = self.prompt_config.get("formatting_instructions", "")
        style = self.profile.get("style", "")
        if "{persona_style_rules}" in formatting_instructions:
            formatting_instructions = formatting_instructions.format(
                persona_style_rules=style
            )

        # Build final system prompt
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
        
        # This is passed to the Conscience for a complete audit
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")

        # --- 4. Delegate LLM Call ---
        try:
            # Delegate the actual LLM call and parsing to the provider
            answer, reflection, context_audit = await self.llm_provider.get_intellect_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_for_audit=final_context_for_audit
            )
            return answer, reflection, context_audit

        except Exception as e:
            self.last_error = f"IntellectEngine delegation failed: {e}"
            self.log.exception("IntellectEngine failed to get response from provider")
            return None, None, final_context_for_audit