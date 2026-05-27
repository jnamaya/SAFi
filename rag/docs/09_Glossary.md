---
title: SAFi Glossary
slug: glossary
tags: [safi, reference, glossary]
summary: Definitions of symbols, variables, and recurring terms used across the SAFi corpus. Updated for the five-faculty architecture.
version: 2.0
---

## Symbols and variables

- a_t: Proposed draft answer at turn t (from Intellect)
- r_t: Rationale or reasoning trace at turn t (from Intellect)
- x_t: Current user input or query at turn t
- V = {(v_i, w_i)}: Active values profile with non-negative weights summing to 1.0
- M_t: Memory state at turn t (conversation summary + Spirit coaching note)
- D_t: Will gate decision at turn t (approve or block)
- L_t: Conscience ledger at turn t (score, confidence, rationale per declared value)
- S_t: Spirit coherence score at turn t, scaled to [1, 10]
- p_t: Alignment profile vector at turn t (element-wise product of value weights and Conscience scores)
- μ_t: Long-term memory vector at turn t (EMA of alignment profile vectors over time)
- d_t: Behavioral drift at turn t (cosine distance from historical baseline μ_{t-1})
- β: EMA smoothing factor (default 0.9) used by Spirit

## Canonical equations

- Intellect: (a_t, r_t) = I(x_t, V, M_t, context, coaching)
- Will: D_t = W(a_t, x_t, P) — deterministic Python, zero LLM calls
- Conscience: L_t = C(a_t, x_t, V) — synchronous, Phase 4
- Spirit score: S_t = clip(Σ wᵢ · sᵢ · cᵢ, −1, 1) → [1, 10]
- Spirit EMA: μ_t = β · μ_{t-1} + (1 − β) · p_t
- Drift: d_t = 1 − cos_sim(p_t, μ_{t-1})

## Key architectural terms

- **Synderesis**: The fifth faculty and constitution compiler. Establishes immutable rules, value weights, rubrics, and scope boundaries for each persona. Read-only after deployment; no other faculty can modify it at runtime.
- **Intent Air Gap**: The architectural separation between the Intellect (generation) and execution. The Intellect can only produce proposals (intents); it cannot execute actions directly. This prevents a jailbroken Intellect from doing real harm.
- **Blind Will**: The Will faculty's defining security property. Pure deterministic Python with zero LLM calls, incapable of semantic reasoning, and therefore immune to prompt injection and social engineering.
- **Reflexion Loop**: When the Will blocks a draft, it instructs the Intellect to produce a revised, compliant response rather than immediately returning a refusal to the user. The Will then re-evaluates the new draft.
- **Phase Zero (Phase 0)**: The pre-generation gate. Screens the incoming prompt against persona-specific blacklists before any LLM generation begins. If triggered, the Intellect is never called.
- **Scope Compliance**: A special value declared in every SAFi persona profile. A Conscience score of −1.0 on Scope Compliance triggers the Phase 4.5 hard gate, blocking the response regardless of all other value scores.
- **Ethical ledger (L_t)**: The structured output of the Conscience audit: one record per value with a score (−1.0 to +1.0), confidence (0.0 to 1.0), and text rationale.
- **Alignment profile (p_t)**: The per-turn ethical fingerprint vector, computed as the element-wise product of value weights and Conscience scores.
- **Hard gate (Phase 4.5)**: The Will's second check after the Conscience audit. Reads the ledger for Scope Compliance score and triggers a block if it is −1.0.
- **EMA (Exponential Moving Average)**: The mathematical mechanism Spirit uses to maintain the long-term memory vector μ_t: μ_t = β · μ_{t-1} + (1 − β) · p_t.
