"""Pure governance-profile compiler.

Synderesis accepts plain profile and governance data and returns a compiled
profile. Catalog discovery, persistence, environment configuration, and
connector registration belong to the application adapter and are never loaded
from this module.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .utils import _norm_label
from .will import ALLOWED_GATE_REASONS

log = logging.getLogger(__name__)


def _normalize_weights(values: List[Dict[str, Any]], target_sum: float = 1.0) -> List[Dict[str, Any]]:
    """Normalize relative weights, distributing an all-zero set evenly."""
    if not values:
        return []
    normalized = copy.deepcopy(values)
    for value in normalized:
        if "weight" not in value:
            value["weight"] = 1.0
    current_sum = sum(float(value.get("weight", 0)) for value in normalized)
    if current_sum <= 0:
        share = target_sum / len(normalized)
        for value in normalized:
            value["weight"] = round(share, 3)
        return normalized
    factor = target_sum / current_sum
    for value in normalized:
        value["weight"] = round(float(value.get("weight", 0)) * factor, 3)
    return normalized


def _has_usable_rubric(value: Dict[str, Any]) -> bool:
    rubric = value.get("rubric")
    if isinstance(rubric, list):
        return bool(rubric)
    if isinstance(rubric, dict):
        guide = rubric.get("scoring_guide")
        return bool(guide) if isinstance(guide, list) else bool(str(rubric.get("description") or "").strip())
    return False


def _validate_value_rubrics(profile: Dict[str, Any], profile_label: str = "profile") -> Dict[str, Any]:
    """Fail on unscorable hard gates and discard unscorable ordinary values."""
    values = profile.get("values", [])
    bad_gates = [
        value.get("value") or value.get("name") or "<unnamed>"
        for value in values if value.get("hard_gate") and not _has_usable_rubric(value)
    ]
    if bad_gates:
        raise ValueError(
            f"Profile '{profile_label}' has hard-gate value(s) without a usable rubric: "
            f"{', '.join(repr(name) for name in bad_gates)}."
        )
    stripped = [
        value.get("value") or value.get("name") or "<unnamed>"
        for value in values if not value.get("hard_gate") and not _has_usable_rubric(value)
    ]
    if stripped:
        log.warning("Profile '%s': removing values without usable rubrics: %s", profile_label, stripped)
        profile = copy.deepcopy(profile)
        gates = [value for value in profile["values"] if value.get("hard_gate")]
        scored = [
            value for value in profile["values"]
            if not value.get("hard_gate") and _has_usable_rubric(value)
        ]
        profile["values"] = gates + _normalize_weights(scored)
    return profile


def assemble_agent(
    base_profile: Dict[str, Any],
    governance: Dict[str, Any],
    governance_weight: float = 0.60,
) -> Dict[str, Any]:
    """Combine supplied role and policy data using the standard precedence."""
    profile = copy.deepcopy(base_profile)
    governance = governance or {}
    profile["worldview"] = (
        "--- Organizational Policy ---\n"
        f"{governance.get('global_worldview', '')}\n"
        "--- Specific Role ---\n"
        f"{profile.get('worldview', '')}"
    )
    if governance.get("scope_statement"):
        profile["scope_statement"] = governance["scope_statement"]

    agent_rules = profile.get("will_rules", [])
    policy_rules = governance.get("global_will_rules", [])
    if isinstance(agent_rules, dict) or isinstance(policy_rules, dict):
        agent_dict = agent_rules if isinstance(agent_rules, dict) else {}
        policy_dict = policy_rules if isinstance(policy_rules, dict) else {}
        agent_prose = agent_rules if isinstance(agent_rules, list) else list(agent_dict.get("rules") or [])
        policy_prose = policy_rules if isinstance(policy_rules, list) else list(policy_dict.get("rules") or [])
        merged = copy.deepcopy(agent_dict)
        structural = dict(merged.get("structural_requirements") or {})
        for key, value in (policy_dict.get("structural_requirements") or {}).items():
            if value not in (None, "", []):
                structural[key] = value
        if structural:
            merged["structural_requirements"] = structural
        for key, value in policy_dict.items():
            if key != "structural_requirements" and key not in merged:
                merged[key] = value
        prose = list(policy_prose)
        prose.extend(rule for rule in agent_prose if rule not in prose)
        if prose:
            merged["rules"] = prose
        profile["will_rules"] = merged
    else:
        profile["will_rules"] = list(policy_rules or []) + list(agent_rules or [])

    policy_weight = max(0.0, min(1.0, float(governance_weight)))
    org_values = _normalize_weights(governance.get("global_values", []), policy_weight)
    role_values = _normalize_weights(profile.get("values", []), 1.0 - policy_weight)
    values = org_values + role_values
    for value in values:
        if "value" not in value and "name" in value:
            value["value"] = value["name"]
    profile["values"] = values
    return profile


def _apply_ai_standards(
    profile: Dict[str, Any],
    standards: Dict[str, Any],
    tool_catalog: Optional[Mapping[str, Iterable[str]]] = None,
) -> Dict[str, Any]:
    standards = standards or {}
    structural_in = standards.get("structural_requirements") or {}
    blacklist_in = [item for item in (standards.get("early_prompt_blacklist") or []) if str(item).strip()]
    tools_in = standards.get("allowed_tools")
    if not structural_in and not blacklist_in and not isinstance(tools_in, list):
        return profile

    rules = profile.get("will_rules")
    merged = copy.deepcopy(rules) if isinstance(rules, dict) else ({"rules": list(rules)} if rules else {})
    structural = dict(merged.get("structural_requirements") or {})
    if structural_in.get("require_disclaimer"):
        structural["require_disclaimer"] = True
    for key in ("mandatory_disclaimer_substring", "disclaimer_repair_text"):
        value = str(structural_in.get(key) or "").strip()
        if value:
            structural[key] = value
    for key in ("banned_markdown_syntaxes", "pii_validators"):
        values = list(structural.get(key) or [])
        for value in structural_in.get(key) or []:
            if value and value not in values:
                values.append(value)
        if values:
            structural[key] = values
    threshold = structural_in.get("alignment_score_threshold")
    if threshold is not None:
        try:
            old = structural.get("alignment_score_threshold")
            structural["alignment_score_threshold"] = float(threshold) if old is None else max(float(old), float(threshold))
        except (TypeError, ValueError):
            log.warning("Ignoring invalid alignment threshold in supplied standards.")
    if structural:
        merged["structural_requirements"] = structural

    if blacklist_in:
        blacklist = list(merged.get("early_prompt_blacklist") or [])
        blacklist.extend(item for item in blacklist_in if item not in blacklist)
        merged["early_prompt_blacklist"] = blacklist

    if isinstance(tools_in, list) and tools_in:
        existing = merged.get("allowed_tools")
        if isinstance(existing, list) and existing:
            allowed = set(_expand_declared_tools(tools_in, tool_catalog))
            merged["allowed_tools"] = [
                item for item in _expand_declared_tools(existing, tool_catalog) if item in allowed
            ]
        else:
            merged["allowed_tools"] = list(tools_in)
    profile["will_rules"] = merged
    return profile


def apply_charter(
    profile: Dict[str, Any],
    charter: Optional[Dict[str, Any]],
    policy_values: Optional[List[Dict[str, Any]]] = None,
    charter_weight: float = 0.40,
    ai_standards: Optional[Dict[str, Any]] = None,
    tool_catalog: Optional[Mapping[str, Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Apply supplied organization values and standards to a profile."""
    profile = copy.deepcopy(profile)
    charter = charter or {}
    policy_values = policy_values or []
    ai_standards = ai_standards or {}
    profile = _apply_ai_standards(profile, ai_standards, tool_catalog)

    mission = (charter.get("mission") or "").strip()
    charter_values = charter.get("core_values") or []
    if mission or charter_values:
        names = [value.get("name") or value.get("value") for value in charter_values if isinstance(value, dict)]
        names = [name for name in names if name]
        lines = ["--- Organization Context ---"]
        if mission:
            lines.append(f"Mission: {mission}")
        if names:
            lines.append(f"Organization values: {', '.join(names)}.")
        profile["worldview"] = "\n".join(lines) + "\n\n" + (profile.get("worldview") or "")

    def map_values(values):
        out = copy.deepcopy(values or [])
        for value in out:
            if "value" not in value and "name" in value:
                value["value"] = value["name"]
        return out

    charter_values = map_values(charter_values)
    policy_values = map_values(policy_values)
    ai_values = map_values([value for value in (ai_standards.get("values") or []) if isinstance(value, dict)])
    ai_gates = [value for value in ai_values if value.get("hard_gate")]
    ai_scored = [value for value in ai_values if not value.get("hard_gate")]
    for value in ai_gates:
        value["weight"] = 0.0
    existing_gates = [value for value in profile.get("values", []) if value.get("hard_gate")]
    charter_gates = [value for value in charter_values if value.get("hard_gate")]
    org_scored = [value for value in charter_values if not value.get("hard_gate")] + ai_scored
    policy_gates = [value for value in policy_values if value.get("hard_gate")]
    policy_scored = [value for value in policy_values if not value.get("hard_gate")]

    gates: Dict[str, Dict[str, Any]] = {}
    for value in ai_gates + existing_gates + charter_gates + policy_gates:
        label = value.get("value") or value.get("name")
        retained = gates.get(label)
        if retained is None:
            gates[label] = value
        elif not retained.get("gate_reason") and value.get("gate_reason"):
            retained["gate_reason"] = value["gate_reason"]

    weight = max(0.0, min(1.0, float(charter_weight)))
    if org_scored and policy_scored:
        scored = _normalize_weights(org_scored, weight) + _normalize_weights(policy_scored, 1.0 - weight)
    elif org_scored:
        scored = _normalize_weights(org_scored)
    elif policy_scored:
        scored = _normalize_weights(policy_scored)
    else:
        scored = [value for value in profile.get("values", []) if not value.get("hard_gate")]
    profile["values"] = list(gates.values()) + scored
    return profile


def _expand_declared_tools(names: Iterable[str], catalog: Optional[Mapping[str, Iterable[str]]]) -> List[str]:
    """Expand opaque connector identifiers using caller-supplied catalog data."""
    expanded: List[str] = []
    seen = set()
    catalog = catalog or {}
    for name in names:
        if not isinstance(name, str):
            continue
        for function_name in catalog.get(name, (name,)):
            if isinstance(function_name, str) and function_name and function_name not in seen:
                seen.add(function_name)
                expanded.append(function_name)
    return expanded


def authorized_tools(advertised: Any, policy_allowed: Any, tool_catalog=None) -> List[str]:
    advertised_names = _expand_declared_tools(advertised or [], tool_catalog)
    if isinstance(policy_allowed, list) and policy_allowed:
        allowed = set(_expand_declared_tools(policy_allowed, tool_catalog))
        return [name for name in advertised_names if name in allowed]
    return advertised_names


def authorized_knowledge_base(requested: Optional[str], policy_allowed: Optional[Any]) -> Optional[str]:
    if not requested or not isinstance(policy_allowed, list):
        return requested
    return requested if requested in policy_allowed else None


def _stamp_knowledge_authorization(profile: Dict[str, Any]) -> Dict[str, Any]:
    rules = profile.get("will_rules")
    allowed = rules.get("allowed_knowledge_bases") if isinstance(rules, dict) else None
    requested = profile.get("rag_knowledge_base")
    if requested and not authorized_knowledge_base(requested, allowed):
        log.warning("Requested knowledge source is not authorized by the supplied profile rules.")
        profile["rag_knowledge_base"] = None
        profile["rag_blocked_by_policy"] = requested
    return profile


def _stamp_gate_reasons(profile: Dict[str, Any]) -> Dict[str, Any]:
    for value in profile.get("values", []):
        if value.get("hard_gate") and value.get("gate_reason") not in ALLOWED_GATE_REASONS:
            value["gate_reason"] = "hard_gate_violation"
    return profile


def _stamp_tool_authorization(profile: Dict[str, Any], tool_catalog=None) -> Dict[str, Any]:
    rules = profile.get("will_rules")
    policy_allowed = rules.get("allowed_tools") if isinstance(rules, dict) else None
    profile["allowed_tools"] = authorized_tools(profile.get("tools"), policy_allowed, tool_catalog)
    constraints = rules.get("tool_parameter_constraints") if isinstance(rules, dict) else None
    if isinstance(constraints, dict) and "tool_parameter_constraints" not in profile:
        profile["tool_parameter_constraints"] = constraints
    return profile


def _inject_disclaimer_directive(profile: Dict[str, Any]) -> Dict[str, Any]:
    rules = profile.get("will_rules")
    if not isinstance(rules, dict):
        return profile
    structural = rules.get("structural_requirements") or {}
    disclaimer = (structural.get("mandatory_disclaimer_substring") or "").strip()
    if not structural.get("require_disclaimer") or not disclaimer:
        return profile
    worldview = profile.get("worldview", "") or ""
    if disclaimer not in worldview:
        profile["worldview"] = worldview + (
            "\n\n--- Mandatory Disclosure ---\n"
            "End every response with this exact text:\n" + disclaimer + "\n"
        )
    return profile


def compile_profile(
    agent: Dict[str, Any],
    governance: Optional[Dict[str, Any]] = None,
    *,
    charter: Optional[Dict[str, Any]] = None,
    policy_values: Optional[List[Dict[str, Any]]] = None,
    charter_weight: float = 0.40,
    ai_standards: Optional[Dict[str, Any]] = None,
    tool_catalog: Optional[Mapping[str, Iterable[str]]] = None,
    scope_value: Optional[Dict[str, Any]] = None,
    scope_directive: str = "",
) -> Dict[str, Any]:
    """Compile supplied data; catalog and persistence resolution stay in host code."""
    if governance:
        profile = assemble_agent(agent, governance)
    else:
        profile = copy.deepcopy(agent)
        profile["values"] = _normalize_weights(profile.get("values", []), 1.0)
    if scope_value:
        profile["values"] = [copy.deepcopy(scope_value)] + list(profile.get("values") or [])
    if scope_directive:
        profile["worldview"] = (profile.get("worldview") or "") + scope_directive
    profile = apply_charter(
        profile,
        charter,
        policy_values=policy_values,
        charter_weight=charter_weight,
        ai_standards=ai_standards,
        tool_catalog=tool_catalog,
    )
    profile = _inject_disclaimer_directive(profile)
    profile = _validate_value_rubrics(profile, str(agent.get("key") or agent.get("name") or "profile"))
    profile = _stamp_tool_authorization(profile, tool_catalog)
    profile = _stamp_gate_reasons(profile)
    return _stamp_knowledge_authorization(profile)
