"""Apply deterministic structural, authorization, and threshold checks."""
from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Tuple, Optional
import logging
from .utils import _norm_label
from .. import pii_validators

# The violation reason a failing hard gate reports is DATA on the value itself
# (gate_reason, stamped into the compiled profile by synderesis), never derived
# from the value's name: the Will must not interpret names. The reason drives
# both the redirect directive lookup and the orchestrator's scope-vs-content
# classification, so each gate must name its real failure mode. Only genuine
# scope/injection gates may use "scope_violation"; a grounding breach
# (fabrication) is NOT a scope problem and must not be reported as one.
# Anything outside this set collapses to the generic reason, so a malformed
# policy cannot invent a routing path.
ALLOWED_GATE_REASONS: frozenset = frozenset(
    {"scope_violation", "grounding_violation", "ethical_violation"}
)


class WillGate:
    """
    The only component that may approve or block. Every decision here is made in
    Python, with no LLM call — see the note on llm_provider in __init__.
    """

    def __init__(
        self,
        llm_provider: Any,
        *,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        alignment_threshold: float = 0.5,
    ):
        # llm_provider is retained for interface compatibility with the other
        # faculties and is deliberately unused: every gate below is decided in
        # Python. There was once an LLM-judged Will; its "will_gate" prompt was
        # removed from system_prompts.json and the `prompt_config` parameter
        # that fed it was removed once it was confirmed nothing read it. Do not
        # reintroduce an LLM call here without revisiting that decision — the
        # gate's value is that it is not a judgement call.
        self.llm_provider = llm_provider
        self.values = values
        self.profile = profile or {}
        self.alignment_threshold = alignment_threshold
        self.log = logging.getLogger(self.__class__.__name__)

    def evaluate_draft_structure(self, draft_output: str) -> Tuple[bool, str]:
        rules = self.profile.get("will_rules", {})
        
        if isinstance(rules, dict):
            struct = rules.get("structural_requirements", {})
            
            # Disclaimer presence
            if struct.get("require_disclaimer"):
                expected = (struct.get("mandatory_disclaimer_substring") or "").strip()
                if not expected:
                    # Config error: the rule is on but no substring was set. There
                    # is nothing checkable to enforce — blocking every draft (or
                    # crashing on a KeyError, the old behavior) helps nobody.
                    self.log.warning(
                        "WillGate: require_disclaimer is set but "
                        "mandatory_disclaimer_substring is empty — skipping disclaimer check."
                    )
                elif expected not in draft_output:
                    return False, "missing_disclaimer"
            
            # Sensitive identifiers in the OUTPUT (GOVERNANCE_BACKLOG 83).
            # Phase Zero covers the inbound half, but it is prompt-only and
            # never sees a draft. This is the half that matters once agents
            # hold tools: an agent can read a document containing account
            # numbers and repeat them into a chat log that becomes a governance
            # record. Deterministic, same as every other check here: a regex
            # plus a checksum, no model.
            #
            # Fails CLOSED on a configured-but-unreadable value, matching the
            # disclaimer rule above: a control that silently does nothing is
            # worse than one that refuses.
            enabled = struct.get("pii_validators")
            if enabled:
                try:
                    findings = pii_validators.scan(
                        draft_output, enabled, self.profile.get("pii_validator_catalog")
                    )
                except Exception as e:
                    self.log.error(
                        "WillGate: PII scan failed, refusing the draft: %s", e)
                    return False, "pii_detected"
                if findings:
                    # Types and counts in the log, never the matched value.
                    self.log.warning(
                        "WillGate: sensitive identifier in draft | %s",
                        pii_validators.summarize(findings))
                    return False, "pii_detected"

            # Code block policy: zero-trust whitelist OR legacy blacklist
            allowed = struct.get("allowed_markdown_syntaxes")
            if allowed:
                # Zero-trust whitelist: block any code fence not explicitly permitted.
                # Only engages when the whitelist is non-empty. An empty/missing list
                # means "no restriction configured" (the wizard default) — NOT "block
                # everything" — and falls through to the legacy blacklist branch below.
                # "```" in the allowed list = permit all code blocks.
                if "```" in draft_output and "```" not in allowed:
                    fences = re.findall(r'```[a-zA-Z]*', draft_output)
                    for fence in fences:
                        if fence not in allowed:
                            return False, "ethical_violation"
            else:
                for syntax in struct.get("banned_markdown_syntaxes", []):
                    if syntax in draft_output:
                        return False, "ethical_violation"
        # Legacy prose rules are normalized to structured requirements by the
        # application adapter. The enforcement core does not infer requirements
        # from natural-language rules or profile style.
                        
        return True, "pass"

    def evaluate_hard_gates(self, ledger: List[Dict[str, Any]]) -> Tuple[str, str]:
        """
        Checks hard-gate values in the Conscience ledger before Spirit aggregation.
        Any hard-gate value scoring -1 triggers an immediate violation, bypassing
        the Spirit aggregate entirely. Hard-gate values have weight=0.0 and are
        excluded from the Spirit EMA.
        """
        # Match by normalized label — the same comparison Spirit and the
        # orchestrator's coverage check use — so a case/Unicode variant of a
        # gate name from the auditor doesn't fail closed here while passing
        # everywhere else.
        gates = {}  # normalized label -> the gate's value dict (carries gate_reason)
        for v in self.values:
            if v.get("hard_gate"):
                name = v.get("value") or v.get("name")
                gates[_norm_label(name)] = v
        if not gates:
            return ("approve", "no_hard_gates_defined")

        ledger_by_norm: Dict[str, Dict[str, Any]] = {}
        for e in ledger:
            if e.get("value") is not None:
                ledger_by_norm.setdefault(_norm_label(e.get("value")), e)

        # Fail-closed: a hard gate that the audit did not score cannot be
        # assumed compliant. A missing entry (Conscience omitted it, returned a
        # garbled/empty ledger, etc.) is treated as a violation, not a pass.
        for norm, gate in gates.items():
            if norm not in ledger_by_norm:
                defined_name = gate.get("value") or gate.get("name")
                self.log.warning(f"WillGate: Hard gate '{defined_name}' missing from ledger — failing closed.")
                return ("violation", "hard_gate_unscored")

        for norm, gate in gates.items():
            entry = ledger_by_norm[norm]
            if float(entry.get("score", 0)) <= -1.0:
                # Report the gate's real failure mode, read from the compiled
                # profile. A gate without a valid gate_reason defaults to a
                # generic content violation rather than masquerading as a
                # scope breach.
                defined_name = gate.get("value") or gate.get("name")
                reason = gate.get("gate_reason")
                if reason not in ALLOWED_GATE_REASONS:
                    reason = "hard_gate_violation"
                self.log.warning(f"WillGate: Hard gate failure on '{defined_name}' → {reason}.")
                return ("violation", reason)

        return ("approve", "hard_gates_passed")

    def evaluate_spirit_score(self, spirit_assessment: Dict[str, Any]) -> Tuple[str, str]:
        """
        Evaluates Spirit's aggregated alignment assessment and returns a gate decision.
        Will owns all block/approve decisions; Spirit only aggregates.

        Threshold priority (highest to lowest):
          1. Agent-level: will_rules.structural_requirements.alignment_score_threshold
          2. Instance-level: alignment_threshold (set from Config.SPIRIT_ALIGNMENT_THRESHOLD)
        """
        if spirit_assessment.get("critical_violation"):
            # Use ethical_violation so the agent's own rephrase directive fires
            # (every agent defines this key). Phase 4.5 hard-gate already handles
            # true scope breaches — anything reaching here is a content quality issue.
            return ("violation", "ethical_violation")

        # Resolve threshold: agent-specific override → instance default
        rules = self.profile.get("will_rules", {})
        struct = rules.get("structural_requirements", {}) if isinstance(rules, dict) else {}
        threshold = float(struct.get("alignment_score_threshold", self.alignment_threshold))

        if spirit_assessment.get("alignment_score", 1.0) < threshold:
            return ("violation", "low_alignment_score")
        return ("approve", "alignment_within_threshold")

    async def evaluate_tool_intent(
        self,
        tool_name: str,
        parameters: dict,
        profile: dict,
    ) -> Tuple[str, str]:
        """
        Gate a proposed tool call before any execution. No LLM calls.

        Order is a security property, not a style choice: the allow-list runs
        BEFORE the read-only fast pass, so a policy that narrows web_search can
        still block it, and parameter constraints run last because they are
        per-tool and only meaningful for tools that get that far.
        """
        # 1. Profile allow-list.
        # Compiled profiles always carry allowed_tools:
        # the advertised tool list, optionally narrowed by the policy's
        # will_rules.allowed_tools. An empty list is deny-all — an agent that
        # was offered no tools has no legitimate tool intents (a name arriving
        # here anyway means hallucination or injection). Only a profile with no
        # key at all (not built by the compiler) skips the check.
        allowed_tools: Optional[List[str]] = profile.get("allowed_tools")
        if allowed_tools is not None and tool_name not in allowed_tools:
            self.log.warning(f"WillGate: Blocked '{tool_name}' — not in agent's allowed_tools.")
            return (
                "violation",
                f"Tool '{tool_name}' is not authorized for this agent profile.",
            )

        # 2. Parameter constraints apply uniformly to all authorized tools.
        parameter_constraints: Dict[str, List[Any]] = (
            profile.get("tool_parameter_constraints", {}).get(tool_name, {})
        )
        for param_key, allowed_values in parameter_constraints.items():
            param_val = parameters.get(param_key)
            if param_val is None:
                # Default-deny: omitting a constrained parameter must not bypass
                # the constraint — the tool's server-side default is unvetted.
                self.log.warning(
                    f"WillGate: Blocked '{tool_name}' — "
                    f"constrained parameter '{param_key}' was not provided."
                )
                return (
                    "violation",
                    f"Parameter '{param_key}' is constrained for tool '{tool_name}' and must be provided explicitly.",
                )
            if param_val not in allowed_values:
                self.log.warning(
                    f"WillGate: Blocked '{tool_name}' — "
                    f"parameter '{param_key}={param_val}' not in permitted values."
                )
                return (
                    "violation",
                    f"Parameter '{param_key}={param_val}' is not permitted for tool '{tool_name}'.",
                )

        self.log.info(f"WillGate: Deterministically approved authorized tool '{tool_name}'.")
        return ("approve", "Passed structural and allow-list constraints.")
