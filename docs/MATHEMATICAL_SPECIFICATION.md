# SAFi Mathematical Specification

> **Version:** 1.0  
> **Last Updated:** 2026-01-06  
> **Status:** Aligned with code implementation

This document defines the formal mathematical foundation of SAFi's four-faculty architecture.

---

## Core Mathematical Objects

| Symbol | Description |
|--------|-------------|
| $t$ | Interaction index (turn number) |
| $x_t$ | Input context (prompt + metadata) |
| $V = \{(v_i, w_i)\}$ | Value set with weights, where $\sum w_i = 1$ |
| $a_t$ | Draft response from Intellect |
| $D_t \in \{\text{approve}, \text{violation}\}$ | Will's decision |
| $E_t$ | Will's reason string |
| $L_t = \{(v_i, s_{i,t}, c_{i,t})\}$ | Conscience ledger per value |
| $s_{i,t} \in \{-1, 0, +1\}$ | Score for value $v_i$ |
| $c_{i,t} \in [0,1]$ | Confidence for value $v_i$ |
| $S_t \in [1,10]$ | Spirit coherence score |
| $M_t$ | Memory state (prior audits, profiles, aggregates) |

---

## Timing Model

```
┌─────────────────────────────────────────────────────────────┐
│  SYNCHRONOUS (User Waits)                                   │
│  ┌─────────┐    ┌──────┐    ┌─────────────┐                │
│  │Intellect│───▶│ Will │───▶│Return to User│               │
│  └─────────┘    └──────┘    └─────────────┘                │
│       │              │                                      │
│       │         [violation]                                 │
│       │              ▼                                      │
│       │        ┌──────────┐                                 │
│       └───────▶│ Reflexion│──▶ Retry once                  │
│                └──────────┘                                 │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼ (background thread)
┌─────────────────────────────────────────────────────────────┐
│  ASYNCHRONOUS (Background)                                  │
│  ┌───────────┐    ┌────────┐    ┌───────────────┐          │
│  │ Conscience│───▶│ Spirit │───▶│ Memory Update │          │
│  └───────────┘    └────────┘    └───────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Intellect

The Intellect generates the initial response and internal reflection:

$$a_t, r_t = I(x_t, V, M_t)$$

Where:
- $a_t$ is the draft response
- $r_t$ is a short internal reflection (used for audit logging)

**Code Reference:** [`intellect.py#generate()`](safi_app/core/faculties/intellect.py)

---

## Stage 2: Will

The Will makes a binary governance decision:

$$D_t, E_t = W(a_t, x_t, V)$$

**If $D_t = \text{approve}$:**
- Return $a_t$ to the user immediately
- Enqueue background audit: $J_t = \{t, x_t, a_t, V, M_t\}$

**If $D_t = \text{violation}$:**
- Proceed to Stage 2.1 (Reflexion Retry)

**Code Reference:** [`will.py#evaluate()`](safi_app/core/faculties/will.py)

---

## Stage 2.1: Reflexion Retry

When the Will blocks a response, the system attempts self-correction (single retry):

**Step 1:** Construct reflexion prompt incorporating violation feedback:
$$x'_t = x_t \oplus E_t$$

**Step 2:** Generate corrected draft:
$$a'_t, r'_t = I(x'_t, V, M_t)$$

**Step 3:** Re-evaluate with Will:
$$D'_t, E'_t = W(a'_t, x_t, V)$$

**If $D'_t = \text{approve}$:**
- Adopt corrected response: $a_t \leftarrow a'_t$
- Proceed to return and enqueue audit

**If $D'_t = \text{violation}$:**
- Return rejection message to user
- Record event: $\{t, x_t, a_t, a'_t, D_t, E_t, D'_t, E'_t\}$
- Abort downstream stages

**Code Reference:** [`orchestrator.py#L339-393`](safi_app/core/orchestrator.py)

---

## Stage 3: Conscience

For each value $v_i$ in $V$, the Conscience evaluates alignment:

$$s_{i,t}, c_{i,t} = G_i(a_t, x_t, v_i)$$

The complete ledger is composed as:

$$L_t = \{(v_i, s_{i,t}, c_{i,t})\}$$

**Code Reference:** [`conscience.py#evaluate()`](safi_app/core/faculties/conscience.py)

---

## Stage 4: Spirit

### Spirit Score Computation

$$S_t = \sigma\left(\sum w_i \cdot s_{i,t} \cdot \varphi(c_{i,t})\right)$$

Where:
- $\sigma(x)$ scales the result to $[1, 10]$
- $\varphi(c) = c$ (identity function; confidence as direct multiplier)

### Profile Vector

$$p_t = w \odot s_t$$

### Exponential Moving Average (EMA)

$$\mu_t = \beta \mu_{t-1} + (1-\beta) p_t$$

Where $\beta = 0.9$ by default (configurable via `SPIRIT_BETA`).

### Drift Calculation

$$d_t = 1 - \cos_{\text{sim}}(p_t, \mu_{t-1})$$

### Memory Update

$$M_{t+1} = U(M_t, L_t, S_t, \mu_t, d_t)$$

### Feedback to Intellect

A natural-language coaching note $f_t$ is generated from $S_t$ and $d_t$ to steer the next turn.

**Code Reference:** [`spirit.py#compute()`](safi_app/core/faculties/spirit.py)

---

## Type System

| Faculty | Signature |
|---------|-----------|
| Intellect | $I: (x_t, V, M_t) \rightarrow (a_t, r_t)$ |
| Will | $W: (a_t, x_t, V) \rightarrow (D_t, E_t)$ |
| Conscience | $C: (a_t, x_t, V) \rightarrow L_t$ |
| Spirit | $S: (L_t, V, M_t) \rightarrow (S_t, d_t, \mu_t)$ |

---

## Implementation Notes

1. **φ(c) Choice:** The downweighting function $\varphi$ is implemented as identity. Future versions may use $\varphi(c) = c^2$ to penalize low-confidence scores.

2. **σ Scaling:** Spirit score is mapped from $[-1, 1] \rightarrow [1, 10]$ via linear transformation.

3. **Reflexion Limit:** Only one retry is attempted to prevent infinite loops.

4. **Memory Format:** $\mu$ is stored as a semantic dictionary (value name → float) for robustness across value set changes.
