"""Re-exports every faculty so callers import them from one surface.

Pipeline order: PhaseZeroGate gates the raw prompt, IntellectEngine drafts,
ConscienceAuditor scores the draft against Synderesis-compiled values,
SpiritIntegrator aggregates, and WillGate is the only thing that may approve
or block. Synderesis itself is the compiler that builds those values.
"""
from __future__ import annotations
from .intellect import IntellectEngine
from .will import WillGate
from .conscience import ConscienceAuditor
from .spirit import SpiritIntegrator
from .phase_zero import PhaseZeroGate
from .synderesis import compile_profile, assemble_agent, apply_charter

__all__ = [
    "IntellectEngine",
    "WillGate",
    "ConscienceAuditor",
    "SpiritIntegrator",
    "PhaseZeroGate",
    "compile_profile",
    "assemble_agent",
    "apply_charter",
]
