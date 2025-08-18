SAFi formal spec, current implementation

Core objects

t, discrete interaction index

x_t, input context (prompt, metadata)

V = {(v_i, w_i)}_{i=1..n}, declared value set with weights, ∑ w_i = 1

a_t, the draft action or answer

D_t ∈ {approve, violation}, Will’s gate decision

E_t, Will’s reason string

L_t = {(v_i, s_{i,t}, c_{i,t})}, Conscience ledger per value with score s_{i,t} ∈ {−1, 0, +1} (or scaled) and confidence c_{i,t} ∈ [0,1]

S_t ∈ [0,1] or [1,10], Spirit coherence for this turn

M_t, memory of prior audits, profiles, and running aggregates


Timing model

Intellect and Will are synchronous, user blocking

Conscience and Spirit are asynchronous, non blocking, logged after reply

Drift integration updates M_{t+1} when the background audit completes


Stage 1, Intellect (sync)

a_t, r_t = I(x_t, V, M_t) where r_t is a short internal reflection used by Will


Stage 2, Will gate (sync)

D_t, E_t = W(a_t, x_t, V, r_t)

If D_t = violation:

return a safe response or escalation notice to the user

record a minimal event: {t, x_t, a_t, D_t, E_t}

abort downstream stages for this turn


If D_t = approve:

return a_t to the user immediately

enqueue a background audit job J_t carrying {t, x_t, a_t, V, M_t}



Stage 3, Conscience audit (async job)

For each v_i in V: s_{i,t}, c_{i,t}, q_{i,t} = G_i(a_t, x_t, v_i) where q_{i,t} is a short rationale string

Compose the ledger: L_t = {(v_i, s_{i,t}, c_{i,t}, q_{i,t})}_{i=1..n}

Persist audit artifact: AuditRecord(t, L_t, meta = {x_t, a_t, D_t, E_t})


Stage 4, Spirit aggregation and drift (async continuation)

Instant coherence for turn t: S_t = σ( ∑i w_i · s{i,t} · φ(c_{i,t}) ) map to 1–10 if desired: S′_t = 1 + 9·S_t

Running profile vector of weighted scores: p_t = w ⊙ s_t  where s_t = (s_{1,t}, …, s_{n,t})

Update exponential moving average: μ_t = β μ_{t−1} + (1−β) p_t  with β ∈ [0,1)

Drift signal: d_t = 1 − cos_sim(p_t, μ_{t−1})  in [0,2]

Policy hooks (async side effects, not blocking user):

if S_t < τ_S, flag for human review

if d_t > τ_d, raise drift alert, open a remediation task

write a Spirit summary note tied to L_t



Closed loop update (async)

M_{t+1} = U(M_t, L_t, S_t, μ_t, d_t)

Emit artifacts:

per turn: {t, D_t, E_t, L_t, S_t, d_t}

running: {μ_t, trend charts, drift incidents}



Type discipline, why the order is fixed in this implementation

I: (x_t, V, M_t) → a_t

W: (a_t, x_t, V, r_t) → {approve, violation}

If approve, enqueue audit, return to user (sync boundary)

C: (a_t, x_t, V) → L_t  (vector of per value scores and rationales)

S: (L_t, V, M_t) → S_t, d_t, μ_t  (scalars and updated profiles) The sync chain is I → W → user. The audit chain is C → S → M update. Swapping C and W would force the sync path to compute a full ledger before gating, which breaks latency and the function signatures you rely on.


Policy and knobs (as currently implied)

Score alphabet: {Violates, Omits, Affirms, Strongly Affirms} mapped to s ∈ {−1, 0, +½, +1}

Confidence c ∈ [0,1] derived from the model’s rubric

σ can be identity to [−1,1] then rescaled, or logistic to [0,1]

φ(c) typically linear or convex to downweight low confidence rationales

β controls memory smoothness, τ_S and τ_d set alert sensitivity


Pseudocode, faithful to runtime behavior

sync path

a, r = I(x_t, V, M_t) D, E = W(a, x_t, V, r)

if D == "violation": return safe_reply(E) log({t, x_t, a, D, E}) else: return a                      # user sees answer now enqueue_audit_job({t, x_t, a, V, M_t})

async audit worker

def run_audit(job): L = [] for v_i, w_i in V: s_i, c_i, q_i = G_i(job.a, job.x, v_i) L.append((v_i, s_i, c_i, q_i)) S = spirit_score(L, V) p = weighted_vector(L, V)         # w ⊙ s mu_new = beta * M.mu + (1-beta) * p d = 1 - cos_sim(p, M.mu)

store_audit(t=job.t, ledger=L, spirit=S, drift=d)
if S < τ_S or d > τ_d:
    raise_alert(t=job.t, reasons=top_offending_values(L), S=S, d=d)

M.mu = mu_new
M = update_memory(M, L, S, d)

