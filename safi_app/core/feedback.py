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
    Create a compact, structured coach note for Intellect.
    Inputs are pure numbers. No model calls.
    
    mu           current spirit memory vector, shape [V]
    value_names  names for each dimension in mu
    drift        cosine distance 0..2, typical 0..1
    recent_mu    optional list of prior mu vectors, oldest first
    drift_bands  thresholds for labeling drift
    trend_window how many recent points to check per value
    """
    assert len(mu) == len(value_names) and len(mu) > 0, "mu and value_names must align"

    # pick strongest and weakest dimensions
    top_i  = int(np.argmax(mu))
    low_i  = int(np.argmin(mu))
    top_nm, low_nm = value_names[top_i], value_names[low_i]
    top_sc, low_sc = float(mu[top_i]), float(mu[low_i])

    # label drift
    a, b, c = drift_bands
    if drift < a:
        drift_label = "none"
    elif drift < b:
        drift_label = "slight"
    elif drift < c:
        drift_label = "moderate"
    else:
        drift_label = "high"

    # simple trend detection for top and low values
    def slope_for(idx: int) -> Optional[float]:
        if not recent_mu or len(recent_mu) < trend_window:
            return None
        # Ensure we only use the most recent items up to the window size
        series = np.array([m[idx] for m in recent_mu[-trend_window:]], dtype=float)
        if series.size < 2: # Need at least 2 points to fit a line
            return None
        # fit line y = m*x + c on x = 0..n-1, slope m
        x = np.arange(series.size, dtype=float)
        m, _ = np.polyfit(x, series, 1)
        return float(m)

    top_slope = slope_for(top_i)
    low_slope = slope_for(low_i)

    # turn slopes into short labels
    def trend_label(s: Optional[float], tol: float = 1e-3) -> Optional[str]:
        if s is None:
            return None
        if s >  tol:
            return "rising"
        if s < -tol:
            return "falling"
        return "flat"

    top_tr = trend_label(top_slope)
    low_tr = trend_label(low_slope)

    # build a stable scoreboard line for the model and for logs
    header = (
        f"Spirit state, Top={top_nm}({top_sc:.2f}), "
        f"Low={low_nm}({low_sc:.2f}), Drift={drift:.2f}({drift_label})"
    )

    # human friendly nudge
    parts = []
    if top_sc > 0.1: # Only report on strength if it's meaningfully positive
        parts.append(f"You are strong on {top_nm}")
        if top_tr:
            parts.append(f"which is {top_tr}")
    
    if low_sc < 0.5: # Only suggest focus if the score is not already high
        parts.append(f"Focus more on {low_nm}")
        if low_tr:
            parts.append(f"which is {low_tr}")

    if drift_label in {"moderate", "high"}:
        parts.append("Correct course this turn")

    # Join with different separators for better readability
    note = ". ".join(p.strip() for p in parts)
    if note:
        note = note.strip() + "."

    # final output, two lines, consistent format
    return f"{header}\nFeedback: {note}"
