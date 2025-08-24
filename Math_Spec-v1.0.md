# SAFi Formal Specification

## Core Objects

  * **t**: discrete interaction index (the turn number)
  * **x\_t**: input context (prompt, metadata)
  * **V = {(v\_i, w\_i)}**: declared value set with weights, ∑ w\_i = 1
  * **a\_t**: draft action or answer
  * **D\_t ∈ {approve, violation}**: Will’s gate decision
  * **E\_t**: Will’s reason string
  * **L\_t = {(v\_i, s\_{i,t}, c\_{i,t})}**: Conscience ledger per value, with score s\_{i,t} ∈ {−1, 0, +1} (or scaled) and confidence c\_{i,t} ∈ [0,1]
  * **S\_t ∈ [0,1] or [1,10]**: Spirit coherence for this turn
  * **M\_t**: memory of prior audits, profiles, and running aggregates


## Timing Model

  * **Intellect** and **Will** are synchronous (user waits)
  * **Conscience** and **Spirit** are asynchronous (background jobs)
  * Memory is updated once the background audit completes


## Stage 1: Intellect (sync)

  * a\_t, r\_t = I(x\_t, V, M\_t)
  * *r\_t is a short internal reflection used by Will*


## Stage 2: Will Gate (sync)

  * D\_t, E\_t = W(a\_t, x\_t, V, r\_t)

### If D\_t = violation:

  * return safe response or escalation notice
  * record minimal event {t, x\_t, a\_t, D\_t, E\_t}
  * abort downstream stages for this turn

### If D\_t = approve:

  * return a\_t to the user immediately
  * enqueue background audit job J\_t = {t, x\_t, a\_t, V, M\_t}


## Stage 3: Conscience Audit (async)

  * For each v\_i in V:
      * s\_{i,t}, c\_{i,t}, q\_{i,t} = G\_i(a\_t, x\_t, v\_i)
  * Compose ledger: L\_t = {(v\_i, s\_{i,t}, c\_{i,t}, q\_{i,t})}
  * Persist audit record with metadata


## Stage 4: Spirit Aggregation and Drift (async)

  * Compute spirit score: S\_t = σ( ∑ w\_i · s\_{i,t} · φ(c\_{i,t}) )
  * Map to [1,10] if desired
  * Compute profile vector: p\_t = w ⊙ s\_t
  * Update moving average: μ\_t = β μ\_{t−1} + (1−β) p\_t
  * Drift: d\_t = 1 − cos\_sim(p\_t, μ\_{t−1})

### Policy hooks:

  * If S\_t \< τ\_S → flag for review
  * If d\_t \> τ\_d → raise drift alert
  * Write spirit summary note


## Closed Loop Update (async)

  * M\_{t+1} = U(M\_t, L\_t, S\_t, μ\_t, d\_t)

### Emit artifacts:

  * **per turn**: {t, D\_t, E\_t, L\_t, S\_t, d\_t}
  * **running**: {μ\_t, trend charts, drift incidents}

## Type Discipline

  * **I**: (x\_t, V, M\_t) → a\_t
  * **W**: (a\_t, x\_t, V, r\_t) → {approve, violation}
  * **C**: (a\_t, x\_t, V) → L\_t
  * **S**: (L\_t, V, M\_t) → S\_t, d\_t, μ\_t

The **synchronous chain**: I → W → user
The **asynchronous chain**: C → S → M update


## Policy and Parameters

  * **Score alphabet**: {Violates, Omits, Affirms, Strongly Affirms} mapped to s ∈ {−1, 0, +½, +1}
  * **Confidence**: c ∈ [0,1]
  * **σ**: scaling function (identity or logistic)
  * **φ(c)**: function to downweight low-confidence rationales
  * **β**: controls memory smoothness
  * **τ\_S, τ\_d**: thresholds for alerts


## Pseudocode

```python
# sync path
a, r = I(x_t, V, M_t)
D, E = W(a, x_t, V, r)

if D == "violation":
    return safe_reply(E)
    log({t, x_t, a, D, E})
else:
    return a  # user sees answer now
    enqueue_audit_job({t, x_t, a, V, M_t})

# async audit worker
def run_audit(job):
    L = []
    for v_i, w_i in V:
        s_i, c_i, q_i = G_i(job.a, job.x, v_i)
        L.append((v_i, s_i, c_i, q_i))

    S = spirit_score(L, V)
    p = weighted_vector(L, V)        # w ⊙ s
    mu_new = beta * M.mu + (1-beta) * p
    d = 1 - cos_sim(p, M.mu)

    store_audit(t=job.t, ledger=L, spirit=S, drift=d)

    if S < τ_S or d > τ_d:
        raise_alert(t=job.t, reasons=top_offending_values(L), S=S, d=d)

    M.mu = mu_new
    M = update_memory(M, L, S, d)
```

