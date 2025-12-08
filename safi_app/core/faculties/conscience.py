"""
Defines the ConscienceAuditor class.

Audits the final output for ethical alignment.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any, Optional
import logging

class ConscienceAuditor:
    """
    Audits the final, user-facing output for alignment with a set of values.
    """

    def __init__(
        self,
        llm_provider: Any,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        self.llm_provider = llm_provider
        self.values = values
        self.profile = profile or {}
        self.prompt_config = prompt_config or {}
        self.log = logging.getLogger(self.__class__.__name__)

    async def evaluate(
        self,
        *,
        final_output: str,
        user_prompt: str,
        reflection: str,
        retrieved_context: str,
    ) -> List[Dict[str, Any]]:
        """
        Scores the final output against each configured value.
        """
        if len(user_prompt) < 100 and len(final_output) < 100:
            return []

        prompt_template = self.prompt_config.get("prompt_template")
        if not prompt_template:
            return []

        worldview = self.profile.get("worldview", "")
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=retrieved_context if retrieved_context else "[NO DOCUMENTS FOUND]"
            )

        worldview_injection = ""
        if worldview:
            template = self.prompt_config.get("worldview_template", "")
            if template: worldview_injection = template.format(worldview=worldview)

        rubrics = []
        rubrics = []
        for v in self.values:
            if "rubric" in v:
                rub = v["rubric"]
                # Handle both Dict (standard) and List (legacy/custom) formats
                if isinstance(rub, dict):
                     desc = rub.get("description", "")
                     guide = rub.get("scoring_guide", [])
                elif isinstance(rub, list):
                     # If it's a list, it's the scoring guide itself.
                     # Expect description on the parent value object.
                     desc = v.get("description", "")
                     guide = rub
                else:
                     desc = ""
                     guide = []

                rubrics.append({
                    "value": v["value"],
                    "description": desc,
                    "scoring_guide": guide,
                })
        rubrics_str = json.dumps(rubrics, indent=2)

        sys_prompt = prompt_template.format(
            worldview_injection=worldview_injection, 
            rubrics_str=rubrics_str
        )

        body = (
            f"USER PROMPT:\n{user_prompt}\n\n"
            f"AI REFLECTION:\n{reflection}\n\n"
            f"CONTEXT:\n{retrieved_context if retrieved_context else 'None'}\n\n"
            f"FINAL OUTPUT:\n{final_output}"
        )

        # Delegate to LLMProvider
        return await self.llm_provider.run_conscience(
            system_prompt=sys_prompt,
            user_prompt=body
        )