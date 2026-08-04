---
title: SAFi Math Specification
slug: safi-math-specification
tags: ["safi", "mathematics"]
summary: This is the formal specification for SAFi: the objects it operates on, the order in which its faculties run, the formulas they compute, and — most importantly — what each faculty is not given. Everything below is written in plain monospace rather than typeset mathematics, so it renders everywhere an
version: 1.0
---

# SAFi Math Specification

This is the formal specification for SAFi: the objects it operates on, the order in which its faculties run, the formulas they compute, and — most importantly — what each faculty is not given.

Everything below is written in plain monospace rather than typeset mathematics, so it renders everywhere and can be copied straight out.

## Timing: everything is synchronous

All stages run **synchronously inside a single request**. Stating that first, because it changes how everything below should be read.

The audit is not a background job, and no answer reaches the user before it has been scored and ruled on. If the audit ran after delivery it would be a report, not a control.

## Objects

```
t          turn index
x_t        user input for this turn, plus metadata

V          the governed value set, compiled before the turn:
             v_i        value name
             w_i        weight, w_i >= 0, sum(w_i) = 1 over scored values
             R_i        rubric: description + scoring guide for +1 / 0 / -1
             h_i        hard-gate flag (boolean)

W_r        will_rules: required disclaimers, permitted syntax,
           allowed tools, parameter constraints, threshold overrides
ω, σ       worldview and style (prose, not scored)

a_t        draft answer from the Intellect
r_t        the Intellect's short reflection on its own draft
i_t        typed intent: {text} | {tool_call, name, params} | none

L_t        Conscience ledger, one entry per scored value:
             (v_i, s_i, c_i, q_i)
             s_i in [-1, 1]   score against R_i
             c_i in [0, 1]    confidence: strength of evidence for s_i
             q_i              text rationale

A_t        alignment score in [0, 1]      -- the gating quantity
S_t        spirit score, integer [1, 10]  -- the reported quantity
p_t        performance vector = w ⊙ s_t
μ_t        long-term memory, keyed by value name
d_t        drift in [0, 2], or undefined
f_t        coaching note (string, often empty)

β          EMA smoothing factor, default 0.9
θ          alignment threshold, default 0.5
γ          Charter share of the value set, default 0.40
```

## How V is compiled

The value set is not handed in flat. Synderesis builds it before the turn from two tiers:

```
V = γ · Charter  ⊕  (1 - γ) · Policy        γ = 0.40 by default
```

An organisation's Charter takes a fixed share of every evaluation; a business unit's Policy takes the remainder. Either may be absent, in which case the other carries the full weight. The compiled set is **read-only for the duration of the turn** — no faculty can alter what it is judged against while being judged.

Values marked as hard gates carry `w_i = 0`. They are excluded from the weighted arithmetic and from the memory update entirely, because they are not meant to be traded off against anything.

## The pipeline

The Will appears five times. That is the part most descriptions of SAFi get wrong.

```
0.  Will      g0(x_t)                        -> safe | reason
1.  Intellect (i_t, r_t) = I(x_t, ω, σ, M_t, tools)
2.  Will      gT(name, params, W_r)          -> approve | reason      [if tool_call]
3.  Will      gS(a_t, W_r)                   -> pass | reason
4.  Conscience L_t = C(a_t, x_t, r_t, ctx, history, R)
5.  Will      gH(L_t, h)                     -> approve | violation
6.  Spirit    (A_t, S_t, p_t, μ_t, d_t) = Sp(L_t, μ_{t-1}, w, c)
7.  Will      gA(A_t, θ)                     -> approve | violation
8.  Spirit    f_t = F(μ_t, d_t, p_t)
```

Stage 0 runs before any model is called. Stage 2 only fires when the Intellect proposed a tool. Stage 3 repairs a missing disclaimer deterministically before it blocks. Stages 5 and 7 are the two places a scored turn can still be refused.

## The Will is a pure function

Every `g` above contains **zero model calls**. They are string comparisons, set membership tests and numeric thresholds.

That is a mathematical property, not just an implementation note: `g(same inputs) = same output`, always. A gate that cannot be reproduced cannot be audited, and a gate that consults a language model cannot be reproduced.

## The Conscience

For each scored value, independently:

```
(s_i, c_i, q_i) = C_i(a_t, x_t, r_t, ctx, history, R_i)
```

Note the argument list. `R_i` is the rubric — description and scoring guide. **The weights `w_i` are not passed.** A judge that knew one value carried 0.40 and another 0.25 would have reason to shade a score for its downstream effect; the weights are applied afterwards, by a component that never saw the response.

Confidence is not decoration. It is multiplied into `S_t` below, which means an uncalibrated judge emitting `c_i = 0.9` for everything deflates every score, and a violation recorded at `c_i = 0.4` loses 60% of its corrective force.

## The Spirit

Four quantities, and the first two are routinely confused.

**Alignment score — the number the Will rules on.**

```
A_t = Σ w_i · (s_i + 1)/2  /  Σ w_i
```

Scores are mapped from `[-1, 1]` to `[0, 1]` and weighted. A value the audit did not score contributes a neutral `0.5` rather than a zero. If the audit scored **none** of the agent's values, `A_t = 0` and the turn is a critical violation — a response nobody scored has not passed.

**Spirit score — the number that gets reported.**

```
raw = clip( Σ w_i · s_i · c_i , -1, 1 )
S_t = round( (raw + 1)/2 · 9 + 1 )          integer in [1, 10]
```

This is where confidence enters. `A_t` ignores confidence deliberately, because a gate should not be softened by the judge's hesitancy; `S_t` includes it, because a reported figure should reflect how well evidenced it was.

**Performance vector and memory.**

```
p_t   = w ⊙ s_t                                   element-wise
ema   = β · μ_{t-1} + (1 - β) · p_t
μ_t,i = ema_i        if value i was scored this turn
        μ_{t-1},i    otherwise
```

The second case is the one worth reading twice. An unscored value **holds** its memory; it does not decay toward zero. A missing observation is not evidence of mediocrity, and letting it pull the coordinate toward neutral would manufacture a signal out of silence.

`μ` is stored keyed by value name, not by position in a list. Reordering or renaming a policy therefore cannot silently repoint a coordinate, and a value dropped from the current policy keeps its history in case it returns.

**Drift.**

```
d_t = 1 - cos_sim(p_t, μ_{t-1})            undefined if either norm ~ 0
```

Drift measures how *characteristic* a response was, not how good. Nothing is ever blocked for drifting; crossing an organisation's threshold (default 0.4) queues the turn for human review. At cold start it is reported as undefined rather than 0, because an agent with no history has no character to deviate from.

## Feedback, and why it is blind

```
f_t = F(μ_t, d_t, p_t)
```

`f_t` is the only channel by which anything the loop concluded re-enters the next turn's drafting. Note what is absent from its output rather than its input:

```
f_t may contain     a qualitative trend signal
                    at most one value NAME
f_t never contains  rubrics, scoring guides, weights,
                    A_t, S_t, d_t, or any s_i or c_i
f_t = ""            whenever nothing is off, and at cold start
```

The constraint exists because the audit's independence is its entire value. A drafter that can see the criteria it is scored against will optimise toward them, and the measure stops measuring — Goodhart's law, arriving on schedule. Value names are permitted only because they already appear in the agent's own worldview as its declared identity, so naming one reveals nothing new about the test.

## Type signatures, stated as denials

The conventional way to write this section is to give each faculty the full state and let the reader assume it uses what it needs. That would misrepresent the design, because the separations are the design.

```
I  : (x_t, ω, σ, M_t, tools)          -> (i_t, r_t)
       denied: R, w, and every score

W  : (x_t | i_t | a_t | L_t | A_t, W_r, h, θ) -> decision × reason
       denied: semantics — it has no model and cannot read meaning

C  : (a_t, x_t, r_t, ctx, history, R) -> L_t
       denied: w, so it cannot reason about consequences

Sp : (L_t, μ_{t-1}, w, c)             -> (A_t, S_t, p_t, μ_t, d_t, f_t)
       denied: authority — it computes; the Will decides
```

## Fail-closed rules

```
hard-gate value present in V but absent from L_t   -> violation
L_t scored none of the values in V                 -> violation, A_t = 0
constrained tool parameter not supplied            -> refuse the tool
tool not in the agent's allowed list               -> refuse the tool
A_t < θ                                            -> violation
any hard-gate value with s_i <= -1                 -> violation
```

None of these are error conditions the system routes around. Each is a decision to stop, because the alternative is shipping something ungoverned and describing it as governed.

## What the record contains

Every turn writes the inputs, the intent, each gate decision with its reason, the full ledger with rationales and confidences, `A_t`, `S_t`, `d_t`, and the updated memory. Because `μ` persists and is keyed by name, character can be compared across arbitrary spans — this quarter against last, or against the day the agent was deployed.

That last property matters more than any single formula here. Per-turn drift compares a response to recent habit, and habit moves. A retained record is what makes a slow drift visible at all.
