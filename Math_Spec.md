SAFi Formal Specification

Core Objects
 * t: discrete interaction index (the turn number)
 * x_t: input context (prompt, metadata)
 * V = {(v_i, w_i)}: declared value set with weights, ∑ w_i = 1
 * a_t: draft action or answer
 * D_t ∈ {approve, violation}: Will’s gate decision
 * E_t: Will’s reason string
 * L_t = {(v_i, s_{i,t}, c_{i,t})}: Conscience ledger per value, with score s_{i,t} ∈ {−1, 0, +1} (or scaled) and confidence c_{i,t} ∈ [0,1]
 * S_t ∈ [0,1] or [1,10]: Spirit coherence for this turn
 * M_t: memory of prior audits, profiles, and running aggregates
Timing Model
 * Intellect and Will are synchronous (user waits)
 * Conscience and Spirit are asynchronous (background jobs)
 * Memory is updated once the background audit completes
Stage 1: Intellect (sync)
 * a_t, r_t = I(x_t, V, M_t)
 * r_t is a short internal reflection used by Will
Stage 2: Will Gate (sync)
 * D_t, E_t = W(a_t, x_t, V, r_t)
If D_t = violation:
 * return safe response or escalation notice
 * record minimal event {t, x_t, a_t, D_t, E_t}
 * abort downstream stages for this turn
If D_t = approve:
 * return a_t to the user immediately
 * enqueue background audit job J_t = {t, x_t, a_t, V, M_t}
Stage 3: Conscience Audit (async)
 * For each v_i in V:
   * s_{i,t}, c_{i,t}, q_{i,t} = G_i(a_t, x_t, v_i)
 * Compose ledger: L_t = {(v_i, s_{i,t}, c_{i,t}, q_{i,t})}
 * Persist audit record with metadata
Stage 4: Spirit Aggregation and Drift (async)
 * Compute spirit score: S_t = σ( ∑ w_i · s_{i,t} · φ(c_{i,t}) )
 * Map to [1,10] if desired
 * Compute profile vector: p_t = w ⊙ s_t
 * Update moving average: μ_t = β μ_{t−1} + (1−β) p_t
 * Drift: d_t = 1 − cos_sim(p_t, μ_{t−1})
Policy hooks:
 * If S_t < τ_S → flag for review
 * If d_t > τ_d → raise drift alert
 * Write spirit summary note
Closed Loop Update (async)
 * M_{t+1} = U(M_t, L_t, S_t, μ_t, d_t)
Emit artifacts:
 * per turn: {t, D_t, E_t, L_t, S_t, d_t}
 * running: {μ_t, trend charts, drift incidents}
Type Discipline
 * I: (x_t, V, M_t) → a_t
 * W: (a_t, x_t, V, r_t) → {approve, violation}
 * C: (a_t, x_t, V) → L_t
 * S: (L_t, V, M_t) → S_t, d_t, μ_t
The synchronous chain: I → W → user
The asynchronous chain: C → S → M update
Policy and Parameters
 * Score alphabet: {Violates, Omits, Affirms, Strongly Affirms} mapped to s ∈ {−1, 0, +½, +1}
 * Confidence: c ∈ [0,1]
 * σ: scaling function (identity or logistic)
 * φ(c): function to downweight low-confidence rationales
 * β: controls memory smoothness
 * τ_S, τ_d: thresholds for alerts
Pseudocode
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

