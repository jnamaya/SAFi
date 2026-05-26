from typing import List, Optional
import numpy as np

def build_spirit_feedback(
    mu: np.ndarray,
    value_names: List[str],
    drift: float,
    recent_mu: Optional[List[np.ndarray]] = None,
    drift_bands = (0.10, 0.20, 0.40),   # none, slight, moderate, high
    trend_window: int = 3,
    value_weights: Optional[List[float]] = None
) -> str:
    """
    Create a compact, conversational coaching note for the Intellect model.
    This version avoids jargon and provides clear, actionable feedback
    with qualitative score labels.

    value_weights: when provided, values with weight <= 0 (e.g. the injected
    Scope Compliance sentinel) are excluded from the best/worst analysis so
    they never appear as coaching targets.
    """
    assert len(mu) == len(value_names) and len(mu) > 0, "mu and value_names must align"

    # Build an index list that excludes zero-weight sentinel values
    if value_weights and len(value_weights) == len(mu):
        active = [i for i, w in enumerate(value_weights) if (w or 0.0) > 0.0]
    else:
        active = list(range(len(mu)))

    # Fall back to the full array if every value somehow has zero weight
    if not active:
        active = list(range(len(mu)))

    active_mu = np.array([mu[i] for i in active])
    top_i  = active[int(np.argmax(active_mu))]
    low_i  = active[int(np.argmin(active_mu))]
    top_nm, low_nm = value_names[top_i], value_names[low_i]
    top_score, low_score = mu[top_i], mu[low_i]
    
    a, b, c = drift_bands
    if drift is None or drift < a: drift_label = "none"
    elif drift < b: drift_label = "slight"
    elif drift < c: drift_label = "moderate"
    else: drift_label = "high"

    def _score_label(score: float) -> str:
        """Helper to create qualitative labels for scores."""
        if score < 0.25: return "very low"
        if score < 0.45: return "low"
        if score < 0.65: return "good"
        if score < 0.85: return "high"
        return "excellent"

    top_label = _score_label(top_score)
    low_label = _score_label(low_score)

    def slope_for(idx: int) -> Optional[float]:
        if not recent_mu or len(recent_mu) < trend_window:
            return None
        series = np.array([m[idx] for m in recent_mu[-trend_window:]], dtype=float)
        if series.size < 2:
            return None
        x = np.arange(series.size, dtype=float)
        m, _ = np.polyfit(x, series, 1)
        return float(m)

    top_slope = slope_for(top_i)
    low_slope = slope_for(low_i)

    def trend_label(s: Optional[float], tol: float = 1e-3) -> Optional[str]:
        if s is None: return None
        if s >  tol: return "and has been rising"
        if s < -tol: return "and has been falling"
        return "and is stable"

    top_tr = trend_label(top_slope)
    low_tr = trend_label(low_slope)

    # Construct a single, conversational paragraph
    parts = []
    
    if top_score >= 0.65: # Only report if the strength is actually 'good' or better
        # --- MODIFIED LINE ---
        strength_part = f"Your core strength is '{top_nm}' (score: {top_score:.2f} - {top_label})"
        if top_tr:
            strength_part += f" {top_tr}"
        parts.append(strength_part)

    if low_score < 0.5: # Only suggest focus if the score isn't already high
        # --- MODIFIED LINE ---
        improvement_part = f"your main area for improvement is '{low_nm}' (score: {low_score:.2f} - {low_label})"
        if low_tr:
            improvement_part += f" {low_tr}"
        parts.append(improvement_part)

    if drift_label in {"moderate", "high"}:
        parts.append(f"Note: Your last response showed a {drift_label} drift from your established alignment; please correct your course this turn.")

    if not parts:
        return "Your alignment is stable and well-balanced. Maintain current performance."

    # Join the parts into a single, cohesive string.
    return ". ".join(parts) + "."