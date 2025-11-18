"""
Defines the ConscienceAuditor class.
"""
from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Optional

# --- Import services for type hinting and runtime ---
from typing import TYPE_CHECKING
from ..services.llm_provider import LLMProvider


class ConscienceAuditor:
    """
    Audits the final, user-facing output for alignment with a set of values.
    
    This class is responsible for *assembling the rubrics* from the persona's
    value set and then *delegating* the LLM call to the LLMProvider
    to get a detailed JSON evaluation. This provides the data used for
    long-term ethical steering (Spirit).
    """

    def __init__(
        self,
        llm_provider: "LLMProvider",
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        prompt_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initializes the ConscienceAuditor.

        Args:
            llm_provider: An instance of the LLMProvider service.
            values: The list of value dictionaries for this persona.
            profile: The persona profile configuration.
            prompt_config: The configuration for system prompts and instructions.
        """
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
        Scores the final output against each configured value using detailed rubrics.
        
        Args:
            final_output: The final AI answer shown to the user.
            user_prompt: The user's original prompt.
            reflection: The AI's internal 'thought' from the Intellect step.
            retrieved_context: The raw RAG/plugin context that was retrieved.

        Returns:
            A list of evaluation dictionaries, e.g., 
            [{"value": "Honesty", "score": 1.0, "reason": "...", "confidence": 1.0}, ...]
        """
        
        # --- 1. Pre-check ---
        # Skip audit for short, non-substantive interactions
        if len(user_prompt) < 100 and len(final_output) < 100:
            self.log.info(f"Skipping conscience audit for short interaction. Prompt: '{user_prompt}'")
            return []

        # --- 2. System Prompt Assembly ---
        prompt_template = self.prompt_config.get("prompt_template")
        if not prompt_template:
            self.log.error("ConscienceAuditor 'prompt_template' not found in system_prompts.json")
            return []

        # Get the persona's worldview
        worldview = self.profile.get("worldview", "")

        # Inject the *same context* the Intellect saw into the Conscience's worldview
        if "{retrieved_context}" in worldview:
            worldview = worldview.format(
                retrieved_context=retrieved_context if retrieved_context else "[NO DOCUMENTS FOUND]"
            )

        worldview_injection = ""
        if worldview:
            worldview_template = self.prompt_config.get("worldview_template", "")
            if worldview_template:
                worldview_injection = worldview_template.format(worldview=worldview)

        # Assemble the JSON rubrics from the value set
        rubrics = []
        for v in self.values:
            if "rubric" in v:
                rubrics.append(
                    {
                        "value": v["value"],
                        "description": v["rubric"].get("description", ""),
                        "scoring_guide": v["rubric"].get("scoring_guide", []),
                    }
                )
        rubrics_str = json.dumps(rubrics, indent=2)

        # Build the final system prompt
        sys_prompt = prompt_template.format(
            worldview_injection=worldview_injection, rubrics_str=rubrics_str
        )

        # Build the user prompt, which contains all artifacts to be audited
        body = (
            f"USER PROMPT:\n{user_prompt}\n\n"
            f"AI's INTERNAL REFLECTION:\n{reflection}\n\n"
            f"DOCUMENTS RETRIEVED BY RAG:\n{retrieved_context if retrieved_context else 'None'}\n\n"
            f"AI's FINAL OUTPUT TO USER:\n{final_output}"
        )
        
        # --- 3. Delegate LLM Call ---
        try:
            # Delegate the LLM call and JSON parsing to the provider
            evaluations = await self.llm_provider.get_conscience_audit(
                system_prompt=sys_prompt,
                user_prompt=body
            )
            return evaluations
            
        except Exception as e:
            self.log.exception(f"Conscience delegation failed: {e}") 
            return []