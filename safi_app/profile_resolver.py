"""Application adapter for profile catalogs and persisted governance data.

This module owns user-land resolution: built-in and extension catalogs,
database reads, connector metadata, and display-only labels. It passes plain
data to the pure Synderesis compiler in ``core.faculties.synderesis``.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import pkgutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .persistence import database as db
from .core import agents as _agents_pkg
from .core import tool_connectors
from . import security_policy
from .core.faculties import synderesis as compiler
from .core.faculties.utils import _norm_label
from .core.faculties.will import ALLOWED_GATE_REASONS
from .core.services.retriever import resolve_rag_format_string
from .core.policies import runtime_defaults
from .role_config import ROLE_CONFIG, ROLE_CONFIG_VERSION

log = logging.getLogger(__name__)


def _load_catalog() -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], set[str]]:
    all_agents: Dict[str, Dict[str, Any]] = {}
    fallback_keys: List[str] = []
    for info in pkgutil.iter_modules(_agents_pkg.__path__):
        module = importlib.import_module(f"{_agents_pkg.__name__}.{info.name}")
        key = getattr(module, "KEY", None)
        agent = getattr(module, "AGENT", None)
        if not isinstance(key, str) or not key.strip() or not isinstance(agent, dict):
            log.error("Profile module '%s' lacks KEY/AGENT and was skipped.", info.name)
            continue
        key = key.lower().strip()
        if key in all_agents:
            log.error("Profile module '%s' duplicates key '%s' and was skipped.", info.name, key)
            continue
        all_agents[key] = agent
        if getattr(module, "FALLBACK", False):
            fallback_keys.append(key)

    extension_keys: set[str] = set()
    extension_dir = os.environ.get("SAFI_EXTENSIONS_DIR", "").strip()
    if extension_dir and Path(extension_dir).is_dir():
        for extension_file in sorted(Path(extension_dir).glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(
                    f"safi_ext_{extension_file.stem}", extension_file
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                key = str(module.KEY).lower().strip()
                if not key or not isinstance(module.AGENT, dict):
                    raise ValueError("KEY must be a non-empty string and AGENT a dict")
                if key in all_agents:
                    log.error("Extension '%s' shadows a profile key and was refused.", extension_file.name)
                    continue
                all_agents[key] = module.AGENT
                extension_keys.add(key)
            except Exception as exc:
                log.error("Extension '%s' failed to load and was skipped: %s", extension_file.name, exc)

    active = {
        key: agent for key, agent in all_agents.items()
        if Config.builtin_agent_enabled(key) or key in extension_keys
    }
    if not active:
        active = {key: all_agents[key] for key in fallback_keys} or dict(all_agents)
    return all_agents, active, extension_keys


ALL_AGENTS, AGENTS, EXTENSION_KEYS = _load_catalog()
_EXTENSION_KEYS = EXTENSION_KEYS


def _load_profile(name: str) -> Optional[Dict[str, Any]]:
    key = "".join(
        char for char in (name or "").lower().strip().replace(" ", "_")
        if char.isalnum() or char == "_"
    )
    if key in AGENTS:
        return AGENTS[key]
    try:
        agent = db.get_agent(key)
    except Exception:
        log.exception("Could not load profile '%s'.", key)
        return None
    if agent:
        agent.setdefault("values", [])
        agent.setdefault("will_rules", [])
        for value in agent.get("values", []):
            if "name" in value and "value" not in value:
                value["value"] = value["name"]
    return agent


def list_profiles(
    owner_id: Optional[str] = None,
    org_id: Optional[str] = None,
    user_role: Optional[str] = None,
    include_all: bool = False,
):
    builtins = [
        {"key": key, "name": agent["name"], "is_custom": False, "created_by": None}
        for key, agent in AGENTS.items()
    ]
    try:
        custom = db.list_all_agents() if include_all else db.list_agents(
            owner_id, org_id, user_role or ROLE_CONFIG["default_role"],
            ROLE_CONFIG["visibility_roles"],
        )
    except Exception:
        log.exception("Could not list profiles.")
        custom = []
    return sorted(builtins + custom, key=lambda item: item["name"])


def _tool_catalog() -> Dict[str, tuple]:
    return {**tool_connectors.CONNECTOR_TOOLS, **tool_connectors.discovered_connectors()}


def _stamp_legacy_gate_reasons(values):
    """Translate old persisted gate labels at the data boundary."""
    legacy = {
        "scope compliance": "scope_violation",
        "grounding fidelity": "grounding_violation",
    }
    for value in values or []:
        if not value.get("hard_gate") or value.get("gate_reason") in ALLOWED_GATE_REASONS:
            continue
        value["gate_reason"] = legacy.get(
            _norm_label(value.get("value") or value.get("name")),
            "hard_gate_violation",
        )


def _resolve_kb_display_name(kb_name: Optional[str]) -> Optional[str]:
    if not kb_name:
        return None
    if "-" in kb_name and len(kb_name) == 36:
        try:
            kb = db.get_knowledge_base(kb_name)
        except Exception:
            log.exception("Could not resolve knowledge-source display name.")
            return None
        return kb.get("name") if kb else None
    return kb_name.replace("_", " ").replace("-", " ")


def get_profile(name: str, policy_id: Optional[str] = None) -> Dict[str, Any]:
    """Resolve persisted/content inputs, then call the pure profile compiler."""
    raw_agent = _load_profile(name)
    if not raw_agent:
        raise KeyError(f"Unknown profile '{name}'.")
    agent = json.loads(json.dumps(raw_agent))
    _stamp_legacy_gate_reasons(agent.get("values"))

    effective_policy_id = policy_id or agent.get("policy_id")
    org_id = agent.get("org_id")
    policy_values: List[Dict[str, Any]] = []
    policy_config: Dict[str, Any] = {}
    policy_version = None
    policy_name = None
    governance: Dict[str, Any] = {}

    if effective_policy_id and effective_policy_id != "standalone":
        try:
            policy = db.get_policy(effective_policy_id)
        except Exception:
            log.exception("Could not resolve the selected policy.")
            policy = None
        if policy:
            policy_config = policy.get("policy_config") or {}
            policy_version = policy.get("version")
            policy_name = policy.get("name")
            policy_values = json.loads(json.dumps(policy.get("values_weights", []) or []))
            _stamp_legacy_gate_reasons(policy_values)
            governance = {
                "global_worldview": policy.get("worldview", ""),
                "global_will_rules": policy.get("will_rules", []),
                "global_values": policy_values,
                "scope_statement": policy_config.get("scope_statement") or None,
            }
            org_id = policy.get("org_id") or org_id

    charter = None
    ai_standards = None
    charter_weight = 0.40
    spirit_beta = 0.90
    org_name = None
    if org_id:
        try:
            org = db.get_organization(org_id)
            org_name = org.get("name") if org else None
            settings = org.get("settings") if org else None
            if isinstance(settings, str):
                settings = json.loads(settings)
            settings = settings or {}
            charter_weight = float(settings.get("governance_split", charter_weight))
            spirit_beta = float(settings.get("spirit_beta", spirit_beta))
            charter = db.get_charter(org_id)
            ai_standards = db.get_ai_standards(org_id)
        except Exception:
            log.exception("Could not resolve organization governance data.")

    policy_beta = policy_config.get("ethical_memory")
    if policy_beta is not None:
        try:
            spirit_beta = float(policy_beta)
        except (TypeError, ValueError):
            pass

    _stamp_legacy_gate_reasons((charter or {}).get("core_values"))
    _stamp_legacy_gate_reasons((ai_standards or {}).get("values"))
    scope = governance.get("scope_statement") or agent.get("scope_statement")
    scope_value = None
    scope_directive = ""
    if scope:
        scoped = runtime_defaults.inject_scope_compliance({"scope_statement": scope, "values": []})
        scope_value = scoped["values"][0]
        scope_directive = scoped["worldview"]

    final = compiler.compile_profile(
        agent,
        governance,
        charter=charter,
        policy_values=policy_values,
        charter_weight=charter_weight,
        ai_standards=ai_standards,
        tool_catalog=_tool_catalog(),
        scope_value=scope_value,
        scope_directive=scope_directive,
    )
    final.update({
        "policy_id": effective_policy_id or "standalone",
        "policy_version": policy_version,
        "org_id": org_id,
        "spirit_beta": spirit_beta,
        "policy_name": policy_name,
        "org_name": org_name,
        "has_charter": bool(charter),
        "rag_knowledge_base_name": _resolve_kb_display_name(final.get("rag_knowledge_base")),
        "role_config_version": ROLE_CONFIG_VERSION,
    })
    directives = dict(runtime_defaults.DEFAULT_REPHRASE_DIRECTIVES)
    directives.update(final.get("internal_rephrase_directives") or {})
    final["internal_rephrase_directives"] = directives
    final["phase_zero_rules"] = security_policy.PHASE_ZERO_RULES
    final["phase_zero_rules_version"] = security_policy.RULESET_VERSION
    final["pii_validator_catalog"] = security_policy.PII_CATALOGUE
    final["rag_format_string"] = resolve_rag_format_string(final.get("rag_format_string"))
    return final
