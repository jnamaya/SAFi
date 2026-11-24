from __future__ import annotations

import copy
from typing import Any, Dict, List


def lift_values(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = copy.deepcopy(values)
    for v in out:
        if v.get("hard_gate"):
            v["weight"] = 0.0
    return out


_lift_values = lift_values
