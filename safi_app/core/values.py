"""Backward-compatibility shim. The canonical module is synderesis.py."""
from .synderesis import (  # noqa: F401
    PERSONAS,
    GOVERNANCE_MAP,
    get_profile,
    list_profiles,
    load_custom_persona,
    list_custom_personas,
    assemble_agent,
    _normalize_weights,
    _inject_scope_compliance,
)
