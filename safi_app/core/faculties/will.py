"""Apply deterministic structural, authorization, and threshold checks."""
from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Tuple, Optional
import logging
from .utils import _norm_label
from .. import pii_validators
from ... import security_policy

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


def _build_protected_rm_regex(protected_root_dirs: List[str]) -> Optional[re.Pattern]:
    """Compile a regex matching recursive/forced `rm` against policy-protected root directories."""
    if not protected_root_dirs:
        return None
    allow_root = False
    named_dirs: List[str] = []
    for d in protected_root_dirs:
        raw = str(d or "").strip()
        stripped = raw.strip("/")
        if raw == "/" and not stripped:
            allow_root = True
        elif stripped:
            named_dirs.append(re.escape(stripped))
    branches: List[str] = []
    if allow_root:
        branches.append(r"/\*?(?=$|[\s;&|\"'\`\)])")
    if named_dirs:
        joined = "|".join(named_dirs)
        branches.append(rf"/(?:{joined})/?\*?(?=$|[\s;&|\"'\`\)])")
    if not branches:
        return None
    return re.compile(
        rf"\brm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(?:{'|'.join(branches)})",
        re.IGNORECASE,
    )


def _build_word_boundary_regex(commands: List[str]) -> Optional[re.Pattern]:
    """Compile a word-boundary regex from a policy list of shell command phrases."""
    escaped = [
        r"\s+".join(re.escape(part) for part in str(c).strip().split())
        for c in (commands or [])
        if str(c or "").strip()
    ]
    if not escaped:
        return None
    return re.compile(rf"\b({'|'.join(escaped)})\b", re.IGNORECASE)


def _has_forbidden_destructive_payload(
    cmd_lower: str,
    forbidden_shell_patterns: List[str],
    protected_root_dirs: List[str],
) -> bool:
    """Return True if a shell command matches a policy-forbidden shell pattern or protected directory wipe."""
    if any(str(f).lower() in cmd_lower for f in (forbidden_shell_patterns or []) if f):
        return True
    rm_re = _build_protected_rm_regex(protected_root_dirs)
    return bool(rm_re and rm_re.search(cmd_lower))


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

        rules = self.profile.get("will_rules", {})
        struct = rules.get("structural_requirements", {}) if isinstance(rules, dict) else {}
        threshold = float(struct.get("alignment_score_threshold", self.alignment_threshold))

        if spirit_assessment.get("alignment_score", 1.0) < threshold:
            return ("violation", "low_alignment_score")
        return ("approve", "alignment_within_threshold")

    @staticmethod
    def classify_tool_risk(tool_name: str, parameters: dict, profile: Optional[dict] = None) -> Tuple[str, str]:
        """
        Classify tool intent into deterministic risk classes driven by policy `will_rules`:
          R0: read-only query
          R1: reversible local workspace modification
          R2: destructive or high-impact local change
          R3: external side effect
          R4: privileged or forbidden operation
        """
        import shlex

        lowered = (tool_name or "").lower().strip()
        params = parameters if isinstance(parameters, dict) else {}

        will_rules = (profile or {}).get("will_rules") if isinstance(profile, dict) else None
        rules = security_policy.resolve_tool_risk_rules(will_rules)

        forbidden_paths = [str(p).lower() for p in (rules.get("forbidden_paths") or []) if p]
        forbidden_executables = {str(e).lower() for e in (rules.get("forbidden_executables") or []) if e}
        forbidden_shell_patterns = [str(p).lower() for p in (rules.get("forbidden_shell_patterns") or []) if p]
        protected_root_dirs = [str(d) for d in (rules.get("protected_root_dirs") or []) if d]

        file_path_tools = {str(t).lower() for t in (rules.get("file_path_tools") or []) if t}
        shell_tools = {str(t).lower() for t in (rules.get("shell_tools") or []) if t}

        r0_tools = {str(t).lower() for t in (rules.get("r0_tools") or []) if t}
        r0_substrings = [str(s).lower() for s in (rules.get("r0_substrings") or []) if s]
        r1_tools = {str(t).lower() for t in (rules.get("r1_tools") or []) if t}
        r2_tools = {str(t).lower() for t in (rules.get("r2_tools") or []) if t}
        r2_substrings = [str(s).lower() for s in (rules.get("r2_substrings") or []) if s]
        r3_tools = {str(t).lower() for t in (rules.get("r3_tools") or []) if t}
        r3_prefixes = [str(p).lower() for p in (rules.get("r3_prefixes") or []) if p]

        r2_shell_re = _build_word_boundary_regex(list(rules.get("r2_shell_commands") or []))
        r0_shell_re = _build_word_boundary_regex(list(rules.get("r0_shell_commands") or []))
        r1_shell_override_re = _build_word_boundary_regex(list(rules.get("r1_shell_override_commands") or []))

        # 1. File path tools
        if lowered in file_path_tools:
            target_path = str(params.get("path") or params.get("file_path") or params.get("target_path") or "").lower()
            if any(p in target_path for p in forbidden_paths):
                return "R4", "Privileged or forbidden system command/path"

        # 2. Shell execution tools
        elif lowered in shell_tools:
            cmd = str(params.get("command") or params.get("cmd") or "").strip()
            cmd_lower = cmd.lower()

            if _has_forbidden_destructive_payload(cmd_lower, forbidden_shell_patterns, protected_root_dirs):
                return "R4", "Forbidden destructive shell payload"

            segments = re.split(r'(?:\s*(?:&&|\|\||[;\n|])\s*)', cmd)
            for seg in segments:
                seg_clean = seg.strip()
                if not seg_clean:
                    continue

                try:
                    tokens = shlex.split(seg_clean)
                except Exception:
                    tokens = seg_clean.split()

                if not tokens:
                    continue

                first_token = tokens[0].lower().split("/")[-1]

                if first_token in forbidden_executables:
                    return "R4", "Privileged or forbidden system command/path"

                # If invoking git commit/tag/notes, string arguments (-m) are commit messages, not paths
                if first_token == "git" and len(tokens) > 1 and tokens[1].lower() in ("commit", "tag", "notes"):
                    continue

                for tok in tokens[1:]:
                    tok_lower = tok.lower()
                    if any(p in tok_lower for p in forbidden_paths):
                        return "R4", "Privileged or forbidden system command/path"

        # 3. Fallback check for any other tool parameters
        else:
            params_str = json.dumps(params, default=str).lower()
            if any(p in params_str for p in forbidden_paths):
                return "R4", "Privileged or forbidden system command/path"

        if lowered in r2_tools or any(action in lowered for action in r2_substrings):
            return "R2", "Destructive or high-impact local action"

        if any(ext in lowered for ext in r3_prefixes) or lowered in r3_tools:
            return "R3", "External action with external side effects"

        if lowered in r1_tools:
            return "R1", "Reversible local modification"

        if lowered in r0_tools or any(sub in lowered for sub in r0_substrings):
            return "R0", "Read-only query"

        # Shell command classification
        if lowered in shell_tools:
            cmd = str(params.get("command") or params.get("cmd") or "").strip().lower()
            if _has_forbidden_destructive_payload(cmd, forbidden_shell_patterns, protected_root_dirs):
                return "R4", "Forbidden destructive shell payload"
            if (r2_shell_re and r2_shell_re.search(cmd)) or ">" in cmd:
                return "R2", "Destructive shell command"
            if (r0_shell_re and r0_shell_re.search(cmd)) and not (
                r1_shell_override_re and r1_shell_override_re.search(cmd)
            ):
                return "R0", "Read-only shell command"
            return "R1", "Shell execution"

        # Unclassified default fallback
        return "R1", "Standard operational tool call"

    async def evaluate_tool_intent(
        self,
        tool_name: str,
        parameters: dict,
        profile: dict,
    ) -> Tuple[str, str]:
        """
        Gate a proposed tool call before any execution. No LLM calls.

        Order is a security property, not a style choice:
          1. Allowed tools check (T_allow = T_advertised ∩ T_charter ∩ T_policy)
          2. Risk classification (R0-R4) and policy risk gating
          3. Parameter constraints (default-deny)
        """
        # 0. Validate tool name and typed parameters
        if not tool_name or not isinstance(tool_name, str):
            self.log.warning("WillGate: Blocked tool intent — tool_name must be a non-empty string.")
            return ("violation", "Tool name must be a non-empty string.")

        if not isinstance(parameters, dict):
            self.log.warning(f"WillGate: Blocked '{tool_name}' — parameters must be a dictionary.")
            return ("violation", f"Invalid parameters type for tool '{tool_name}': expected dictionary.")

        # 1. Profile allow-list.
        allowed_tools: Optional[List[str]] = profile.get("allowed_tools")
        if allowed_tools is not None and tool_name not in allowed_tools:
            self.log.warning(f"WillGate: Blocked '{tool_name}' — not in agent's allowed_tools.")
            return (
                "violation",
                f"Tool '{tool_name}' is not authorized for this agent profile.",
            )

        # 2. Risk classification and enforcement
        risk_class, risk_reason = self.classify_tool_risk(tool_name, parameters, profile)
        if risk_class == "R4":
            self.log.warning(f"WillGate: Blocked '{tool_name}' — R4 Privileged/Forbidden ({risk_reason}).")
            return (
                "violation",
                f"Tool intent blocked: privileged or forbidden operation ({risk_reason}).",
            )

        # Check policy risk limits if configured
        max_allowed_risk = (
            profile.get("will_rules", {})
            .get("max_tool_risk_class", "R3")
            if isinstance(profile.get("will_rules"), dict)
            else "R3"
        )
        risk_hierarchy = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}
        if risk_hierarchy.get(risk_class, 1) > risk_hierarchy.get(max_allowed_risk, 3):
            self.log.warning(
                f"WillGate: Blocked '{tool_name}' — risk class {risk_class} exceeds limit {max_allowed_risk}."
            )
            return (
                "violation",
                f"Tool intent blocked: risk level {risk_class} exceeds policy limit {max_allowed_risk}.",
            )

        # 3. Parameter constraints apply uniformly to all authorized tools.
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

        self.log.info(f"WillGate: Deterministically approved authorized tool '{tool_name}' [{risk_class}].")
        return ("approve", "Passed structural, risk, and allow-list constraints.")
