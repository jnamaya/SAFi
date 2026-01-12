"""
Defines the WillGate class.

An ethical gatekeeper that evaluates a draft response.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any, Tuple, Optional
import logging
from ...utils import normalize_text, dict_sha256

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