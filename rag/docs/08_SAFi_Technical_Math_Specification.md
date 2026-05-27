---
title: SAFi Explained: The Formal Mathematical Specification
slug: technical-math-specification
tags: ["safi", "reference", "math", "specification"]
summary: Formal mathematical and technical specification for SAFi: objects, six-phase pipeline, Spirit EMA and drift formulas, Will gate logic, and synchronous pseudocode.
version: 2.0
---

# SAFi Explained: The Formal Mathematical Specification

## Purpose
This document provides the formal specification for the Self Alignment Framework Interface (SAFi). It defines the mathematical objects, data flow, timing model, formulas, and pseudocode that implement the system. All phases run synchronously within a single request.

## Core mathematical objects

- t: the discrete interaction index (turn number)
- x_t: the user input at turn t
- V = {(v_i, w_i)}: the declared set of values with non-negative weights summing to 1.0
- a_t: the draft answer produced by the Intellect
- r_t: the Intellect's internal rationale for the draft
- D_t: the Will's gate decision (approve or block)
- L_t: the Conscience ledger; for each value v_i, a triple (s_i, c_i, q_i) where s_i ∈ [−1, 1] is the score, c_i ∈ [0, 1] is confidence, and q_i is the text rationale
- S_t: the Spirit coherence score for turn t, scaled to [1, 10]
- p_t: the alignment profile vector for turn t (element-wise weights × scores)
- μ_t: the long-term memory vector (exponential moving average of profile vectors)
- d_t: the cosine-distance drift measure for turn t
- β: the EMA smoothing factor (default 0.9)

## Synderesis layer
Before any interaction, the Synderesis layer compiles the persona configuration: value set V with weights, scope statement, will rules, and rubrics. This configuration is read-only after deployment. No faculty can modify it at runtime.

## System timing model
All six phases run synchronously within a single request. The user does not receive a response until Phase 6 completes.

Phase 0 → Phase 1 → Phase 2 → Phase 3 (→ Reflexion Loop if blocked) → Phase 4 → Phase 4.5 (Hard Gate) → Phase 5 → Phase 6

## Spirit formulas

### Step 1: Spirit score
S_t = clip( Σ wᵢ · sᵢ · cᵢ, −1, 1 ) rescaled linearly to [1, 10]

Where wᵢ are the value weights from V, sᵢ are the Conscience scores, and cᵢ are the confidence values.

### Step 2: Alignment profile
p_t = w ⊙ s_t

The element-wise product of the weight vector w and the score vector s_t for this turn. This is the ethical fingerprint of the current response.

### Step 3: Long-term memory (EMA)
μ_t = β · μ_{t-1} + (1 − β) · p_t

Where β = 0.9. This exponential moving average accumulates the agent's ethical history. Recent turns have more influence; older turns decay but are never forgotten entirely.

### Step 4: Behavioral drift
d_t = 1 − cos_sim(p_t, μ_{t-1})

The cosine distance between the current turn's alignment profile and the historical baseline. A drift of 0 means the response was fully consistent with the agent's established character. A drift near 1 means the response was a strong outlier.

### Python implementation (from spirit.py)
```python
p_t    = self.value_weights * scores           # alignment profile vector
mu_new = self.beta * mu_prev + (1 - self.beta) * p_t   # EMA update
drift  = 1.0 - float(
    np.dot(p_t, mu_prev) /
    (np.linalg.norm(p_t) * np.linalg.norm(mu_prev))
)  # cosine drift
```

## Six-phase pseudocode
```python
# Phase 0: Pre-generation gate
if phase_zero_gate(x_t, persona.blacklists):
    return safe_refusal("Blocked before generation.")

# Phase 1: Data gathering
context = gather_rag_and_plugins(x_t)

# Phase 2: Apprehension (Intellect — air-gapped from execution)
a_t, r_t = Intellect(x_t, context, V, M_t, spirit_coaching)

# Phase 3: Structural Will gate (deterministic Python, zero LLM)
decision, reason = Will.structural_check(x_t, a_t, persona.will_rules)
if decision == "block":
    # Reflexion Loop: governed rewrite
    a_t, r_t = Intellect.rewrite(x_t, context, V, M_t, reason)
    decision, reason = Will.structural_check(x_t, a_t, persona.will_rules)
    if decision == "block":
        return safe_refusal(reason)

# Phase 4: Conscience audit (synchronous — user waits for this)
L_t = Conscience(a_t, x_t, V)

# Phase 4.5: Hard gate on Conscience ledger
if L_t["scope_compliance"].score == -1.0:
    return governed_rephrase(x_t, V)

# Phase 5: Spirit integration (no LLM — pure Python/NumPy)
S_t, mu_t, d_t, coaching = Spirit.integrate(L_t, mu_prev, V)

# Phase 6: Safe execution — log and deliver
log_full_audit(x_t, a_t, r_t, decision, L_t, S_t, d_t, mu_t)
return a_t
```

## Cross references
- 02 Faculties Intellect
- 03 Faculties Will
- 04 Faculties Conscience
- 05 Faculties Spirit
- 23 SAFi Synderesis
- 10 SAFi Technical Workflow
