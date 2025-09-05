from typing import List, Optional
import numpy as np

def build_spirit_feedback(
    mu: np.ndarray,
    value_names: List[str],
    drift: float,
    recent_mu: Optional[List[np.ndarray]] = None,
    drift_bands = (0.10, 0.20, 0.40),   # none, slight, moderate, high
    trend_window: int = 3
) -> str:
    """
    Create a compact, conversational coaching note for the Intellect model.
    This version avoids jargon and provides clear, actionable feedback.
    """
    assert len(mu) == len(value_names) and len(mu) > 0, "mu and value_names must align"

    top_i  = int(np.argmax(mu))
    low_i  = int(np.argmin(mu))
    top_nm, low_nm = value_names[top_i], value_names[low_i]
    
    a, b, c = drift_bands
    if drift < a: drift_label = "none"
    elif drift < b: drift_label = "slight"
    elif drift < c: drift_label = "moderate"
    else: drift_label = "high"

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

    # --- CHANGE: Construct a single, conversational paragraph ---
    # We build the feedback as a list of phrases and then join them together
    # to form a natural-sounding coaching note.
    parts = []
    
    # Add a sentence about the AI's core strength.
    if mu[top_i] > 0.1: # Only report if the strength is meaningful
        strength_part = f"Your core strength is '{top_nm}' ({mu[top_i]:.2f})"
        if top_tr:
            strength_part += f" {top_tr}"
        parts.append(strength_part)

    # Add a sentence about the area for improvement.
    if mu[low_i] < 0.5: # Only suggest focus if the score isn't already high
        improvement_part = f"your main area for improvement is '{low_nm}' ({mu[low_i]:.2f})"
        if low_tr:
            improvement_part += f" {low_tr}"
        parts.append(improvement_part)

    # Add a final, direct instruction if there was significant drift.
    if drift_label in {"moderate", "high"}:
        parts.append(f"Note: Your last response showed a {drift_label} drift from your established alignment; please correct your course this turn.")

    if not parts:
        return "Your alignment is stable and well-balanced. Maintain current performance."

    # Join the parts into a single, cohesive string.
    return ". ".join(parts) + "."

