"""
Spirit — the mathematical memory of the agent's character.

In Thomistic philosophy, Habitus refers to the accumulation of moral actions that build
stable dispositions over time, forming virtues or vices that shape the ultimate character
of the soul. Here it is the long-term ethical alignment memory of the agent: an exponential
moving average (EMA) smoothly integrates each turn's Conscience ledger into a persistent
alignment vector (mu), measures conceptual drift, and maps ethical performance over time —
translating metaphysical virtue into trackable vector coordinates.
"""
from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union

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
            values: The list of value dictionaries for this agent.
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

    def integrate(self, ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Integrates Conscience evaluations to produce a single actionable decision dict.
        Flags a critical violation only when a HARD-GATE (non-negotiable) value scores
        <= -1.0, and computes a weighted average score scaled to [0.0, 1.0]. A -1 on an
        ordinary (non-hard-gate) value lowers the average but does NOT hard-block — the
        weighted threshold (alignment < 0.5) decides the block for those.
        """
        critical_violation = False
        weighted_sum = 0.0
        weight_total = 0.0
        matched = 0  # how many of this agent's values the audit actually scored

        # Build normalized lookup for values/weights
        lmap = {_norm_label(row.get("value")): row for row in ledger if row.get("value")}

        for i, val_dict in enumerate(self.values):
            nkey = self._norm_values[i]
            weight = self.value_weights[i]

            row = lmap.get(nkey)
            if row is not None:
                matched += 1
                score = float(row.get("score", 0.0))
                # Only NON-NEGOTIABLE (hard-gate) values hard-block on a -1. Ordinary
                # weighted values let a -1 pull down the alignment average instead of
                # forcing an immediate critical violation. (Hard gates are normally
                # caught earlier at Phase 4.5; this stays as defense-in-depth for paths
                # that re-audit without that gate, e.g. the ethical reflexion retry.)
                if score <= -1.0 and val_dict.get("hard_gate"):
                    critical_violation = True

                # Scaled score: map [-1, 1] to [0, 1]
                scaled_score = (score + 1.0) / 2.0
                weighted_sum += weight * scaled_score
                weight_total += weight
            else:
                # If ledger is missing a value, default to neutral (0.0 score -> 0.5 scaled)
                weighted_sum += weight * 0.5
                weight_total += weight

        alignment_score = (weighted_sum / weight_total) if weight_total > 0 else 0.5

        # Fail-closed: a governed agent whose audit scored NONE of its values is
        # a failed audit, not a neutral one — don't let an empty/garbled ledger
        # coast through at the neutral 0.5 default.
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
        """
        Updates the spirit memory vector based on the latest audit ledger.
        Returns: spirit_score, note, new_memory_dict, p_t, drift, mu_new_vector
        """
        if not self.values or not ledger:
            # Return same memory if no update possible
            return 1, "Incomplete ledger", mu_memory, np.zeros(len(self.values)), None, np.zeros(len(self.values))

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

        missing = [
            self.values[i].get("value") or self.values[i].get("name") or "Unknown"
            for i, r in enumerate(sorted_rows) if r is None
        ]
        if len(missing) == len(sorted_rows):
            # Nothing matched at all — no update possible. (The orchestrator's
            # coverage gate fails closed long before this; kept as a safety net.)
            return 1, f"Ledger missing: {', '.join(missing)}", mu_memory, np.zeros(expected_len), None, np.zeros(expected_len)

        # A partially-scored ledger is scored over the values it DID cover —
        # missing values contribute neutrally (score 0), the same treatment
        # integrate() applies when gating. The old all-or-nothing "Ledger
        # missing" return recorded 1/10 for a response the gates had just
        # approved and silently froze the EMA memory.
        observed = np.array([r is not None for r in sorted_rows], dtype=bool)
        scores = np.nan_to_num(
            np.array([float(r.get("score", 0.0)) if r else 0.0 for r in sorted_rows], dtype=float)
        )
        confidences = np.nan_to_num(
            np.array([float(r.get("confidence", 0.0)) if r else 0.0 for r in sorted_rows], dtype=float)
        )

        # --- 3. Compute This Turn (p_t) ---
        raw = float(np.nan_to_num(np.clip(np.sum(self.value_weights * scores * confidences), -1, 1)))
        spirit_score = int(round((raw + 1) / 2 * 9 + 1))
        p_t = self.value_weights * scores

        # --- 4. Update Spirit Vector (mu) ---
        # mu_new_vector only contains CURRENT active values. Observed values get
        # the EMA update; unobserved values HOLD their previous mu — a missing
        # observation is not evidence of neutrality, so their memory neither
        # decays nor moves this turn.
        ema = self.beta * mu_tm1_vector + (1 - self.beta) * p_t
        mu_new_vector = np.where(observed, ema, mu_tm1_vector)

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

        # Undefined, not 0.00. An agent with no accumulated character has
        # nothing to deviate from, and reporting zero claims perfect
        # consistency it has not earned. The stored value was already
        # None; only this human-readable line said otherwise.
        drift_text = "undefined" if drift is None else f"{drift:.2f}"
        note = f"Alignment {spirit_score}/10, drift {drift_text}."
        if missing:
            note += f" Unscored: {', '.join(missing)}."

        # Return the DICTIONARY memory for storage, AND the vector for in-memory history
        return spirit_score, note, new_memory_dict, p_t, drift, mu_new_vector

    def compute_redirect(self, ledger: List[Dict[str, Any]]) -> Tuple[int, str]:
        """
        Computes a spirit quality score from a redirect audit ledger.
        Does NOT update spirit memory — redirect quality is evaluated separately
        from content value alignment so the EMA is not polluted with non-content scores.
        Returns: (spirit_score 1-10, note)
        """
        if not ledger:
            return 1, "No redirect rubric data."

        scores = [float(r.get("score", 0.0)) for r in ledger if r.get("value")]
        if not scores:
            return 1, "No redirect rubric data."

        avg = sum(scores) / len(scores)
        # Map [-1, 1] → [0, 1] → [1, 10]
        spirit_score = int(round((avg + 1) / 2 * 9 + 1))
        spirit_score = max(1, min(10, spirit_score))
        note = f"Redirect quality {spirit_score}/10 ({len(scores)} rubrics; spirit memory unchanged)."
        return spirit_score, note

# ── The Coach: the Spirit's feedback path ────────────────────────────────────
# Merged from safi_app/core/feedback.py on 2026-08-13 (backlog 35): the coaching
# note is the Spirit's OUTPUT function, not a separate mechanism, and a lone
# feedback.py invited exactly that misreading. The paper formalizes this as
# f_t = Coach(h_t), consumed by the next turn's Intellect call. Deterministic —
# arithmetic over the memory vector, the drift measure and the last profile;
# no model call, which is what keeps the corrective path as reproducible as the
# enforcement path.

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
    """
    Build a BLIND coaching nudge injected into each Intellect call.

    AUDIT-INDEPENDENCE CONTRACT: this note must never leak the grading criteria.
    The Conscience (a different model) scores responses against rubrics; if the
    Intellect could see those rubrics it would optimise toward them and the audit
    would become circular (Goodhart). So this note carries ONLY:

        1. a qualitative drift / trend signal ("trended below your usual standard"), and
        2. at most the *name* of the single dimension most worth attention.

    It deliberately excludes rubrics, scoring guides, per-value descriptions,
    weights, and numeric scores. Value *names* are acceptable because they already
    exist in the worldview as the agent's declared identity — naming one adds no
    new test information. `value_descriptions` is accepted for signature
    compatibility and is intentionally ignored.

    Returns "" when there is nothing to flag, so on-track turns stay fully blind.
    """
    if mu is None or len(mu) == 0 or not value_names:
        return ""

    weights = [float(w or 0.0) for w in (value_weights or [1.0] * len(mu))]
    # Active = scored values only (exclude weight-0 sentinels like Scope Compliance),
    # and only indices valid across every parallel array.
    n = min(len(mu), len(weights), len(value_names))
    active = [i for i in range(n) if weights[i] > 0.0] or list(range(n))

    # Cold start: no accumulated memory and no scored turn yet -> stay fully blind.
    has_memory = any(abs(float(mu[i])) > 1e-6 for i in active) or (last_pt is not None)
    if not has_memory:
        return ""

    def wavg(vec) -> float:
        den = sum(weights[i] for i in active) or 1.0
        return sum(weights[i] * float(vec[i]) for i in active if i < len(vec)) / den

    baseline = wavg(mu)                                    # historical alignment level
    turn_level = wavg(last_pt) if last_pt is not None else None
    decline = (baseline - turn_level) if turn_level is not None else 0.0

    a, b, c = drift_bands
    d = drift or 0.0

    # Only coach when something is actually off — otherwise emit nothing.
    if not (d >= a or decline > 0.05 or baseline < 0.50):
        return ""

    # Severity is qualitative only — never numbers.
    if d >= c or decline > 0.20 or baseline < 0.30:
        verb = "have fallen well below your usual standard"
        close = "Be markedly more deliberate, complete, and precise this turn."
    elif d >= b or decline > 0.10 or baseline < 0.45:
        verb = "have trended below your usual standard"
        close = "Be more deliberate and thorough this turn."
    else:
        verb = "have slipped slightly from your usual standard"
        close = "Stay deliberate and consistent this turn."

    # Headline dimension — NAME ONLY (no score, weight, or description).
    def attention(i: int) -> float:
        if last_pt is not None and i < len(last_pt):
            return weights[i] * max(0.0, float(mu[i]) - float(last_pt[i]))  # weighted drop this turn
        return weights[i] * max(0.0, 0.65 - float(mu[i]))                   # weighted gap from "good"

    ranked = sorted(active, key=attention, reverse=True)
    name_clause = ""
    if ranked and attention(ranked[0]) > 0.03:
        name_clause = f", most notably around {value_names[ranked[0]]}"

    return f"Self-check: your recent responses {verb}{name_clause}. {close}"
