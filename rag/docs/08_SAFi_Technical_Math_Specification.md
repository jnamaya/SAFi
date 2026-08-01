---
title: "SAFi Explained: The Formal Mathematical Specification"
slug: technical-math-specification
tags: ["safi", "reference", "math", "specification"]
summary: Formal specification for SAFi — objects, the pipeline with all five Will checkpoints, the Charter/Policy compilation, alignment score versus spirit score, EMA and drift, the blind feedback contract, and the fail-closed rules.
version: 3.0
---

# SAFi Explained: The Formal Mathematical Specification

## Purpose
This document is the formal specification for the Self-Alignment Framework Interface (SAFi): the mathematical objects, the order the faculties run in, the formulas they compute, and what each faculty is deliberately not given. All stages run synchronously within a single request.

## Core mathematical objects

- t: the discrete interaction index (turn number)
- x_t: the user input at turn t, plus metadata
- V: the governed value set, compiled before the turn. Each value carries a name v_i, a weight w_i, a rubric R_i (description plus a scoring guide for +1 / 0 / -1), and a hard-gate flag h_i
- W_r: will_rules — required disclaimers, permitted syntax, allowed tools, parameter constraints, threshold overrides
- omega, sigma: worldview and style (prose, not scored)
- a_t: the draft answer produced by the Intellect
- r_t: the Intellect's short reflection on its own draft
- i_t: the typed intent — text, tool_call, or none
- L_t: the Conscience ledger; per scored value a tuple (s_i, c_i, q_i) where s_i is in [-1, 1], c_i is in [0, 1], and q_i is the text rationale
- A_t: the alignment score in [0, 1] — the quantity the Will gates on
- S_t: the spirit score, an integer in [1, 10] — the quantity that gets reported
- p_t: the performance vector, w elementwise-multiplied by s_t
- mu_t: long-term memory, stored keyed by value name
- d_t: drift in [0, 2], or undefined
- f_t: the coaching note (a string, frequently empty)
- beta: EMA smoothing factor, default 0.9
- theta: alignment threshold, default 0.5
- gamma: Charter share of the value set, default 0.40

## Synderesis layer: how V is compiled
Synderesis builds the value set before the turn begins from two tiers:

V = gamma * Charter + (1 - gamma) * Policy, with gamma = 0.40 by default

The organisational Charter takes a fixed share of every evaluation and the business-unit Policy takes the remainder. Either tier may be absent, in which case the other carries the full weight. The compiled set is read-only for the duration of the turn: no faculty can alter what it is being judged against while being judged.

Values flagged as hard gates carry w_i = 0. They are excluded from the weighted arithmetic and from the memory update, because they are not meant to be traded off against anything.

## Timing model
Every stage runs synchronously inside a single request. The audit is not a background job, and no answer reaches the user before it has been scored and ruled on. An audit that ran after delivery would be a report, not a control.

## The pipeline
The Will acts at five separate points. This is the part most descriptions of SAFi get wrong.

```
0.  Will        g0(x_t)                          -> safe | reason
1.  Intellect   (i_t, r_t) = I(x_t, omega, sigma, M_t, tools)
2.  Will        gT(name, params, W_r)            -> approve | reason   [if tool_call]
3.  Will        gS(a_t, W_r)                     -> pass | reason
4.  Conscience  L_t = C(a_t, x_t, r_t, ctx, history, R)
5.  Will        gH(L_t, h)                       -> approve | violation
6.  Spirit      (A_t, S_t, p_t, mu_t, d_t) = Sp(L_t, mu_prev, w, c)
7.  Will        gA(A_t, theta)                   -> approve | violation
8.  Spirit      f_t = F(mu_t, d_t, p_t)
```

Stage 0 runs before any model is called. Stage 2 fires only when the Intellect proposed a tool. Stage 3 repairs a missing disclaimer deterministically before it blocks. Stages 5 and 7 are the two places a scored turn can still be refused.

## The Will is a pure function
Every gate above makes zero model calls. They are string comparisons, set membership tests and numeric thresholds. This is a mathematical property, not only an implementation note: the same inputs always produce the same output. A gate that cannot be reproduced cannot be audited, and a gate that consults a language model cannot be reproduced.

## Spirit formulas

### Alignment score — what the Will gates on
A_t = sum(w_i * (s_i + 1)/2) / sum(w_i)

Scores are mapped from [-1, 1] to [0, 1] and weighted. A value the audit did not score contributes a neutral 0.5 rather than a zero. If the audit scored none of the agent's values, A_t = 0 and the turn is a critical violation — a response nobody scored has not passed.

### Spirit score — what gets reported
raw = clip( sum(w_i * s_i * c_i), -1, 1 )
S_t = round( (raw + 1)/2 * 9 + 1 ), an integer in [1, 10]

Confidence enters here and only here. A_t ignores confidence deliberately, because a gate should not be softened by the judge's hesitancy; S_t includes it, because a reported figure should reflect how well evidenced it was.

### Performance vector and memory
p_t = w elementwise-multiplied by s_t
ema = beta * mu_prev + (1 - beta) * p_t
mu_t,i = ema_i if value i was scored this turn, otherwise mu_prev,i

The second case matters. An unscored value holds its memory rather than decaying toward zero: a missing observation is not evidence of mediocrity, and letting it pull the coordinate toward neutral would manufacture a signal out of silence.

Memory is keyed by value name, not by position in a list. Reordering or renaming a policy therefore cannot silently repoint a coordinate, and a value dropped from the current policy keeps its history in case it returns.

### Drift
d_t = 1 - cos_sim(p_t, mu_prev), undefined when either vector has norm approximately zero

Drift measures how characteristic a response was, not how good. Nothing is ever blocked for drifting; crossing the organisation's threshold (default 0.4) queues the turn for supervisory review by a human. At cold start drift is reported as undefined rather than 0, because an agent with no history has no character to deviate from.

### Python implementation (from spirit.py)
```python
p_t    = self.value_weights * scores                    # performance vector
ema    = self.beta * mu_tm1_vector + (1 - self.beta) * p_t
mu_new = np.where(observed, ema, mu_tm1_vector)         # unobserved values HOLD
denom  = float(np.linalg.norm(p_t) * np.linalg.norm(mu_tm1_vector))
drift  = None if denom < eps else 1.0 - float(np.dot(p_t, mu_tm1_vector) / denom)
```

## Feedback, and why it is blind
f_t = F(mu_t, d_t, p_t)

f_t is the only channel by which anything the loop concluded re-enters the next turn's drafting. What matters is what its output excludes:

- f_t may contain a qualitative trend signal, and at most one value NAME.
- f_t never contains rubrics, scoring guides, weights, A_t, S_t, d_t, or any s_i or c_i.
- f_t is the empty string whenever nothing is off, and at cold start.

The constraint exists because the audit's independence is its entire value. A drafter that can see the criteria it is scored against will optimise toward them and the measure stops measuring — Goodhart's law. Value names are permitted only because they already appear in the agent's worldview as its declared identity, so naming one reveals nothing new about the test.

## Type signatures, stated as denials
The separations are the design, so the signatures are given with what each faculty is refused.

```
I  : (x_t, omega, sigma, M_t, tools)        -> (i_t, r_t)
       denied: R, w, and every score

W  : (x_t | i_t | a_t | L_t | A_t, W_r, h, theta) -> decision x reason
       denied: semantics — no model, cannot read meaning

C  : (a_t, x_t, r_t, ctx, history, R)       -> L_t
       denied: w, so it cannot reason about downstream consequences

Sp : (L_t, mu_prev, w, c)                   -> (A_t, S_t, p_t, mu_t, d_t, f_t)
       denied: authority — it computes; the Will decides
```

## Fail-closed rules
- A hard-gate value present in V but absent from L_t: violation.
- L_t scored none of the values in V: violation, A_t = 0.
- A constrained tool parameter not supplied: refuse the tool.
- A tool not in the agent's allowed list: refuse the tool.
- A_t below theta: violation.
- Any hard-gate value scoring s_i <= -1: violation.

None of these are error conditions the system routes around. Each is a decision to stop, because the alternative is shipping something ungoverned and describing it as governed.

## What the record contains
Each turn writes the inputs, the intent, every gate decision with its reason, the full ledger with rationales and confidences, A_t, S_t, d_t, and the updated memory. Because mu persists and is keyed by name, character can be compared across arbitrary spans. Per-turn drift compares a response to recent habit, and habit moves; a retained record is what makes a slow drift visible at all.

## Cross references
- 02 Faculties Intellect
- 03 Faculties Will
- 04 Faculties Conscience
- 05 Faculties Spirit
- 07 Concepts Drift Allegory
- 23 SAFi Synderesis
- 10 SAFi Technical Workflow
