---
title: SAFi Glossary
slug: glossary
tags: [safi, reference, glossary]
summary: Definitions of symbols, variables, and recurring terms used across the SAFi corpus.
version: 1.0
---

## Symbols and variables

- a_t: Proposed answer at time t (from Intellect)
- r_t: Rationale or reasoning trace at time t (from Intellect)
- x_t: Current user input or query at time t
- V: Active values profile
- M_t: Memory state at time t
- D_t: Decision outcome at time t (after Will gate)
- E_t: Ethical evaluation components at time t (from Conscience)
- L_t: Conscience ledger entry at time t
- S_t: Spirit score at time t (alignment/coherence)
- μ_t: Policy parameters or model guidance active at time t
- d_t: Drift measure over a time window

## Canonical equations

- Intellect: (a_t, r_t) = I(x_t, V, M_t)
- Will: D_t = W(a_t, r_t, V, policy)
- Conscience: L_t = C(D_t, standards, context)
- Spirit: S_t = S(L_{≤t}, patterns)
