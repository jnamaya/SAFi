"""
Defines the IntellectEngine class.

Core cognitive faculty for generating responses.
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import logging
from ..retriever import Retriever

class IntellectEngine:
    """
    Core cognitive faculty.
    Constructs context and prompts, then delegates execution to the LLMProvider.
    """

    def __init__(
        self,
        llm_provider: Any,
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            llm_provider: The unified LLM service.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts.
        """
        self.llm_provider = llm_provider
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.log = logging.getLogger(self.__class__.__name__)
        self.last_error = None

        # Initialize Retriever if configured
        self.retriever = None
        kb_name = self.profile.get("rag_knowledge_base")
        if kb_name:
            self.retriever = Retriever(knowledge_base_name=kb_name)
            # Inject retriever into provider if needed (rare, but keeping pattern if exists)
            # Note: In this refactor, LLMProvider is pure LLM, so Retriever stays here.

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

        # --- 1. RAG & Plugin Context Logic ---
        query_for_rag = user_prompt
        if plugin_context and plugin_context.get("rag_query_override"):
            query_for_rag = plugin_context["rag_query_override"]

        retrieved_context_string = ""
        if self.retriever:
            retrieved_docs = self.retriever.search(query_for_rag)
            if retrieved_docs:
                format_string = self.profile.get("rag_format_string", "{text_chunk}")
                formatted_chunks = []
                for doc in retrieved_docs:
                    try:
                        formatted_chunks.append(format_string.format(**doc))
                    except KeyError:
                        if "text_chunk" in doc: formatted_chunks.append(doc["text_chunk"])
                retrieved_context_string = "\n\n".join(formatted_chunks)
            else:
                retrieved_context_string = "[NO DOCUMENTS FOUND]"

        plugin_context_string = ""
        if plugin_context:
            if plugin_context.get("preformatted_context_string"):
                plugin_context_string += plugin_context["preformatted_context_string"]
            if "plugin_error" in plugin_context:
                plugin_context_string += f"CONTEXT ERROR: {plugin_context['plugin_error']}\n\n"

        # --- 2. Prompt Construction ---
        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")
        
        full_context_injection = "\n\n".join(filter(None, [plugin_context_string, retrieved_context_string]))
        
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=full_context_injection if full_context_injection else "[NO DOCUMENTS FOUND]"
            )

        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far.\n<summary>{memory_summary}</summary>" 
            if memory_summary else ""
        )

        spirit_injection = ""
        if spirit_feedback:
            template = self.prompt_config.get("coaching_note", "")
            if template: spirit_injection = template.format(spirit_feedback=spirit_feedback)

        user_name_injection = ""
        if user_name:
            template = self.prompt_config.get("user_name_template", "CONTEXT: User name: {user_name}.")
            user_name_injection = template.format(user_name=user_name)

        user_profile_injection = ""
        if user_profile_json and user_profile_json != "{}":
            template = self.prompt_config.get("user_profile_template", "CONTEXT: User Profile:\n{user_profile_json}")
            user_profile_injection = template.format(user_profile_json=user_profile_json)

        formatting_instructions = self.prompt_config.get("formatting_instructions", "")
        if "{persona_style_rules}" in formatting_instructions:
            formatting_instructions = formatting_instructions.format(persona_style_rules=style)

        system_prompt = "\n\n".join(filter(None, [
            worldview, 
            user_name_injection,
            user_profile_injection,
            memory_injection, 
            spirit_injection, 
            formatting_instructions
        ]))
        
        formatting_reminder = self.prompt_config.get("formatting_reminder", "")
        final_user_message = user_prompt + formatting_reminder
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")

        # --- 3. Execution (Delegated to LLMProvider) ---
        # The provider handles clients, models, retries, and parsing.
        return await self.llm_provider.run_intellect(
            system_prompt=system_prompt,
            user_prompt=final_user_message,
            context_for_audit=final_context_for_audit
        )