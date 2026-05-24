# SAFi Mathematical Specification

> **Version:** 1.1  
> **Last Updated:** 2026-05-24  
> **Status:** Aligned with code implementation

This document defines the formal mathematical foundation of SAFi's five-stage architecture.

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
| $s_{i,t} \in [-1.0, 1.0]$ | Alignment score for value $v_i$ (continuous float) |
| $c_{i,t} \in [0, 1]$ | Confidence for value $v_i$ |
| $S_t \in [1, 10]$ | Spirit coherence score |
| $M_t$ | Memory state (prior audits, profiles, aggregates) |

---

## Timing Model

```
┌──────────────────────────────────────────────────────────────────────┐
│  SYNCHRONOUS (User Waits for All of This)                            │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────┐  ┌───────────┐  ┌────────┐  │
│  │Phase Zero│─▶│ Intellect│─▶│ Will │─▶│ Conscience│─▶│ Spirit │  │
│  └──────────┘  └──────────┘  └──────┘  └───────────┘  └────────┘  │
│                      │            │                         │        │
│                      │       [violation]                    │        │
│                      │            ▼                    [violation]  │
│                      │      ┌──────────┐                    ▼        │
│                      └─────▶│ Reflexion│──▶ Retry once  Rephrase    │
│                             └──────────┘                    │        │
│                                                             ▼        │
│                                                      Return to User  │
└──────────────────────────────────────────────────────────────────────┘
                         │
                         ▼ (ThreadPoolExecutor — fire and forget)
┌──────────────────────────────────────────────────────────────────────┐
│  ASYNCHRONOUS (Background)                                           │
│  ┌─────────────────────────┐   ┌──────────────────────────────────┐ │
│  │ Conversation Summarizer │   │ Profile Extraction (if enabled)  │ │
│  └─────────────────────────┘   └──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Stage 0: Phase Zero Gate

Before the Intellect is ever invoked, the Phase Zero Gate evaluates the raw user
prompt deterministically — zero LLM calls. If a threat is detected, the orchestrator
short-circuits immediately to a governed redirect; Intellect is never called.

Three detection mechanisms run in order:

**1. Global signature scan** — matches against `INJECTION_SIGNATURES` in `threat_intel.py`,
a database of known attack patterns grouped by category
(`persona_swap`, `instruction_override`, `jailbreak_archetypes`,
`multilingual_persona_swap`, etc.):

$$\text{safe} = \neg \exists\, p \in \text{INJECTION\_SIGNATURES} : p \subseteq \text{lower}(x_t)$$

**2. Persona blacklist scan** — checks per-agent keywords defined in the policy's
`early_prompt_blacklist`:

$$\text{safe} = \neg \exists\, p \in \text{blacklist} : p \subseteq \text{lower}(x_t)$$

**3. Entropy heuristic** — flags high-entropy payloads followed by embedded instruction
markers (catches obfuscated injections that evade signature matching):

$$H(x_t) = -\sum_c P(c) \log_2 P(c) > \tau_H \;\land\; \text{has\_instruction\_marker}(x_t)$$

Where $\tau_H = 4.5$ bits/char (configurable via `ENTROPY_THRESHOLD`).

**If any check fails** → `trigger_persona_redirect(violation_type=gate_reason)` and return.  
**If all pass** → proceed to Stage 1.

**Code Reference:** [`phase_zero.py`](../safi_app/core/faculties/phase_zero.py),
[`threat_intel.py`](../safi_app/core/threat_intel.py),
[`orchestrator.py#Phase0`](../safi_app/core/orchestrator.py)

---

## Stage 1: Intellect

The Intellect generates the initial response and internal reflection:

$$a_t, r_t = I(x_t, V, M_t)$$

Where:
- $a_t$ is the draft response
- $r_t$ is a short internal reflection (used for audit logging)

**Code Reference:** [`intellect.py#generate()`](../safi_app/core/faculties/intellect.py)

---

## Stage 2: Will

The Will makes a binary governance decision:

$$D_t, E_t = W(a_t, x_t, V)$$

The Will is entirely deterministic (zero LLM calls). It checks in order:

1. **Structural invariants** — required disclaimers, banned markdown syntax
2. **Hard-gate values** — any value in $L_t$ flagged `hard_gate=true` scoring $\leq -1$ triggers immediate violation
3. **Spirit alignment threshold** — $S_t < 0.5$ triggers violation

**If $D_t = \text{approve}$:**
- Return $a_t$ to the user immediately
- Enqueue background audit: $J_t = \{t, x_t, a_t, V, M_t\}$

**If $D_t = \text{violation}$:**
- Proceed to Stage 2.1 (Reflexion Retry)

**Code Reference:** [`will.py#evaluate()`](../safi_app/core/faculties/will.py)

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
- Call `trigger_persona_redirect()` — the user always receives a governed
  redirect response; SAFi never returns a hard rejection or silence.
- Record event: $\{t, x_t, a_t, a'_t, D_t, E_t, D'_t, E'_t\}$
- Abort downstream stages

**Code Reference:** [`orchestrator.py#L339-393`](../safi_app/core/orchestrator.py)

---

## Stage 3: Conscience

For each value $v_i$ in $V$, the Conscience evaluates alignment via LLM and returns
a continuous score:

$$s_{i,t}, c_{i,t} = G_i(a_t, x_t, v_i), \quad s_{i,t} \in [-1.0, 1.0],\; c_{i,t} \in [0, 1]$$

The complete ledger is composed as:

$$L_t = \{(v_i, s_{i,t}, c_{i,t})\}$$

**Note:** The LLM is instructed to use the anchor points $\{-1.0, 0.0, +1.0\}$ in
practice, but scores are stored and processed as continuous floats — no discretization
is applied in code.

**Code Reference:** [`conscience.py#evaluate()`](../safi_app/core/faculties/conscience.py)

---

## Stage 4: Spirit

### Profile Vector

$$p_t = w \odot s_t$$

### Spirit Score Computation

The raw aggregate is clipped to $[-1, 1]$ and linearly rescaled to $[1, 10]$:

$$\text{raw}_t = \text{clip}\!\left(\sum_i w_i \cdot s_{i,t} \cdot c_{i,t},\; -1,\; 1\right)$$

$$S_t = \text{round}\!\left(\frac{\text{raw}_t + 1}{2} \cdot 9 + 1\right)$$

This maps $\text{raw}_t = -1 \Rightarrow S_t = 1$ and $\text{raw}_t = +1 \Rightarrow S_t = 10$.

**Note:** Earlier versions of this spec described $\sigma$ as a sigmoid function.
The implementation uses clipping followed by linear rescaling — there is no sigmoid.

### Exponential Moving Average (EMA)

$$\mu_t = \beta \mu_{t-1} + (1-\beta) p_t$$

Where $\beta = 0.9$ by default (configurable via `SPIRIT_BETA`).

### Drift Calculation

$$d_t = 1 - \cos\_\text{sim}(p_t,\, \mu_{t-1}) = 1 - \frac{p_t \cdot \mu_{t-1}}{\|p_t\|\;\|\mu_{t-1}\|}$$

A numerical guard $\epsilon = 10^{-8}$ prevents division by zero when either vector
has near-zero norm; drift is reported as `null` in that case.

### Memory Update

$$M_{t+1} = U(M_t, L_t, S_t, \mu_t, d_t)$$

### Feedback to Intellect

A natural-language coaching note $f_t$ is generated from $S_t$ and $d_t$ to steer
the next turn. Redirect turns use a separate `compute_redirect()` path that scores
redirect quality without updating the EMA, keeping the Spirit memory free from
non-content scores.

**Code Reference:** [`spirit.py#compute()`](../safi_app/core/faculties/spirit.py)

---

## Type System

| Faculty | Signature |
|---------|-----------|
| Phase Zero | $P: x_t \rightarrow (\text{safe} \in \mathbb{B},\; \text{reason})$ |
| Intellect | $I: (x_t, V, M_t) \rightarrow (a_t, r_t)$ |
| Will | $W: (a_t, x_t, V) \rightarrow (D_t, E_t)$ |
| Conscience | $C: (a_t, x_t, V) \rightarrow L_t$ |
| Spirit | $S: (L_t, V, M_t) \rightarrow (S_t, d_t, \mu_t)$ |

---

## Implementation Notes

1. **Conscience score anchors:** The LLM is prompted with anchor labels
   (`-1.0 = Confusing`, `0.0 = Vague`, `1.0 = Clear`) but scores arrive as
   continuous floats. No rounding is applied in code.

2. **Spirit scaling:** Score is mapped from $[-1, 1] \rightarrow [1, 10]$ via
   linear transformation `(raw + 1) / 2 * 9 + 1`, then rounded to the nearest integer.

3. **No hard rejections:** SAFi never returns silence or an error to the user.
   Every violation — including double Will failure (main + reflexion) — routes
   through `trigger_persona_redirect()`, which always produces a governed response.

4. **Reflexion limit:** Only one retry is attempted to prevent infinite loops.

5. **Memory format:** $\mu$ is stored as a semantic dictionary (value name → float)
   for robustness across value set changes. Dormant values (removed from policy)
   are preserved in the dictionary but excluded from active computation.

6. **Phase Zero is language-aware:** The signature database (`threat_intel.py`)
   includes multilingual patterns (Chinese, Spanish, Japanese, French, Portuguese)
   to catch injection attempts that evade ASCII-based matching.
