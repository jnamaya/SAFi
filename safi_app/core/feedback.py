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
    Build a structured, actionable coaching note injected into each Intellect call.

    Improvements over v1:
    - Zero-weight sentinels (e.g. Scope Compliance) excluded from all analysis.
    - All below-threshold values reported, tiered as critical / needs-work, not
      just the single worst.
    - Values sorted by weight × gap so high-importance drops get top billing.
    - Per-value descriptions included as prescriptive directives.
    - last_pt (this turn's raw scores) compared to mu (historical average) so
      the model learns whether it just dropped on a specific value vs. a chronic
      pattern.
    - Drift attributed to the specific values that moved most, not just a label.
    - Stable-but-low distinguished from sudden-drop via trend slope.
    """
    assert len(mu) == len(value_names) and len(mu) > 0, "mu and value_names must align"

    weights = [float(w or 0.0) for w in (value_weights or [1.0] * len(mu))]
    descs   = list(value_descriptions or [""] * len(mu))

    # --- Exclude zero-weight sentinel values (e.g. injected Scope Compliance) ---
    active = [i for i, w in enumerate(weights) if w > 0.0]
    if not active:
        active = list(range(len(mu)))  # fallback: shouldn't happen

    # --- Trend slope helper (operates on global index) ---
    def slope_for(idx: int) -> Optional[float]:
        if not recent_mu or len(recent_mu) < 2:
            return None
        window = [m for m in recent_mu[-trend_window:] if idx < len(m)]
        if len(window) < 2:
            return None
        series = np.array([float(m[idx]) for m in window])
        x = np.arange(len(series), dtype=float)
        slope, _ = np.polyfit(x, series, 1)
        return float(slope)

    # --- Score tier label ---
    def tier(s: float) -> str:
        if s < 0.25: return "critical"
        if s < 0.45: return "low"
        if s < 0.65: return "moderate"
        if s < 0.80: return "good"
        return "strong"

    # --- Truncate description for conciseness ---
    def short_desc(i: int) -> str:
        d = descs[i].strip() if i < len(descs) else ""
        if not d:
            return ""
        if len(d) <= 110:
            return d
        return d[:110].rsplit(" ", 1)[0] + "..."

    # --- Build per-value records ---
    records = []
    for i in active:
        score  = float(mu[i])
        w      = weights[i]
        slope  = slope_for(i)

        this_turn = float(last_pt[i]) if (last_pt is not None and i < len(last_pt)) else None
        # Significant this-turn change: >0.12 delta
        dropped  = this_turn is not None and (score - this_turn) > 0.12
        improved = this_turn is not None and (this_turn - score) > 0.12

        trending_down = slope is not None and slope < -0.02
        trending_up   = slope is not None and slope > 0.02

        # Priority = weight × gap from "good" floor (0.65).
        # Boost by extra gap when this turn dropped below the average.
        gap = max(0.0, 0.65 - score)
        if dropped and this_turn is not None:
            gap = max(gap, score - this_turn)
        priority = w * gap

        records.append({
            "i":            i,
            "name":         value_names[i],
            "score":        score,
            "weight":       w,
            "desc":         short_desc(i),
            "this_turn":    this_turn,
            "dropped":      dropped,
            "improved":     improved,
            "trending_down": trending_down,
            "trending_up":  trending_up,
            "priority":     priority,
            "tier":         tier(score),
        })

    # --- Drift tier and attribution ---
    a, b, c  = drift_bands
    drift    = drift or 0.0
    if drift < a:       drift_tier = "none"
    elif drift < b:     drift_tier = "slight"
    elif drift < c:     drift_tier = "moderate"
    else:               drift_tier = "high"

    drift_drivers: List[str] = []
    if drift_tier in ("moderate", "high") and last_pt is not None:
        devs = []
        for r in records:
            i = r["i"]
            if i < len(last_pt):
                dev = abs(float(last_pt[i]) - float(mu[i])) * r["weight"]
                devs.append((dev, r["name"]))
        devs.sort(reverse=True)
        drift_drivers = [name for dev, name in devs[:2] if dev > 0.03]

    # --- Categorise active values ---
    # Critical: score < 0.30, OR dropped hard this turn to below 0.30
    critical   = sorted(
        [r for r in records if r["score"] < 0.30
         or (r["dropped"] and r["this_turn"] is not None and r["this_turn"] < 0.30)],
        key=lambda r: -r["priority"]
    )
    needs_work = sorted(
        [r for r in records if 0.30 <= r["score"] < 0.50 and r not in critical],
        key=lambda r: -r["priority"]
    )
    # Good historically but dropped significantly this turn
    watch = [r for r in records
             if r["dropped"] and r["score"] >= 0.50 and r not in critical]
    strong = sorted(
        [r for r in records if r["score"] >= 0.70],
        key=lambda r: -r["score"]
    )
    improved_vals = [r for r in records if r["improved"]]

    # --- Assemble coaching lines ---
    lines: List[str] = []

    # 1. Overall snapshot
    avg = float(np.mean([r["score"] for r in records]))
    if avg >= 0.70:
        lines.append(f"Overall alignment: strong ({avg:.2f}).")
    elif avg >= 0.50:
        lines.append(f"Overall alignment: moderate ({avg:.2f}) — focus on the areas below.")
    else:
        lines.append(f"Overall alignment: low ({avg:.2f}) — significant improvement needed this turn.")

    # 2. Drift
    if drift_tier in ("moderate", "high"):
        msg = f"Alignment drift: {drift_tier} ({drift:.2f})"
        if drift_drivers:
            msg += f", driven mainly by '{drift_drivers[0]}'"
            if len(drift_drivers) > 1:
                msg += f" and '{drift_drivers[1]}'"
        msg += ". Recalibrate this turn."
        lines.append(msg)
    elif drift_tier == "slight":
        lines.append(f"Slight drift detected ({drift:.2f}) — monitor consistency.")

    # 3. Critical values
    if critical:
        lines.append("CRITICAL — must address this turn:")
        for r in critical[:3]:
            line = f"  • {r['name']} ({r['score']:.2f})"
            if r["dropped"] and r["this_turn"] is not None:
                line += f" [dropped to {r['this_turn']:.2f} last turn, avg {r['score']:.2f}]"
            elif r["trending_down"]:
                line += " [consistently declining]"
            if r["desc"]:
                line += f" — {r['desc']}"
            lines.append(line)

    # 4. Needs-work values (cap at 3 to keep prompt size manageable)
    if needs_work:
        lines.append("Needs improvement:")
        for r in needs_work[:3]:
            line = f"  • {r['name']} ({r['score']:.2f} - {r['tier']})"
            if r["trending_down"]:
                line += " [trending down]"
            elif r["trending_up"]:
                line += " [improving]"
            if r["desc"]:
                line += f" — {r['desc']}"
            lines.append(line)

    # 5. Surprising this-turn drops on otherwise good values
    if watch:
        entries = [
            f"'{r['name']}' ({r['this_turn']:.2f} vs avg {r['score']:.2f})"
            for r in watch[:2]
        ]
        lines.append(f"Dropped this turn: {', '.join(entries)} — review your last response.")

    # 6. Strengths (brief — max 2)
    if strong:
        names = [f"'{r['name']}'" for r in strong[:2]]
        lines.append(f"Strengths: {', '.join(names)} — maintain.")

    # 7. Improvements worth noting
    if improved_vals:
        names = [f"'{r['name']}'" for r in improved_vals[:2]]
        lines.append(f"Improved this turn: {', '.join(names)} — good progress, keep it up.")

    # Clean exit when everything is healthy
    if len(lines) == 1 and "strong" in lines[0]:
        return "Alignment is strong across all values. Maintain current performance."

    return "\n".join(lines)
