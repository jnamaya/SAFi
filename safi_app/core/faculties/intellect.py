"""
Defines the IntellectEngine class.

Core cognitive faculty for generating responses.
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import logging
from ..retriever import Retriever
from ...persistence import database as db

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
        mcp_manager: Any = None
    ):
        """
        Args:
            llm_provider: The unified LLM service.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts.
            mcp_manager: Manager for tool execution.
        """
        self.llm_provider = llm_provider
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.log = logging.getLogger(self.__class__.__name__)
        self.last_error = None
        self.mcp_manager = mcp_manager

        # Initialize Retriever if configured
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
        user_profile_json: str,
        user_name: Optional[str] = None,

        user_id: Optional[str] = None,
        message_id: Optional[str] = None,
        plugin_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generates a response based on the user prompt and contextual information.
        Handles Tool Execution Loop.
        """
        self.last_error = None
        
        # --- 0. Prepare Tools ---
        tools = []
        if self.mcp_manager:
            tools = await self.mcp_manager.get_tools_for_agent(self.profile)

        # --- 1. RAG & Plugin Context Logic ---
        query_for_rag = user_prompt
        # ... (Existing RAG Logic preserved) ...
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

        # --- 2. Prompt Construction (Base) ---
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
        
        # --- 3. Tool Loop Execution ---
        # We allow up to 15 turns of tool use to support deep research flows
        max_tool_turns = 15
        current_user_prompt = user_prompt + formatting_reminder
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")
        
        for turn in range(max_tool_turns):
            # Execute LLM Call
            # We explicitly pass tools. LLMProvider needs to handle parsing tool calls vs text.
            # We expect LLMProvider.run_intellect to return (answer, reflection, context) OR raise/return special tool signal.
            
            # Since we haven't modified run_intellect deeply, we'll rely on it returning the raw JSON string 
            # if we hacked parsing support, OR we need to modify run_intellect to be friendlier.
            
            # To be safe, let's assume `run_intellect` returns the raw content if it fails to parse XML tags
            # but sees valid JSON.
            
            response_tuple = await self.llm_provider.run_intellect(
                system_prompt=system_prompt,
                user_prompt=current_user_prompt,
                context_for_audit=final_context_for_audit,
                tools=tools
            )
            
            answer, reflection, context = response_tuple
            
            # Detect Tool Call (Hacky JSON check on 'answer' if parsing failed or if provider returned raw)
            # If `parse_intellect_response` failed, answer might be None or raw string.
            tool_calls = None
            if answer and answer.strip().startswith('{') and '"tool_calls"' in answer:
                 import json
                 try:
                     payload = json.loads(answer)
                     if "tool_calls" in payload:
                         tool_calls = payload["tool_calls"]
                 except: pass

            if not tool_calls:
                # No tools used, just return the text response
                return answer, reflection, context

            # Determine if we should execute tools
            if tool_calls:
                self.log.info(f"Intellect: Tool calls detected: {len(tool_calls)}")
                
                tool_results_text = ""
                for tc in tool_calls:
                     name = tc.get("name")
                     args = tc.get("arguments")
                     
                     # GOVERNANCE CHECK (Will Faculty could go here in v2)
                     
                     if self.mcp_manager:
                         # SECURITY CHECK: Ensure the agent is allowed to use this tool
                         allowed_tool_names = [t["name"] for t in tools]
                         if name not in allowed_tool_names:
                             tool_results_text += f"\n[TOOL ERROR: Tool '{name}' is not enabled for this agent.]\n"
                             self.log.warning(f"BLOCKED tool execution '{name}' for agent (not in allowed list {allowed_tool_names})")
                         else:
                             if message_id:
                                 db.update_message_reasoning(message_id, f"Executing tool: {name}")
                             
                             result = await self.mcp_manager.execute_tool(name, args, user_id=user_id)
                             tool_results_text += f"\n[TOOL EXECUTION: {name}({args}) => {result}]\n"
                     else:
                         tool_results_text += f"\n[TOOL EXECUTION FAILED: No Manager]\n"

                # Append result to prompt and loop
                current_user_prompt += tool_results_text
                # Log this internally
                self.log.info(f"Intellect: Appending tool results: {tool_results_text[:100]}...")
                continue
        
        
        # If we exit loop without returning, fallback
        self.log.error(f"Intellect: Hit max tool turns ({max_tool_turns}). Returning fallback.")
        return "I'm sorry, I was unable to complete the request within the reasoning limit. The task might be too complex or blocked by safety rules.", "System Loop Limit", final_context_for_audit