"""
Phase Zero Gate — the pre-generation injection barrier.

Before the Intellect is ever invoked, this gate evaluates the raw user prompt against
known attack signatures, per-persona blacklists, and an entropy-based embedded-instruction
heuristic. It is entirely deterministic (zero LLM calls): if a threat is detected the
orchestrator short-circuits immediately to a governed redirect, ensuring the Intellect is
never exposed to adversarial content.
"""
from __future__ import annotations
import math
import collections
import logging
from typing import List, Tuple, Optional

from ..threat_intel import (
    INJECTION_SIGNATURES,
    ENTROPY_THRESHOLD,
    ENTROPY_SAMPLE_LENGTH,
    MIN_LENGTH_FOR_ENTROPY_CHECK,
    EMBEDDED_INSTRUCTION_MARKERS,
)


class PhaseZeroGate:
    """
    Pre-generation injection gate.

    Decision flow:
      1. Global signature scan  — known injection patterns from threat_intel.py
      2. Persona blacklist scan — per-persona blocked phrases (early_prompt_blacklist)
      3. Embedded instruction heuristic — high-entropy payload + instruction markers

    Returns (is_safe, reason). When is_safe is False the orchestrator
    short-circuits to trigger_persona_redirect without ever calling Intellect.
    """

    def __init__(self):
        self.log = logging.getLogger(self.__class__.__name__)

    def evaluate_prompt(
        self,
        user_prompt: str,
        persona_blacklist: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates the raw user prompt before Intellect runs.
        Returns (is_safe, reason).
        """
        prompt_lower = user_prompt.lower()

        # --- 1. Global signature scan ---
        for category, patterns in INJECTION_SIGNATURES.items():
            for pattern in patterns:
                if pattern in prompt_lower:
                    self.log.warning(
                        f"PhaseZeroGate: Injection matched | "
                        f"category='{category}' pattern='{pattern}'"
                    )
                    return False, f"injection:{category}"

        # --- 2. Persona blacklist scan ---
        for pattern in (persona_blacklist or []):
            if pattern.lower() in prompt_lower:
                self.log.warning(
                    f"PhaseZeroGate: Persona blacklist match | pattern='{pattern}'"
                )
                return False, "scope_violation"

        # --- 3. Embedded instruction heuristic ---
        if self._has_embedded_instruction(user_prompt):
            self.log.warning(
                "PhaseZeroGate: Embedded instruction heuristic triggered — "
                "high-entropy payload with instruction markers detected."
            )
            return False, "injection:embedded_instruction"

        return True, "pass"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_entropy(self, text: str) -> float:
        """Shannon entropy in bits per character."""
        if not text:
            return 0.0
        freq = collections.Counter(text)
        n = len(text)
        return -sum((c / n) * math.log2(c / n) for c in freq.values())

    def _has_embedded_instruction(self, prompt: str) -> bool:
        """
        Detects the indirect injection pattern: a high-entropy data blob
        followed by an instruction block.

        Classic example — the 'ancient text' attack:
          1. Random-looking character dump (high Shannon entropy)
          2. Embedded 'NEW TASK: STOP HERE' block inside the data
          3. Final request to reproduce the text including the embedded instruction
        """
        if len(prompt) < MIN_LENGTH_FOR_ENTROPY_CHECK:
            return False

        sample = prompt[:ENTROPY_SAMPLE_LENGTH]
        entropy = self._compute_entropy(sample)

        if entropy < ENTROPY_THRESHOLD:
            return False

        # High entropy confirmed — check if instruction markers appear later in the prompt
        remainder = prompt[ENTROPY_SAMPLE_LENGTH:].lower()
        return any(marker in remainder for marker in EMBEDDED_INSTRUCTION_MARKERS)
