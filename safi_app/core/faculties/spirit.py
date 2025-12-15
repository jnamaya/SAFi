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
        mu_memory: Union[np.ndarray, List, Dict[str, float]]
    ) -> Tuple[int, str, Union[Dict[str, float], np.ndarray], np.ndarray, Optional[float]]:
        """
        Updates the spirit memory vector based on the latest audit ledger.
        """
        if not self.values or not ledger:
            # Return same memory if no update possible
            return 1, "Incomplete ledger", mu_memory, np.zeros(len(self.values)), None

        # --- 1. Resolve Memory to Vector (Transition Logic) ---
        expected_len = len(self.value_weights)
        mu_tm1_vector = np.zeros(expected_len)
        
        # Determine format
        is_legacy = isinstance(mu_memory, (list, np.ndarray))
        
        if is_legacy:
            # LEGACY: Positional Memory
            old_arr = np.array(mu_memory)
            if old_arr.shape[0] != expected_len:
                # Resize logic (Pad/Truncate)
                common_len = min(expected_len, old_arr.shape[0])
                mu_tm1_vector[:common_len] = old_arr[:common_len]
            else:
                mu_tm1_vector = old_arr
        else:
            # MODERN: Semantic Memory (Dict)
            # Map current values to memory keys
            for i, norm_name in enumerate(self._norm_values):
                mu_tm1_vector[i] = mu_memory.get(norm_name, 0.0)

        # --- 2. Parse and Sort Ledger ---
        lmap: Dict[str, Dict[str, Any]] = {
            _norm_label(row.get("value")): row for row in ledger if row.get("value")
        }
        sorted_rows: List[Optional[Dict[str, Any]]] = [
            lmap.get(nkey) for nkey in self._norm_values
        ]

        if any(r is None for r in sorted_rows):
            missing = [self.values[i]["value"] for i, r in enumerate(sorted_rows) if r is None]
            # Safety return
            return 1, f"Ledger missing: {', '.join(missing)}", mu_memory, np.zeros(expected_len), None

        # Convert scores/confidences
        scores = np.nan_to_num(
            np.array([float(r.get("score", 0.0)) for r in sorted_rows], dtype=float)
        )
        confidences = np.nan_to_num(
            np.array([float(r.get("confidence", 0.0)) for r in sorted_rows], dtype=float)
        )

        # --- 3. Compute This Turn (p_t) ---
        raw = float(np.nan_to_num(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1)))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))
        p_t = self.value_weights * scores

        # --- 4. Update Spirit Vector (mu) ---
        # mu_new_vector only contains CURRENT active values
        mu_new_vector = self.beta * mu_tm1_vector + (1 - self.beta) * p_t

        # --- 5. Export Memory (Reconstruct Dict) ---
        if is_legacy:
            # First time migration: Start fresh dict
            new_memory_dict = {}
        else:
            # Checkpoint: Copy old memory to preserve DORMANT values (values not in current policy)
            new_memory_dict = mu_memory.copy()
        
        # Update/Overwrite keys for CURRENT values
        for i, norm_name in enumerate(self._norm_values):
            new_memory_dict[norm_name] = float(mu_new_vector[i])

        # --- 6. Calculate Drift ---
        eps = 1e-8
        denom = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1_vector))
        drift = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1_vector) / denom)

        note = f"Coherence {spirit_score}/10, drift {0.0 if drift is None else drift:.2f}."
        
        # Return the DICTIONARY memory for storage
        return spirit_score, note, new_memory_dict, p_t, drift