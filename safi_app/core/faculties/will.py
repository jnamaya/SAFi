"""
Will — the executive faculty and absolute gatekeeper.

In Thomistic psychology, the Will is the faculty that chooses and commands action based on
the Intellect's apprehension. Here it is the sole decision-making authority — but it
operates under three structurally necessary philosophical limitations:

  No Moral Apprehension (The Will is Blind): Following nihil volitum nisi praecognitum
  ("nothing is willed unless first known"), the Will has no LLM of its own. It cannot read
  semantic meaning or evaluate morality. It relies entirely on the mathematical judgments
  handed down by the Conscience and Spirit to "see" whether an action is aligned.

  No Body: The system has no physical form, drives, or passions — the Will operates in a
  sterile computational vacuum, free from the sensitive appetites that constantly pull
  against human volition.

  Deontological rather than Teleological (The Kantian Engine): A human Will has a
  teleological hunger for flourishing. An AI cannot possess genuine desire. The WillGate
  therefore acts as a strictly Kantian construct — enforcing structural invariants
  (disclaimers, parameter constraints, allowed-tool lists, hard-gate thresholds) purely
  out of duty to the law, without context, nuance, or orientation toward the Good.
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
    Refactored to be purely deterministic in Python with zero LLM calls.
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

    def evaluate_draft_structure(self, draft_output: str) -> Tuple[bool, str]:
        """Validates structural invariants of the generated draft without an LLM."""
        rules = self.profile.get("will_rules", {})
        
        if isinstance(rules, dict):
            struct = rules.get("structural_requirements", {})
            
            # 1. Enforce Disclaimer Presence
            if struct.get("require_disclaimer"):
                if struct["mandatory_disclaimer_substring"] not in draft_output:
                    return False, "missing_disclaimer"
            
            # 2. Enforce Execution Syntax Sanity
            for syntax in struct.get("banned_markdown_syntaxes", []):
                if syntax in draft_output:
                    return False, "ethical_violation"
        else:
            # Legacy list fallback
            draft_lower = draft_output.lower()
            has_disclaimer_rule = any("disclaimer" in str(r).lower() for r in rules)
            if has_disclaimer_rule:
                style_text = self.profile.get("style", "")
                if "Disclaimer:" in style_text:
                    if "Disclaimer: I am an AI guide, not a doctor" in style_text:
                        expected = "Disclaimer: I am an AI guide, not a doctor"
                    elif "Disclaimer: This information is for educational" in style_text:
                        expected = "Disclaimer: This information is for educational"
                    else:
                        expected = "Disclaimer:"
                    
                    if expected not in draft_output:
                        return False, "missing_disclaimer"
            
            has_disclosure_rule = any("disclose" in str(r).lower() or "note" in str(r).lower() for r in rules)
            if has_disclosure_rule:
                if "AI assistance" in self.profile.get("style", ""):
                    expected_note = "*Note: If you share this information externally, please disclose that it was generated with AI assistance.*"
                    if expected_note not in draft_output:
                        return False, "missing_disclaimer"
                        
        return True, "pass"

    async def evaluate(self, *, user_prompt: str, draft_answer: str, conversation_summary: Optional[str] = None) -> Tuple[str, str]:
        """
        Evaluates a draft answer. Returns (decision, reason).
        Purely deterministic Python implementation.
        """
        key = self._key(user_prompt, draft_answer)
        if key in self.cache:
            return self.cache[key]

        is_valid_struct, struct_reason = self.evaluate_draft_structure(draft_answer)
        if not is_valid_struct:
            res = ("violation", struct_reason)
            self.cache[key] = res
            return res

        res = ("approve", "pass")
        self.cache[key] = res
        return res

    def evaluate_hard_gates(self, ledger: List[Dict[str, Any]]) -> Tuple[str, str]:
        """
        Checks hard-gate values in the Conscience ledger before Spirit aggregation.
        Any hard-gate value scoring -1 triggers an immediate violation, bypassing
        the Spirit aggregate entirely. Hard-gate values have weight=0.0 and are
        excluded from the Spirit EMA.
        """
        hard_gate_names = {
            v.get("value") or v.get("name")
            for v in self.values
            if v.get("hard_gate")
        }
        if not hard_gate_names:
            return ("approve", "no_hard_gates_defined")

        for entry in ledger:
            if entry.get("value") in hard_gate_names and float(entry.get("score", 0)) <= -1.0:
                value_name = entry.get("value", "unknown")
                self.log.warning(f"WillGate: Hard gate failure on '{value_name}'.")
                return ("violation", "scope_violation")

        return ("approve", "hard_gates_passed")

    def evaluate_spirit_score(self, spirit_assessment: Dict[str, Any]) -> Tuple[str, str]:
        """
        Evaluates Spirit's aggregated alignment assessment and returns a gate decision.
        Will owns all block/approve decisions; Spirit only aggregates.
        """
        if spirit_assessment.get("critical_violation"):
            # Use ethical_violation so the persona's own rephrase directive fires
            # (every persona defines this key). Phase 4.5 hard-gate already handles
            # true scope breaches — anything reaching here is a content quality issue.
            return ("violation", "ethical_violation")
        if spirit_assessment.get("alignment_score", 1.0) < 0.5:
            return ("violation", "low_alignment_score")
        return ("approve", "alignment_within_threshold")

    async def evaluate_tool_intent(
        self,
        tool_name: str,
        parameters: dict,
        profile: dict,
    ) -> Tuple[str, str]:
        """
        Evaluates a proposed tool call using CQRS pattern before any execution occurs.
        No LLM calls.

        Decision flow:
          1. Profile allow-list   — structural block if tool not permitted.
          2. Parameter constraints — structural block if values are out of range.
          3. Fast pass / Auto approve for allowed tools.
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

        # --- Step 4: Pure deterministic pass for allowed write/command tools ---
        self.log.info(f"WillGate: Deterministically approved write/command tool '{tool_name}'.")
        return ("approve", "Passed structural and allow-list constraints.")
