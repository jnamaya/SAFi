"""
Defines the SpiritIntegrator class.

Integrates Conscience evaluations into a long-term spirit memory vector (mu).
"""
from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional

# Relative import from within the 'faculties' package
from .utils import _norm_label


class SpiritIntegrator:
    """
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    This class performs mathematical operations to update the AI's ethical alignment over time.
    """

    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        """Initializes the SpiritIntegrator."""
        self.values = values
        self.beta = beta
        self.value_weights = (
            np.array([v["weight"] for v in self.values]) if self.values else np.array([1.0])
        )
        self._norm_values = (
            [_norm_label(v["value"]) for v in self.values] if self.values else []
        )
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(self, ledger: List[Dict[str, Any]], mu_tm1: np.ndarray):
        """
        Updates the spirit memory vector based on the latest audit ledger.
        """
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        lmap: Dict[str, Dict[str, Any]] = {
            _norm_label(row.get("value")): row for row in ledger if row.get("value")
        }
        sorted_rows: List[Optional[Dict[str, Any]]] = [
            lmap.get(nkey) for nkey in self._norm_values
        ]

        if any(r is None for r in sorted_rows):
            missing = [self.values[i]["value"] for i, r in enumerate(sorted_rows) if r is None]
            note = f"Ledger missing values: {', '.join(missing)}"
            return 1, note, mu_tm1, np.zeros_like(mu_tm1), None

        scores = np.array([float(r.get("score", 0.0)) for r in sorted_rows], dtype=float)
        confidences = np.array(
            [float(r.get("confidence", 0.0)) for r in sorted_rows], dtype=float
        )

        raw = float(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))

        p_t = self.value_weights * scores
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift