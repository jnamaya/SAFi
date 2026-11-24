"""Will (Voluntas) — Rational Appetite and Deterministic Execution Gate.

In Thomas Aquinas's Summa Theologiae (I, q. 82; I-II, q. 8–17), the will is
the rational appetite ordered toward the good apprehended by reason, exercising
command (imperium) over whether a proposed act is actually executed.

In SAFi, this module enforces structural determinism: it evaluates proposed
outputs and tool calls against explicit policy rules, risk tiers, and hard
gates before any command or response is permitted to execute.
"""

from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Tuple, Optional
import logging
from .utils import _norm_label
from .. import pii_validators
from ... import security_policy


ALLOWED_GATE_REASONS: frozenset = frozenset(
    {"scope_violation", "grounding_violation", "ethical_violation"}
)


def _build_protected_rm_regex(protected_root_dirs: List[str]) -> Optional[re.Pattern]:
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
    if any(str(f).lower() in cmd_lower for f in (forbidden_shell_patterns or []) if f):
        return True
    rm_re = _build_protected_rm_regex(protected_root_dirs)
    return bool(rm_re and rm_re.search(cmd_lower))


class WillGate:

    def __init__(
        self,
        llm_provider: Any,
        *,
        values: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        alignment_threshold: float = 0.5,
    ):


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


                    self.log.warning(
                        "WillGate: require_disclaimer is set but "
                        "mandatory_disclaimer_substring is empty — skipping disclaimer check."
                    )
                elif expected not in draft_output:
                    return False, "missing_disclaimer"
            

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

                    self.log.warning(
                        "WillGate: sensitive identifier in draft | %s",
                        pii_validators.summarize(findings))
                    return False, "pii_detected"

            allowed = struct.get("allowed_markdown_syntaxes")
            if allowed:


                if "```" in draft_output and "```" not in allowed:
                    fences = re.findall(r'```[a-zA-Z]*', draft_output)
                    for fence in fences:
                        if fence not in allowed:
                            return False, "ethical_violation"
            else:
                for syntax in struct.get("banned_markdown_syntaxes", []):
                    if syntax in draft_output:
                        return False, "ethical_violation"


        return True, "pass"

    def evaluate_hard_gates(self, ledger: List[Dict[str, Any]]) -> Tuple[str, str]:


        gates = {}
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


        for norm, gate in gates.items():
            if norm not in ledger_by_norm:
                defined_name = gate.get("value") or gate.get("name")
                self.log.warning(f"WillGate: Hard gate '{defined_name}' missing from ledger — failing closed.")
                return ("violation", "hard_gate_unscored")

        for norm, gate in gates.items():
            entry = ledger_by_norm[norm]
            if float(entry.get("score", 0)) <= -1.0:


                defined_name = gate.get("value") or gate.get("name")
                reason = gate.get("gate_reason")
                if reason not in ALLOWED_GATE_REASONS:
                    reason = "hard_gate_violation"
                self.log.warning(f"WillGate: Hard gate failure on '{defined_name}' → {reason}.")
                return ("violation", reason)

        return ("approve", "hard_gates_passed")

    def evaluate_spirit_score(self, spirit_assessment: Dict[str, Any]) -> Tuple[str, str]:
        if spirit_assessment.get("critical_violation"):


            return ("violation", "ethical_violation")

        rules = self.profile.get("will_rules", {})
        struct = rules.get("structural_requirements", {}) if isinstance(rules, dict) else {}
        threshold = float(struct.get("alignment_score_threshold", self.alignment_threshold))

        if spirit_assessment.get("alignment_score", 1.0) < threshold:
            return ("violation", "low_alignment_score")
        return ("approve", "alignment_within_threshold")

    @staticmethod
    def classify_tool_risk(tool_name: str, parameters: dict, profile: Optional[dict] = None) -> Tuple[str, str]:
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


        if lowered in file_path_tools:
            target_path = str(params.get("path") or params.get("file_path") or params.get("target_path") or "").lower()
            if any(p in target_path for p in forbidden_paths):
                return "R4", "Privileged or forbidden system command/path"


        elif lowered in shell_tools:
            cmd = str(params.get("command") or params.get("cmd") or "").strip()
            cmd_lower = cmd.lower()

            if _has_forbidden_destructive_payload(cmd_lower, forbidden_shell_patterns, protected_root_dirs):
                return "R4", "Forbidden destructive shell payload"

            commands: list[list[str]] = []
            try:
                lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
                tokens = list(lexer)
                current: list[str] = []
                for t in tokens:
                    if t in ("|", "&&", "||", ";", "&", "\n"):
                        if current:
                            commands.append(current)
                            current = []
                    else:
                        current.append(t)
                if current:
                    commands.append(current)
            except Exception:
                for seg in re.split(r'(?:\s*(?:&&|\|\||[;\n])\s*)', cmd):
                    seg_clean = seg.strip()
                    if not seg_clean:
                        continue
                    try:
                        cmd_tokens = shlex.split(seg_clean)
                    except Exception:
                        cmd_tokens = seg_clean.split()
                    if cmd_tokens:
                        commands.append(cmd_tokens)

            for tokens in commands:
                if not tokens:
                    continue

                first_token = tokens[0].lower().split("/")[-1]

                if first_token in forbidden_executables:
                    return "R4", "Privileged or forbidden system command/path"


                if first_token == "git" and len(tokens) > 1 and tokens[1].lower() in ("commit", "tag", "notes"):
                    continue

                for tok in tokens[1:]:
                    tok_lower = tok.lower()
                    if any(p in tok_lower for p in forbidden_paths):
                        return "R4", "Privileged or forbidden system command/path"


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


        return "R1", "Standard operational tool call"

    async def evaluate_tool_intent(
        self,
        tool_name: str,
        parameters: dict,
        profile: dict,
    ) -> Tuple[str, str]:

        if not tool_name or not isinstance(tool_name, str):
            self.log.warning("WillGate: Blocked tool intent — tool_name must be a non-empty string.")
            return ("violation", "Tool name must be a non-empty string.")

        if not isinstance(parameters, dict):
            self.log.warning(f"WillGate: Blocked '{tool_name}' — parameters must be a dictionary.")
            return ("violation", f"Invalid parameters type for tool '{tool_name}': expected dictionary.")


        allowed_tools: Optional[List[str]] = profile.get("allowed_tools")
        if allowed_tools is not None and tool_name not in allowed_tools:
            self.log.warning(f"WillGate: Blocked '{tool_name}' — not in agent's allowed_tools.")
            return (
                "violation",
                f"Tool '{tool_name}' is not authorized for this agent profile.",
            )


        risk_class, risk_reason = self.classify_tool_risk(tool_name, parameters, profile)
        if risk_class == "R4":
            self.log.warning(f"WillGate: Blocked '{tool_name}' — R4 Privileged/Forbidden ({risk_reason}).")
            return (
                "violation",
                f"Tool intent blocked: privileged or forbidden operation ({risk_reason}).",
            )


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


        parameter_constraints: Dict[str, List[Any]] = (
            profile.get("tool_parameter_constraints", {}).get(tool_name, {})
        )
        for param_key, allowed_values in parameter_constraints.items():
            param_val = parameters.get(param_key)
            if param_val is None:


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
