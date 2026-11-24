from __future__ import annotations
import math
import re
import collections
import logging
from functools import lru_cache
from typing import List, Tuple, Optional, Dict, Any

from .. import pii_validators


@lru_cache(maxsize=None)
def _cue_pattern(cue: str) -> "re.Pattern[str]":
    return re.compile(r"\b" + re.escape(cue) + r"\b")


class PhaseZeroGate:

    def __init__(
        self,
        threat_rules: Optional[Dict[str, Any]] = None,
        validator_catalog: Optional[Dict[str, Any]] = None,
    ):
        self.log = logging.getLogger(self.__class__.__name__)
        self.threat_rules = threat_rules or {}
        self.validator_catalog = validator_catalog or {}

    def evaluate_prompt(
        self,
        user_prompt: str,
        agent_blacklist: Optional[List[str]] = None,
        pii_validators_enabled: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        prompt_lower = user_prompt.lower()

        for category, patterns in (self.threat_rules.get("INJECTION_SIGNATURES") or {}).items():
            for pattern in patterns:
                if pattern in prompt_lower:
                    self.log.warning(
                        f"PhaseZeroGate: Injection matched | "
                        f"category='{category}' pattern='{pattern}'"
                    )
                    return False, f"injection:{category}"

        for pattern in (agent_blacklist or []):
            if pattern.lower() in prompt_lower:
                self.log.warning(
                    f"PhaseZeroGate: Agent blacklist match | pattern='{pattern}'"
                )
                return False, "scope_violation"

        if pii_validators_enabled:
            findings = pii_validators.scan(
                user_prompt, pii_validators_enabled, self.validator_catalog
            )
            if findings:
                self.log.warning(
                    "PhaseZeroGate: sensitive identifier in prompt | %s",
                    pii_validators.summarize(findings))
                return False, "pii_detected"

        probed = self._probes_internals(prompt_lower)
        if probed:
            noun, cue = probed
            self.log.warning(
                f"PhaseZeroGate: Internals probe | noun='{noun}' cue='{cue}'"
            )
            return False, "injection:governance_probing"

        if self._has_embedded_instruction(user_prompt):
            self.log.warning(
                "PhaseZeroGate: Embedded instruction heuristic triggered — "
                "encoded payload adjacent to an instruction marker."
            )
            return False, "injection:embedded_instruction"

        return True, "pass"

    def evaluate_tool_result(self, tool_result: str, is_trusted_local: bool = False) -> Tuple[bool, str]:
        text = str(tool_result or "")
        text_lower = text.lower()

        for category, patterns in (self.threat_rules.get("INJECTION_SIGNATURES") or {}).items():
            for pattern in patterns:
                if pattern in text_lower:
                    self.log.warning(
                        f"PhaseZeroGate: Injection in tool result | "
                        f"category='{category}' pattern='{pattern}'"
                    )
                    return False, f"injection:{category}"

        if is_trusted_local:
            return True, "pass"

        if self._has_embedded_instruction(text):
            self.log.warning(
                "PhaseZeroGate: Embedded instruction heuristic triggered in tool result."
            )
            return False, "injection:embedded_instruction"

        return True, "pass"

    def evaluate_untrusted_content(self, content: str) -> Tuple[bool, str]:
        return self.evaluate_tool_result(content, is_trusted_local=False)

    def _probes_internals(self, prompt_lower: str):
        noun_hits = []
        for noun in self.threat_rules.get("SENSITIVE_INTERNALS", ()):
            start = 0
            while True:
                i = prompt_lower.find(noun, start)
                if i < 0:
                    break
                noun_hits.append((i, noun))
                start = i + 1
        if not noun_hits:
            return None

        for cue in self.threat_rules.get("INTERNALS_DISCLOSURE_CUES", ()):
            for m in _cue_pattern(cue).finditer(prompt_lower):
                ci = m.start()
                for ni, noun in noun_hits:
                    if abs(ni - ci) <= int(self.threat_rules.get("INTERNALS_PROXIMITY_CHARS", 0)):
                        return noun, cue
        return None

    def _compute_entropy(self, text: str) -> float:
        if not text:
            return 0.0
        freq = collections.Counter(text)
        n = len(text)
        return -sum((c / n) * math.log2(c / n) for c in freq.values())

    def _has_embedded_instruction(self, prompt: str) -> bool:
        if len(prompt) < int(self.threat_rules.get("MIN_LENGTH_FOR_ENTROPY_CHECK", 0)):
            return False

        prompt_lower = prompt.lower()
        markers = [m.start()
                   for marker in self.threat_rules.get("EMBEDDED_INSTRUCTION_MARKERS", ())
                   for m in re.finditer(re.escape(marker), prompt_lower)]
        if not markers:
            return False

        blob_min_run = int(self.threat_rules.get("BLOB_MIN_RUN", 0))
        if blob_min_run <= 0:
            return False
        for run in re.finditer(r"\S{%d,}" % blob_min_run, prompt):
            blob = run.group(0)
            sample_len = int(self.threat_rules.get("ENTROPY_SAMPLE_LENGTH", len(blob)))
            min_entropy = float(self.threat_rules.get("BLOB_MIN_ENTROPY", float("inf")))
            if self._compute_entropy(blob[:sample_len]) < min_entropy:
                continue
            proximity = int(self.threat_rules.get("BLOB_MARKER_PROXIMITY_CHARS", 0))
            lo = run.start() - proximity
            hi = run.end() + proximity
            if any(lo <= mi <= hi for mi in markers):
                return True
        return False
