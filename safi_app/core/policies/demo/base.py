"""Shared helpers for demo business-unit policies."""
from __future__ import annotations

import copy
from typing import Any, Dict, List


def lift_values(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lift agent values to the policy tier. Hard gates get weight 0: a gate is
    a bright line that blocks on -1, never a component of the alignment average
    (weight != non-negotiability). Scored values keep their authored ratios;
    the compiler renormalizes them to sum to 1.0."""
    out = copy.deepcopy(values)
    for v in out:
        if v.get("hard_gate"):
            v["weight"] = 0.0
    return out


# Alias for internal use
_lift_values = lift_values
