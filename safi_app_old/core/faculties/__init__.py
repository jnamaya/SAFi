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

__all__ = [
    "IntellectEngine",
    "WillGate",
    "ConscienceAuditor",
    "SpiritIntegrator",
]