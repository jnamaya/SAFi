"""
This package bundles the core "faculties" of the SAFi agent.

By importing them here, the orchestrator can continue to import them
from 'safi_app.core.faculties' as if it were a single file,
e.g., `from .faculties import IntellectEngine`.
"""
from __future__ import annotations
from .intellect import IntellectEngine
from .will import WillGate
from .conscience import ConscienceAuditor
from .spirit import SpiritIntegrator
from .phase_zero import PhaseZeroGate
from .synderesis import PERSONAS, GOVERNANCE_MAP, get_profile, list_profiles, assemble_agent

__all__ = [
    "IntellectEngine",
    "WillGate",
    "ConscienceAuditor",
    "SpiritIntegrator",
    "PhaseZeroGate",
    "PERSONAS",
    "GOVERNANCE_MAP",
    "get_profile",
    "list_profiles",
    "assemble_agent",
]