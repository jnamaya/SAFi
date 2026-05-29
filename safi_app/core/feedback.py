from typing import List, Optional
import numpy as np


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
