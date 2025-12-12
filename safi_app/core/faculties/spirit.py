"""
Defines the SpiritIntegrator class.

This module contains the core mathematical logic for updating the agent's
long-term ethical alignment vector (mu).
"""
from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional

# Relative import from within the 'faculties' package
from .utils import _norm_label


class SpiritIntegrator:
    """
    Integrates Conscience evaluations into a long-term spirit memory vector (mu).
    
    This class performs mathematical operations to update the AI's ethical 
    alignment over time. It uses an exponential moving average (EMA) to 
    integrate new observations (p_t) into the existing memory (mu_tm1).
    """

    def __init__(self, values: List[Dict[str, Any]], beta: float = 0.9):
        """
        Initializes the SpiritIntegrator.

        Args:
            values: The list of value dictionaries for this persona.
            beta: The smoothing factor for the exponential moving average.
                  A high value (e.g., 0.9) means slow changes (long memory).
                  A low value (e.g., 0.1) means fast changes (short memory).
        """
        self.values = values
        self.beta = beta
        
        # Pre-calculate value weights as a numpy array
        # ROBUSTNESS FIX: Handle missing keys (custom wizard uses 'name', legacy uses 'value')
        self.value_weights = (
            np.array([float(v.get("weight", 0.2)) for v in self.values], dtype=float) if self.values else np.array([1.0])
        )
        
        # Pre-calculate normalized value names for quick lookup
        self._norm_values = (
            [_norm_label(v.get("value") or v.get("name") or "Unknown_Value") for v in self.values] if self.values else []
        )
        self._norm_index = {name: i for i, name in enumerate(self._norm_values)}

    def compute(
        self, 
        ledger: List[Dict[str, Any]], 
        mu_tm1: np.ndarray
    ) -> Tuple[int, str, np.ndarray, np.ndarray, Optional[float]]:
        """
        Updates the spirit memory vector based on the latest audit ledger.

        Args:
            ledger: The list of evaluation dicts from the Conscience.
            mu_tm1: The spirit vector from the previous turn (t-1).

        Returns:
            A tuple containing:
            (spirit_score, note, mu_new, p_t, drift)
            - spirit_score: A 1-10 score for this turn's coherence.
            - note: A human-readable note about the computation.
            - mu_new: The updated spirit vector for this turn (t).
            - p_t: The raw alignment vector for this turn.
            - drift: The cosine drift between p_t and mu_tm1 (None if invalid).
        """
        if not self.values or not ledger:
            return 1, "Incomplete ledger", mu_tm1, np.zeros_like(mu_tm1), None

        # --- 1. Parse and Sort Ledger ---
        # Create a map of normalized value names to their ledger rows
        lmap: Dict[str, Dict[str, Any]] = {
            _norm_label(row.get("value")): row for row in ledger if row.get("value")
        }
        # Sort the rows to match the canonical order of self.values
        sorted_rows: List[Optional[Dict[str, Any]]] = [
            lmap.get(nkey) for nkey in self._norm_values
        ]

        # Check if any values were missing from the audit
        if any(r is None for r in sorted_rows):
            missing = [self.values[i]["value"] for i, r in enumerate(sorted_rows) if r is None]
            note = f"Ledger missing values: {', '.join(missing)}"
            return 1, note, mu_tm1, np.zeros_like(mu_tm1), None

        # Convert scores and confidences to numpy arrays, handling potential None/NaN
        scores = np.nan_to_num(
            np.array([float(r.get("score", 0.0)) if r.get("score") is not None else 0.0 for r in sorted_rows], dtype=float)
        )
        confidences = np.nan_to_num(
            np.array([float(r.get("confidence", 0.0)) if r.get("confidence") is not None else 0.0 for r in sorted_rows], dtype=float)
        )

        # --- 2. Calculate This Turn's Vector (p_t) ---
        # Calculate the raw weighted, confidence-adjusted score
        # nan_to_num ensures we don't propagate NaNs
        raw = float(np.nan_to_num(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1)))
        # Normalize the raw score to a 1-10 spirit score
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))
        
        # p_t is the alignment vector for this turn, based on score and weight
        p_t = self.value_weights * scores

        # --- 3. Update Spirit Vector (mu) ---
        # Apply the exponential moving average (EMA)
        # mu_new = (beta * old_memory) + ((1 - beta) * new_observation)
        mu_new = self.beta * mu_tm1 + (1 - self.beta) * p_t

        # --- 4. Calculate Drift ---
        # Calculate the cosine drift (1 - cosine_similarity)
        # This measures how much the new observation (p_t) diverges from the old memory (mu_tm1).
        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        return spirit_score, note, mu_new, p_t, drift