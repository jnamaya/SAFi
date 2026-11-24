"""Spirit (Habitus & Telos) — Enduring Disposition and Teleological Alignment.

In Thomas Aquinas's Summa Theologiae (I-II, q. 49–54), repeated acts form an
enduring disposition (habitus) that either strengthens or erodes a rational
agent's orientation toward its proper end (telos).

In SAFi, this module tracks alignment scores and behavioral drift across turns,
measuring whether the agent's concrete acts remain ordered toward its defined
purpose over time rather than decaying under pressure.
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union

from .utils import _norm_label


class SpiritIntegrator:

    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        self.values = values
        self.beta = beta


        self.value_weights = (
            np.array([float(v.get("weight", 0.2)) for v in self.values], dtype=float) if self.values else np.array([1.0])
        )

        self._norm_values = (
            [_norm_label(v.get("value") or v.get("name") or "Unknown_Value") for v in self.values] if self.values else []
        )
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def integrate(self, ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
        critical_violation = False
        weighted_sum = 0.0
        weight_total = 0.0
        matched = 0

        lmap = {_norm_label(row.get("value")): row for row in ledger if row.get("value")}

        for i, val_dict in enumerate(self.values):
            nkey = self._norm_values[i]
            weight = self.value_weights[i]

            row = lmap.get(nkey)
            if row is not None:
                matched += 1
                score = float(row.get("score", 0.0))


                if score <= -1.0 and val_dict.get("hard_gate"):
                    critical_violation = True


                scaled_score = (score + 1.0) / 2.0
                weighted_sum += weight * scaled_score
                weight_total += weight
            else:

                weighted_sum += weight * 0.5
                weight_total += weight

        alignment_score = (weighted_sum / weight_total) if weight_total > 0 else 0.5


        if self.values and matched == 0:
            return {"critical_violation": True, "alignment_score": 0.0}

        return {
            "critical_violation": critical_violation,
            "alignment_score": alignment_score
        }

    def compute(
        self, 
        ledger: List[Dict[str, Any]], 
        mu_memory: Union[np.ndarray, List, Dict[str, float]]
    ) -> Tuple[int, str, Union[Dict[str, float], np.ndarray], np.ndarray, Optional[float], np.ndarray]:
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_memory, np.zeros(len(self.values)), None, np.zeros(len(self.values))


        expected_len = len(self.value_weights)
        mu_tm1_vector = np.zeros(expected_len)

        is_legacy = isinstance(mu_memory, (list, np.ndarray))

        if is_legacy:

            old_arr = np.array(mu_memory)
            if old_arr.shape[0] != expected_len:
                common_len = min(expected_len, old_arr.shape[0])
                mu_tm1_vector[:common_len] = old_arr[:common_len]
            else:
                mu_tm1_vector = old_arr
        else:

            for i, norm_name in enumerate(self._norm_values):
                mu_tm1_vector[i] = mu_memory.get(norm_name, 0.0)


        lmap: Dict[str, Dict[str, Any]] = {
            _norm_label(row.get("value")): row for row in ledger if row.get("value")
        }
        sorted_rows: List[Optional[Dict[str, Any]]] = [
            lmap.get(nkey) for nkey in self._norm_values
        ]

        missing = [
            self.values[i].get("value") or self.values[i].get("name") or "Unknown"
            for i, r in enumerate(sorted_rows) if r is None
        ]
        if len(missing) == len(sorted_rows):


            return 1, f"Ledger missing: {', '.join(missing)}", mu_memory, np.zeros(expected_len), None, np.zeros(expected_len)


        observed = np.array([r is not None for r in sorted_rows], dtype=bool)
        scores = np.nan_to_num(
            np.array([float(r.get("score", 0.0)) if r else 0.0 for r in sorted_rows], dtype=float)
        )
        confidences = np.nan_to_num(
            np.array([float(r.get("confidence", 0.0)) if r else 0.0 for r in sorted_rows], dtype=float)
        )


        raw = float(np.nan_to_num(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1)))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))
        p_t = self.value_weights * scores


        ema = self.beta * mu_tm1_vector + (1 - self.beta) * p_t
        mu_new_vector = np.where(observed, ema, mu_tm1_vector)


        if is_legacy:


            new_memory_dict = {}
        else:

            new_memory_dict = mu_memory.copy()

        for i, norm_name in enumerate(self._norm_values):
            new_memory_dict[norm_name] = float(mu_new_vector[i])


        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1_vector))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1_vector) / denom)


        drift_text = "undefined" if drift is None else f"{drift:.2f}"
        note = f"Alignment {spirit_score}/10, drift {drift_text}."
        if missing:
            note += f" Unscored: {', '.join(missing)}."

        return spirit_score, note, new_memory_dict, p_t, drift, mu_new_vector

    def compute_redirect(self, ledger: List[Dict[str, Any]]) -> Tuple[int, str]:
        if not ledger:
            return 1, "No redirect rubric data."

        scores = [float(r.get("score", 0.0)) for r in ledger if r.get("value")]
        if not scores:
            return 1, "No redirect rubric data."

        avg = sum(scores) / len(scores)

        spirit_score = int(round((avg + 1) / 2 * 9 + 1))
        spirit_score = max(1, min(10, spirit_score))
        note = f"Redirect quality {spirit_score}/10 ({len(scores)} rubrics; spirit memory unchanged)."
        return spirit_score, note


def build_spirit_feedback(
    mu: np.ndarray,
    value_names: List[str],
    drift: float,
    recent_mu: Optional[List[np.ndarray]] = None,
    drift_bands=(0.10, 0.20, 0.40),
    trend_window: int = 3,
    value_weights: Optional[List[float]] = None,
    value_descriptions: Optional[List[str]] = None,
    last_pt: Optional[np.ndarray] = None,
) -> str:
    if mu is None or len(mu) == 0 or not value_names:
        return ""

    weights = [float(w or 0.0) for w in (value_weights or [1.0] * len(mu))]


    n = min(len(mu), len(weights), len(value_names))
    active = [i for i in range(n) if weights[i] > 0.0] or list(range(n))


    has_memory = any(abs(float(mu[i])) > 1e-6 for i in active) or (last_pt is not None)
    if not has_memory:
        return ""

    def wavg(vec) -> float:
        den = sum(weights[i] for i in active) or 1.0
        return sum(weights[i] * float(vec[i]) for i in active if i < len(vec)) / den

    baseline = wavg(mu)
    turn_level = wavg(last_pt) if last_pt is not None else None
    decline = (baseline - turn_level) if turn_level is not None else 0.0

    a, b, c = drift_bands
    d = drift or 0.0

    if not (d >= a or decline > 0.05 or baseline < 0.50):
        return ""


    if d >= c or decline > 0.20 or baseline < 0.30:
        verb = "have fallen well below your usual standard"
        close = "Be markedly more deliberate, complete, and precise this turn."
    elif d >= b or decline > 0.10 or baseline < 0.45:
        verb = "have trended below your usual standard"
        close = "Be more deliberate and thorough this turn."
    else:
        verb = "have slipped slightly from your usual standard"
        close = "Stay deliberate and consistent this turn."


    def attention(i: int) -> float:
        if last_pt is not None and i < len(last_pt):
            return weights[i] * max(0.0, float(mu[i]) - float(last_pt[i]))
        return weights[i] * max(0.0, 0.65 - float(mu[i]))

    ranked = sorted(active, key=attention, reverse=True)
    name_clause = ""
    if ranked and attention(ranked[0]) > 0.03:
        name_clause = f", most notably around {value_names[ranked[0]]}"

    return f"Self-check: your recent responses {verb}{name_clause}. {close}"
