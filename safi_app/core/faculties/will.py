"""
Defines the WillGate class.

An ethical gatekeeper that evaluates a draft response.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any, Tuple, Optional
import logging
from ...utils import normalize_text, dict_sha256

# Tools that only read data and carry no write/destructive side-effects.
# These receive an instant "approve" without an LLM call (CQRS fast path).
READ_ONLY_TOOLS: frozenset = frozenset({
    "get_stock_price",
    "calculator",
    "web_search",
    "find_places",
    "search_web",
    "web_news",
    "fetch_url",
    "read_file",
    "list_files",
    "get_weather",
    "lookup_definition",
})


class WillGate:
    """
    An ethical gatekeeper that evaluates a draft response against a set of values.
    """

    def __init__(
        self,
        llm_provider: Any,
        *,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        self.llm_provider = llm_provider
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.cache: Dict[str, Tuple[str, str]] = {}
        self.log = logging.getLogger(self.__class__.__name__)

    def _key(self, x_t: str, a_t: str) -> str:
        return dict_sha256({"x": normalize_text(x_t), "a": normalize_text(a_t), "V": self.values})

    async def evaluate(self, *, user_prompt: str, draft_answer: str, conversation_summary: Optional[str] = None) -> Tuple[str, str]:
        """
        Evaluates a draft answer. Returns (decision, reason).

        Args:
            user_prompt: The current user prompt
            draft_answer: The Intellect's proposed response
            conversation_summary: Optional summary of conversation history for trajectory analysis
        """
        key = self._key(user_prompt, draft_answer)
        if key in self.cache:
            return self.cache[key]

        rules = self.profile.get("will_rules") or []
        name = self.profile.get("name", "")
        if not rules:
            joined = ", ".join(v["value"] for v in self.values)
            rules = [f"Do not approve drafts that reduce alignment with: {joined}."]

        # Add trajectory-aware rule if conversation history is provided
        trajectory_rule = (
            "IMPORTANT: Analyze the CONVERSATION HISTORY for patterns of escalation or manipulation. "
            "If the conversation shows a trajectory toward harmful content (e.g., innocent setup → borderline questions → harmful request), "
            "decide 'violation' even if the current draft seems acceptable in isolation."
        )

        policy_parts = [
            self.prompt_config.get("header", "You are Will, the ethical gatekeeper."),
            f"Tradition: {name}" if name else "",
            "Rules:",
            *[f"- {r}" for r in rules],
            f"- {trajectory_rule}" if conversation_summary else "",
            # Removed Value Set per user request to restrict Will to Rules only.
            self.prompt_config.get("footer", "Return JSON: {decision, reason}."),
        ]

        system_prompt = "\n".join(filter(None, policy_parts))

        # Build user message with optional conversation context
        if conversation_summary:
            user_msg = (
                f"CONVERSATION HISTORY:\n{conversation_summary}\n\n"
                f"CURRENT PROMPT:\n{user_prompt}\n\n"
                f"DRAFT ANSWER:\n{draft_answer}"
            )
        else:
            user_msg = f"Prompt:\n{user_prompt}\n\nDraft Answer:\n{draft_answer}"

        # Delegate to LLMProvider
        decision, reason = await self.llm_provider.run_will(
            system_prompt=system_prompt,
            user_prompt=user_msg
        )

        self.cache[key] = (decision, reason)
        return decision, reason

    async def evaluate_tool_intent(
        self,
        tool_name: str,
        parameters: dict,
        profile: dict,
    ) -> Tuple[str, str]:
        """
        Evaluates a proposed tool call using CQRS pattern before any execution occurs.

        Decision flow:
          1. Read-only fast pass  — instant approve, no LLM call.
          2. Profile allow-list   — structural block if tool not permitted.
          3. Parameter constraints — structural block if values are out of range.
          4. LLM ethics check     — final gate for write/command tools that pass (1-3).

        Args:
            tool_name:  Name of the tool the Intellect wants to call.
            parameters: Arguments the Intellect supplied.
            profile:    Agent profile dict used for allow-list and constraint checks.

        Returns:
            (decision, reason) where decision is "approve" or "violation".
        """
        # --- Step 1: Profile allow-list check (Structural Security) ---
        allowed_tools: List[str] = profile.get("allowed_tools", [])
        if allowed_tools and tool_name not in allowed_tools:
            self.log.warning(f"WillGate: Blocked '{tool_name}' — not in agent's allowed_tools.")
            return (
                "violation",
                f"Tool '{tool_name}' is not authorized for this agent profile.",
            )

        # --- Step 2: CQRS fast pass for read-only tools ---
        if tool_name in READ_ONLY_TOOLS:
            self.log.info(f"WillGate: Fast-pass approved read-only tool '{tool_name}'.")
            return ("approve", "Read-only fast pass.")

        # --- Step 3: Parameter constraint validation ---
        parameter_constraints: Dict[str, List[Any]] = (
            profile.get("tool_parameter_constraints", {}).get(tool_name, {})
        )
        for param_key, allowed_values in parameter_constraints.items():
            param_val = parameters.get(param_key)
            if param_val is not None and param_val not in allowed_values:
                self.log.warning(
                    f"WillGate: Blocked '{tool_name}' — "
                    f"parameter '{param_key}={param_val}' not in permitted values."
                )
                return (
                    "violation",
                    f"Parameter '{param_key}={param_val}' is not permitted for tool '{tool_name}'.",
                )

        # --- Step 4: LLM ethics check for write/command tools ---
        rules = self.profile.get("will_rules") or []
        name = self.profile.get("name", "")

        policy_parts = [
            self.prompt_config.get("header", "You are Will, the ethical gatekeeper."),
            f"Tradition: {name}" if name else "",
            "Rules:",
            *[f"- {r}" for r in rules],
            "Evaluate whether executing this tool call is ethically safe and permitted by the rules above.",
            "IMPORTANT: You are evaluating a machine-to-machine tool call payload, NOT a final answer to the user.",
            "Do NOT block tool calls for missing conversational formatting (such as greetings, disclaimers, or specific tones) that apply to the final text response.",
            self.prompt_config.get("footer", "Return JSON: {decision, reason}."),
        ]
        system_prompt = "\n".join(filter(None, policy_parts))
        user_msg = (
            f"Tool Name: {tool_name}\n"
            f"Parameters: {json.dumps(parameters, ensure_ascii=False)}"
        )

        decision, reason = await self.llm_provider.run_will(
            system_prompt=system_prompt,
            user_prompt=user_msg,
        )
        return decision, reason
