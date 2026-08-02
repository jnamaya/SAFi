"""
Intellect — the faculty of apprehension and proposal.

In Thomistic psychology, the Intellect abstracts forms, understands context, and proposes
what is good. Here it is the primary cognitive engine (LLM): it parses RAG context,
conversation history, Spirit feedback, and the user prompt to draft responses and propose
tool invocations. The Intellect operates under a strict Air Gap — it is confined entirely
to generating typed intents (apprehension) and possesses absolute zero execution rights.
Tool calls are intercepted and returned as proposals; the Will decides whether they may act.
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import json
import logging
# Retriever is imported lazily inside __init__ — see the note there.
from ...persistence import database as db

# Ceiling on assembled retrieval context, in characters. This is the single choke
# point every agent and both retrieval paths pass through, which is why the bound
# lives here rather than in the retriever: semantic search is naturally capped at
# k=5, but a Bible citation returns a whole chapter, and "Psalm 119" measured 59
# chunks / ~20k chars / ~5k tokens — spent TWICE per turn, since the Conscience
# audits against the same context the Intellect drafted from.
#
# 8000 leaves John 3 and Genesis 1 (~6.3k) untouched and trims only real outliers.
_MAX_CONTEXT_CHARS = 8000


def _apply_context_budget(chunks: List[str]) -> str:
    """Join retrieved chunks up to the budget, and SAY SO when anything is dropped.

    Silence would be the dangerous option: an agent handed two-thirds of Psalm 119
    with no indication has every reason to present it as the whole psalm. The
    Textual Fidelity value exists to catch exactly that, so the truncation has to
    be visible to the model rather than inferred by it.

    Whole chunks are kept or dropped — never cut mid-chunk, which would end a
    passage mid-sentence and invite the model to complete it from memory.
    """
    kept: List[str] = []
    used = 0
    for chunk in chunks:
        cost = len(chunk) + 2  # the "\n\n" join
        if kept and used + cost > _MAX_CONTEXT_CHARS:
            break
        kept.append(chunk)
        used += cost

    dropped = len(chunks) - len(kept)
    if not dropped:
        return "\n\n".join(kept)

    return "\n\n".join(kept) + (
        f"\n\n[CONTEXT TRUNCATED: {dropped} of {len(chunks)} retrieved passages were "
        f"omitted to fit the context budget. What you have been given above is "
        f"INCOMPLETE. Do not present it as the full passage, and do not fill the gap "
        f"from memory — state plainly that only part of the passage was retrieved.]"
    )

class IntellectEngine:
    """
    Core cognitive faculty.
    Constructs context and prompts, then delegates execution to the LLMProvider.

    Air Gap of Intent: this class NEVER executes tools. It intercepts any tool
    call the LLM requests and returns it as a typed "tool_call" intent so the
    orchestrator can route it through the WillGate before acting.
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
            mcp_manager: Manager used only for listing available tools, never for execution.
        """
        self.llm_provider = llm_provider
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.log = logging.getLogger(self.__class__.__name__)
        self.last_error = None
        self.mcp_manager = mcp_manager

        # Initialize Retriever if configured.
        #
        # Imported HERE rather than at module scope: importing the retriever
        # pulls in faiss and the ONNX embedding runtime, and most agents have no
        # knowledge base at all — of the built-ins, only the Steward, Bible
        # Scholar and Contoso Admin do. A top-level import made every
        # deployment pay for a vector-search stack it may never call.
        self.retriever = None
        kb_name = self.profile.get("rag_knowledge_base")
        if kb_name:
            try:
                from ..services.retriever import Retriever
                self.retriever = Retriever(knowledge_base_name=kb_name)
            except ImportError as e:
                # A build without the RAG extras should degrade, not crash: the
                # agent answers without retrieval rather than failing to start.
                self.log.error(
                    f"RAG unavailable for '{kb_name}' ({e}) — answering without retrieval.")

    async def generate(
        self,
        *,
        user_prompt: Any,
        memory_summary: str,
        recent_turns: str = "",
        spirit_feedback: str = "",
        user_profile_json: str,
        agent_context_json: str = "{}",
        user_name: Optional[str] = None,
        user_id: Optional[str] = None,
        message_id: Optional[str] = None,
        plugin_context: Optional[Dict[str, Any]] = None,
        precomputed_retrieved_context: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        """
        Generates a typed intent proposal without executing any tools.

        Returns a 3-tuple of (intent, reflection, retrieved_context) where intent is:
          - {"type": "text", "content": <str>}
              A direct text response ready for Will evaluation.
          - {"type": "tool_call", "tool_name": <str>, "parameters": <dict>}
              A tool invocation proposal the orchestrator must gate before executing.
          - None
              A hard provider failure; caller should inspect self.last_error.
        """
        self.last_error = None

        # --- 0. Prepare Tools (for informing the LLM, not for execution) ---
        tools: List[Dict[str, Any]] = []
        if self.mcp_manager:
            tools = await self.mcp_manager.get_tools_for_agent(self.profile)

        # --- 1. RAG & Plugin Context Logic ---
        if precomputed_retrieved_context is not None:
            # Reuse context from the first Intellect call (retry / tool-agent follow-up).
            retrieved_context_string = precomputed_retrieved_context
        else:
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
                            if "text_chunk" in doc:
                                formatted_chunks.append(doc["text_chunk"])
                    retrieved_context_string = _apply_context_budget(formatted_chunks)
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

        recent_turns_injection = (
            f"RECENT CONVERSATION (last few turns verbatim):\n<recent_turns>{recent_turns}</recent_turns>"
            if recent_turns else ""
        )

        spirit_injection = ""
        if spirit_feedback:
            template = self.prompt_config.get("coaching_note", "")
            if template:
                spirit_injection = template.format(spirit_feedback=spirit_feedback)

        user_name_injection = ""
        if user_name:
            template = self.prompt_config.get("user_name_template", "CONTEXT: User name: {user_name}.")
            user_name_injection = template.format(user_name=user_name)

        user_profile_injection = ""
        if user_profile_json and user_profile_json != "{}":
            template = self.prompt_config.get("user_profile_template", "CONTEXT: User Profile:\n{user_profile_json}")
            user_profile_injection = template.format(user_profile_json=user_profile_json)

        agent_context_injection = ""
        if agent_context_json and agent_context_json not in ("{}", "null", ""):
            try:
                parsed = json.loads(agent_context_json)
                # Only inject if the context has at least one non-empty array
                if any(v for v in parsed.values() if isinstance(v, list) and v):
                    template = self.prompt_config.get(
                        "agent_context_template",
                        "WORK CONTEXT MEMORY (accumulated across all past conversations with this agent):\n<agent_context>{agent_context_json}</agent_context>\nUse this memory to maintain continuity — do not ask the user for information already captured here."
                    )
                    agent_context_injection = template.format(agent_context_json=agent_context_json)
            except Exception:
                pass

        formatting_instructions = self.prompt_config.get("formatting_instructions", "")
        if "{persona_style_rules}" in formatting_instructions:
            formatting_instructions = formatting_instructions.format(persona_style_rules=style)

        tools_injection = ""
        if tools:
            tools_injection = "AVAILABLE TOOLS (You MUST use these tools if the user needs them):\n" + "\n".join([f"- {t['name']}: {t['description']}" for t in tools])

        system_prompt = "\n\n".join(filter(None, [
            worldview,
            user_name_injection,
            user_profile_injection,
            agent_context_injection,
            memory_injection,
            recent_turns_injection,
            spirit_injection,
            tools_injection,
            formatting_instructions
        ]))

        formatting_reminder = self.prompt_config.get("formatting_reminder", "")
        if isinstance(user_prompt, str):
            current_user_prompt = user_prompt + formatting_reminder
        elif isinstance(user_prompt, list):
            current_user_prompt = user_prompt.copy()
            if formatting_reminder:
                current_user_prompt.append(formatting_reminder)
        else:
            current_user_prompt = user_prompt
        
        final_context_for_audit = full_context_injection if full_context_injection else (retrieved_context_string or "")

        # --- 3. Single LLM Call — No Tool Execution ---
        response_tuple = await self.llm_provider.run_intellect(
            system_prompt=system_prompt,
            user_prompt=current_user_prompt,
            context_for_audit=final_context_for_audit,
            tools=tools
        )

        if len(response_tuple) == 4:
            answer, r_t, context, raw_turn = response_tuple
        else:
            answer, r_t, context = response_tuple
            raw_turn = None

        if not answer:
            # Prefer the provider's actual cause (bad key, rate limit, model not
            # found, no egress) over the generic symptom — see
            # LLMProvider.explain_provider_error.
            cause = getattr(self.llm_provider, "last_intellect_error", None)
            self.last_error = (
                f"could not reach the language model — {cause}" if cause
                else "the language model returned an empty response. If this is a new "
                     "install, check that a valid LLM API key is set in .env."
            )
            return None, r_t, final_context_for_audit

        # --- 4. Detect and Intercept Tool Call Intent (never execute here) ---
        if isinstance(answer, str) and answer.strip().startswith('{') and '"tool_calls"' in answer:
            try:
                payload = json.loads(answer)
                tool_calls = payload.get("tool_calls")
                if tool_calls and isinstance(tool_calls, list):
                    first_tc = tool_calls[0]
                    tool_name: str = first_tc.get("name", "")
                    parameters: Dict[str, Any] = first_tc.get("arguments") or {}
                    self.log.info(f"Intellect: Tool call intercepted (not executed): {tool_name}")
                    
                    intent = {"type": "tool_call", "tool_name": tool_name, "parameters": parameters}
                    if raw_turn is not None:
                        intent["_gemini_raw_turn"] = raw_turn

                    return (
                        intent,
                        r_t,
                        context,
                    )
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        return {"type": "text", "content": answer}, r_t, context

    async def generate_forced_response(
        self,
        *,
        user_prompt: str,
        system_directive: str,
        conversation_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Forces a compliant, rephrased response based on a specific system directive.
        Uses run_intellect under the hood.
        """
        self.last_error = None
        
        # Build memory injection
        memory_summary = db.fetch_conversation_summary(conversation_id)
        memory_injection = (
            f"CONTEXT: Here is a summary of our conversation so far.\n<summary>{memory_summary}</summary>"
            if memory_summary else ""
        )
        
        # Build worldview and standard formatting rules but override with directive
        worldview = self.profile.get("worldview", "")
        style = self.profile.get("style", "")
        
        system_prompt = "\n\n".join(filter(None, [
            worldview,
            memory_injection,
            system_directive,
            style
        ]))
        
        # Do NOT pass the original user_prompt — it may contain injection content that
        # would cause the model to reproduce the attack even with a corrective directive.
        # The system_directive already provides full context for generating the redirect.
        response_tuple = await self.llm_provider.run_intellect(
            system_prompt=system_prompt,
            user_prompt="[Generate a compliant redirect response per the system directive above.]",
            context_for_audit="",
            tools=[]
        )
        
        if len(response_tuple) == 4:
            answer, r_t, context, raw_turn = response_tuple
        else:
            answer, r_t, context = response_tuple
            
        if not answer:
            # Prefer the provider's actual cause (bad key, rate limit, model not
            # found, no egress) over the generic symptom — see
            # LLMProvider.explain_provider_error.
            cause = getattr(self.llm_provider, "last_intellect_error", None)
            self.last_error = (
                f"could not reach the language model — {cause}" if cause
                else "the language model returned an empty response. If this is a new "
                     "install, check that a valid LLM API key is set in .env."
            )
            return {"type": "text", "content": "I am currently unable to process this request under governance rules."}, r_t
            
        return {"type": "text", "content": answer}, r_t
