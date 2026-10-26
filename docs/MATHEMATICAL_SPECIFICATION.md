# SAFi Mathematical Specification

> **Version:** 1.10.0
> **Last Updated:** 2026-10-15
> **Status:** Aligned with code implementation

This document defines the formal mathematical foundation of SAFi's five-stage architecture.

> **Implementation note:** This specification is implementation-agnostic. It defines
> SAFi as a cognitive architecture, a set of abstract functions with defined signatures,
> information flow, and scoring semantics. The reference implementation uses large language
> models for the Intellect and Conscience faculties, but any function satisfying the defined
> signature may be substituted (a rules engine, a different model, a human reviewer, etc.).
> The math makes no assumptions about the underlying technology.

---

## Core Mathematical Objects

| Symbol | Description |
|--------|-------------|
| $t$ | Interaction index. Indexes the agent's Spirit-memory sequence, not the conversation. `spirit_memory` is keyed on `profile_name` alone, so built-in agents share $t$ and $\mu_t$ across every organization using that agent. Custom agents are namespaced by org prefix. Governance records carry `t_sequence`. |
| $x_t$ | Input context (prompt + metadata) |
| $\text{scope}$ | Compiled scope boundaries from Synderesis, defining the agent's appointed office |
| $C_{\text{scope}}$ | Antecedent Conscience prompt-scope evaluator (*conscientia antecedens*) |
| $s_{\text{scope}} \in [-1.0, 1.0]$ | Continuous scope alignment score for prompt $x_t$ |
| $c_{\text{scope}} \in [0, 1]$ | Scope confidence score |
| $V = \{(v_i, w_i)\}$ | Value set with weights, $\sum w_i = 1$ |
| $R$ | Rubric set compiled by Synderesis, one scoring guide per value. Given to the Conscience, withheld from the Intellect. |
| $P$ | Persona given to the Intellect: worldview and style. Carries no value, weight, rubric or score. |
| $a_t$ | Draft response from Intellect |
| $D_t \in \{\text{approve}, \text{violation}\}$ | Will's decision |
| $E_t$ | Will's reason string |
| $L_t = \{(v_i, s_{i,t}, c_{i,t})\}$ | Conscience ledger per value |
| $s_{i,t} \in [-1.0, 1.0]$ | Alignment score for value $v_i$ (continuous float) |
| $c_{i,t} \in [0, 1]$ | Confidence for value $v_i$ |
| $A_t \in [0, 1]$ | Aggregate alignment score. Gating quantity consumed by Will Pass 3. |
| $S_t \in [1, 10]$ | Spirit coherence score. Display/audit quantity. |
| $f_t$ | Coaching note from the Spirit, read by turn $t+1$'s Intellect. Qualitative; at most one value name. |
| $M_t$ | Memory state (prior audits, profiles, aggregates) |

---

## Timing Model

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  SYNCHRONOUS (User Waits for All of This)                                                              │
│                                                                                                        │
│ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ ┌────────┐ ┌────────┐                 │
│ │Phase Zero│─▶ Conscience│─▶│Intellect │─▶│Will P1 │─▶│Conscience │─▶│Will P2 │─▶│Spirit  │                 │
│ └──────────┘ │Scope Pre- │ └──────────┘ │structur│ └───────────┘ │hard-   │ └────────┘                 │
│      │       │flight (P1)│      (P2)    │-al     │  Draft Audit │gate    │      │  (P5)                │
│      │       └───────────┘              └────────┘      (P4)     │ (P4.5) │ ┌────────┐                 │
│      │             │                        │                    └────────┘ │Will P3 │                 │
│  [unsafe]   [out_of_scope]             [violation]                   │      │alignmnt│                 │
│      │             │                        ▼                    [violation]└────────┘                 │
│      │             │                  redirect (no              │     │          │                     │
│      │             │                   reflexion)          redirect    │   [violation:                 │
│      │             │                                                   │  low_align /                  │
│      │             │                                                   │  ethical]                     │
│      │             │                                                   │        ▼                      │
│      │             │                                                   │  ┌──────────┐                 │
│      │             │                                                   │  │Reflexion │                 │
│      │             │                                                   │  │(regen →  │                 │
│      │             │                                                   │  │ re-audit)│                 │
│      │             │                                                   │  └──────────┘                 │
│      │             │                                                   │   Retry once                  │
│      │             │                                                   │        │                      │
│      │             │                                                   │  still violation?             │
│      │             │                                                   │  ├ low_align →                │
│      │             │                                                   │  │  system notice             │
│      │             │                                                   │  └ ethical →                  │
│      ▼             ▼                                                   ▼     redirect                   │
│  redirect ◀──────────────────────────────────────────────────────────┘        │                      │
│                                                                               ▼                      │
│                                                                         Return to User                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                         │
                         ▼ (ThreadPoolExecutor, fire and forget)
┌────────────────────────────────────────────────────────────────────────────────┐
│  ASYNCHRONOUS (Background)                                                     │
│  ┌─────────────────────────┐   ┌──────────────────────────────────┐           │
│  │ Conversation Summarizer │   │ Profile Extraction (if enabled)  │           │
│  └─────────────────────────┘   └──────────────────────────────────┘           │
└────────────────────────────────────────────────────────────────────────────────┘
```

All gates above run synchronously. Summarization and profile extraction run asynchronously. Exit from each failed gate is fixed by the failure class:

| Failure | Exit |
|---|---|
| Phase Zero: any check | Agent redirect. Intellect never called. |
| Phase 1: scope preflight (`preflight_prompt_scope`) | Agent redirect (`phase_one_scope`). Intellect never called. |
| Pass 1: unrepairable structural failure | System failure notice. No retry. |
| Pass 1: audit unavailable (fail-closed) | System failure notice. No retry. |
| Pass 2: scope/grounding reason | Agent redirect. No retry. |
| Pass 2: `ethical_violation` reason | Reflexion retry. |
| Pass 3: `low_alignment_score` | Reflexion retry, then system failure notice if unapproved. |
| Pass 3: `ethical_violation` | Reflexion retry, then agent redirect. |

---

## Stage 0: Phase Zero Gate

Before the Intellect is ever invoked, the Phase Zero Gate evaluates the raw user prompt deterministically, invoking no intelligent component. A detected threat short-circuits immediately to a governed redirect. Detection mechanisms run in order:

**1. Global signature scan** against `INJECTION_SIGNATURES` in `safi_app/security_policy.py`:

$$\text{safe} = \neg \exists\ p \in \text{INJECTION-SIGS} : p \subseteq \text{lower}(x_t)$$

**2. Agent blacklist scan** checks keywords from the compiled profile's `early_prompt_blacklist`, the **union** of the organization Charter's list and the business-unit Policy's list (a Policy adds to what the org blocks; it cannot remove from it):

$$\text{safe} = \neg \exists\ p \in \text{blacklist} : p \subseteq \text{lower}(x_t)$$

**2b. Sensitive identifier scan** is a regex-plus-checksum match against `pii_validators` (enabled per org); a hit returns `pii_detected`. Runs before the Intellect so the data never reaches the model.

**3. Embedded-instruction blob heuristic** flags an encoded payload *attached to* an instruction marker. A windowed entropy scan alone cannot separate a payload from technical prose (300-char windows over this repo's own docs measure 5.28–5.46 bits/char, all above the retired 4.5 threshold, while a hex dump scores 3.97 and slips past it), so the discriminator is word structure: an encoded payload is one long unbroken non-whitespace run, prose is not. The test requires a minimum prompt length, at least one marker anywhere in the prompt, and a qualifying blob whose entropy floor holds *inside the blob*, with a marker within proximity of it:

hit ⇔ |x_t| ≥ τ_len ∧ has-instr-marker(x_t) ∧ ∃ b ∈ blobs(x_t) : (|b| ≥ β_run ∧ H(b[0 : τ_sample]) ≥ β_H ∧ ∃ m ∈ markers(x_t) : start(b) − δ_prox ≤ m ≤ end(b) + δ_prox)

H(s) = −Σ_c P(c) · log₂ P(c)

Where blobs(x_t) are the maximal runs of non-whitespace characters in x_t; markers(x_t) are the start offsets in lower(x_t) of every entry in `EMBEDDED_INSTRUCTION_MARKERS`; start(b)/end(b) are the blob's character offsets (end exclusive); and:

- τ_len = 150 chars (`MIN_LENGTH_FOR_ENTROPY_CHECK`) — short prompts are exempt; entropy over a few characters says nothing
- β_run = 200 chars (`BLOB_MIN_RUN`) — measured: base64 of 400 random bytes is one 536-char run and a hex dump 600, while the longest unbroken run across this repo's docs is 113 (a URL in README); 200 sits in that gap with room either side
- τ_sample = 300 chars (`ENTROPY_SAMPLE_LENGTH`) — the blob prefix actually scored
- β_H = 3.0 bits/char (`BLOB_MIN_ENTROPY`) — a floor that only rejects degenerate repetition inside an already-unbroken run (measured: one repeated character ≈ 0–2, hex 3.97, base64 5.88, random printable 6.27)
- δ_prox = 600 chars (`BLOB_MARKER_PROXIMITY_CHARS`) — the instruction must be *attached* to the payload; a marker in paragraph three and a blob in paragraph forty is a long document, not this attack

A hit returns gate reason `injection:embedded_instruction`. The legacy sliding-window threshold `ENTROPY_THRESHOLD` (4.5 bits/char) is retired from this gate and survives only in the benchmark's inline fallback scanner.

**If any check fails** → `trigger_agent_redirect(violation_type=gate_reason)` and return.
**If all pass** → proceed to Stage 0.5 (or Stage 1 if scope preflight is disabled).

**Code Reference:** [`phase_zero.py`](../safi_app/core/faculties/phase_zero.py), [`security_policy.py`](../safi_app/security_policy.py), [`orchestrator.py#Phase0`](../safi_app/core/orchestrator.py)

---

## Stage 0.5: Antecedent Conscience (Prompt Scope Preflight Gate)

Following the deterministic Phase Zero gate, SAFi optionally invokes the **Conscience** faculty in its classical antecedent office (*conscientia antecedens*, Aquinas *ST* I, q. 79, a. 13) when `preflight_prompt_scope` is enabled in the agent's policy:

$$s_{\text{scope}}, c_{\text{scope}}, \text{reason} = C_{\text{scope}}(x_t, \text{scope}, H_t)$$

Where:
- $x_t$ is the inbound user prompt context
- $\text{scope}$ is the compiled agent scope boundary from Synderesis $\Sigma(\text{policy}) \rightarrow (V, R, \text{scope})$
- $H_t$ is recent conversation history (retaining cross-turn context)
- $s_{\text{scope}} \in [-1.0, 1.0]$ is the continuous scope alignment score
- $c_{\text{scope}} \in [0, 1]$ is the confidence score

$$\text{safe}_{\text{scope}} = (s_{\text{scope}} \geq 0.0)$$

**Philosophical and Architectural Rationale:**
In Thomistic moral psychology (*ST* I, q. 79, a. 13), conscience acts not only *consequently* (judging what was done, *bene vel non bene factum*), but *antecedently* (judging whether an act ought to be entertained, *an sit faciendum*). Furthermore, per Aristotle (*Nicomachean Ethics* III.3) and Aquinas (*ST* I-II, q. 14, a. 2), the rational power does not deliberate (*consilium*) on objectives outside its appointed office (*officium* / *iudicium usurpatum*, *ST* II-II, q. 60, a. 6).

Evaluating prompt scope antecedently ensures:
1. **No Out-of-Scope Deliberation or Tool Execution:** The Intellect is prevented from constructing plans, generating responses, or invoking tools on objectives outside its authority.
2. **Separation of Concerns ($P$ vs $V, R, \text{scope}$):** Rubrics $R$ and value weights $w_i$ remain strictly withheld from the Intellect. The Conscience evaluates the prompt purely against the high-level scope boundary.
3. **Preservation of Spirit Memory ($\mu_t$):** A failed scope preflight terminates at Phase 1 via `trigger_agent_redirect(violation_type="scope_violation", will_stage="phase_one_scope")`. The redirect path bypasses the Spirit EMA update, preventing non-content scope rejections from drifting the agent's long-term moral profile.

**If $\text{safe}_{\text{scope}} = \text{false}$** ($s_{\text{scope}} < 0.0$) → `trigger_agent_redirect(violation_type="scope_violation", will_stage="phase_one_scope")` and return immediately. Intellect is never called.
**If $\text{safe}_{\text{scope}} = \text{true}$** (or if `preflight_prompt_scope` is disabled) → proceed to Stage 1.

**Code Reference:** [`conscience.py#evaluate_prompt_scope()`](../safi_app/core/faculties/conscience.py), [`orchestrator.py#Phase1`](../safi_app/core/orchestrator.py)

---

## Stage 1: Intellect

The Intellect generates the initial response and internal reflection:

$$a_t, r_t = I(x_t, P, M_t, f_{t-1})$$

Where:
- $a_t$ is the draft response
- $r_t$ is a short internal reflection (used for audit logging)
- $P$ is the persona: worldview and style, never the value set
- $f_{t-1}$ is the previous turn's qualitative coaching note

**$V$ is absent, and that is deliberate.** The Intellect receives the persona $P$, never the value set, the weights, the rubrics or any score. A drafter able to read the rubric it will be graded against would optimise toward it, and the audit would become circular (Goodhart). The one channel back from the audit is $f_{t-1}$, which carries a qualitative signal and at most one value's *name*, never a score, weight or rubric.

**Code Reference:** [`intellect.py#generate()`](../safi_app/core/faculties/intellect.py)

---

## Stage 2: Will

The Will is entirely deterministic (invokes no intelligent component) and runs **three separate passes** interleaved with Conscience and Spirit. Each pass is binary: approve or violation.

### Pass 1: Structural Check (before Conscience)

Evaluates the Intellect's draft directly against structural invariants:

$$D^1_t, E^1_t = W_1(a_t)$$

Checks in order (`evaluate_draft_structure`):
1. Required disclaimer substring present in $a_t$ (when `require_disclaimer` is set)
2. Sensitive identifier scan on the *output* ($a_t$) when `pii_validators` are enabled (`pii_detected`); the inbound half is Phase Zero 2b
3. Code-fence policy: a non-empty `allowed_markdown_syntaxes` whitelist blocks any fence not explicitly permitted; otherwise a legacy `banned_markdown_syntaxes` blacklist applies.

**Deterministic repair before violation:** a missing mandatory disclaimer is mechanically repairable. The orchestrator appends it ($a_t \leftarrow a_t \oplus \text{disclaimer}$) and the repaired draft re-runs the **full** audit path. Only structurally unrepairable drafts produce $D^1_t = \text{violation}$.

**If $D^1_t = \text{violation}$** → ship a deterministic **system failure notice** (`_ship_system_failure_notice`): a structural failure is a fault of the system, not a verdict on the user's request, so it is *not* voiced as an agent redirect. There is **no reflexion retry at this pass.** The same routing applies to an audit-availability failure (Conscience unreachable or garbled: fail-closed).
**If $D^1_t = \text{approve}$** → proceed to Stage 3 (Conscience).

### Pass 2: Hard-Gate Check (after Conscience, before Spirit)

Evaluates the Conscience ledger for hard-gate failures (`evaluate_hard_gates`):

$$D^2_t, E^2_t = W_2(L_t, V)$$

Any value flagged `hard_gate=true` with score $\leq -1$ triggers immediate violation. The check is **fail-closed**: if a hard-gate value is missing from the ledger (Conscience omitted it or returned a garbled ledger), that too is a violation (`hard_gate_unscored`). The violation reason is per-value data (`gate_reason`), stamped into the compiled profile by Synderesis and validated against {`scope_violation`, `grounding_violation`, `ethical_violation`}, defaulting to `hard_gate_violation`. The Will reads the reason from the failing value and never derives it from the value's name. Hard-gate values carry `weight = 0.0` and are excluded from the Spirit EMA.

**If $D^2_t = \text{violation}$**, the exit depends on the mapped reason:
- Scope/grounding-class reasons (a verdict on engaging the request at all) → call `trigger_agent_redirect()` directly, no retry.
- `ethical_violation`-class reasons (a *correctable* content-quality gate: the request is fine, the draft is the problem) → route to **Stage 2.1 (Reflexion Retry)**.

**If $D^2_t = \text{approve}$** → proceed to Stage 4 (Spirit).

### Pass 3: Alignment Check (after Spirit aggregation)

Consumes Spirit's aggregate assessment $`(\text{critical\_violation},\ A_t)`$ produced by `SpiritIntegrator.integrate()`, **not** the $[1,10]$ coherence score $S_t$ (`evaluate_spirit_score`):

```math
D^3_t, E^3_t = W_3(\text{critical\_violation}_t,\ A_t)
```

- If `critical_violation` is set → violation with reason `ethical_violation`.
- Else if $A_t < \theta$ → violation with reason `low_alignment_score`.

The threshold $\theta$ resolves agent-specific override (`will_rules.structural_requirements.alignment_score_threshold`) → instance default (`SPIRIT_ALIGNMENT_THRESHOLD`, $0.5$).

That override is itself the **stricter** of the two governance tiers, resolved at compile time by Synderesis. The Charter sets a floor a Policy may raise but not lower:

```math
\theta_{\text{override}} = \max(\theta_{\text{charter}},\ \theta_{\text{policy}})
```

with an absent value on either side simply omitted from the max.

**If $D^3_t = \text{violation}$** → run **Stage 2.1 (Reflexion Retry)** once. After the retry, the outcome depends on the residual reason:
- `low_alignment_score` (or any unapproved residual state) → ship **deterministic system failure notice** via `_ship_system_failure_notice()`. In accordance with classical governance, a defective act is never willed; the system does not deliver low-alignment drafts.
- `ethical_violation` (critical) → call `trigger_agent_redirect()`.

**If $D^3_t = \text{approve}$** → return $a_t$ to user.

### Tool-Intent Gate (agentic turns only)

When the Intellect proposes a tool call instead of a text draft, a fourth deterministic Will check runs **before any execution** (`evaluate_tool_intent`). Given a proposed tool name $\tau$ with parameters $\pi$ and the compiled profile's authorization list $T_{\text{allow}}$ (stamped by Synderesis as the intersection of the agent's advertised tools with each governance tier's `allowed_tools`; every layer narrows, none widens):

```math
T_{\text{allow}} = T_{\text{advertised}} \cap T_{\text{charter}} \cap T_{\text{policy}}
```

An absent or empty list at either governance tier means *that tier does not narrow* (it is dropped from the intersection), **not** deny-all. A Charter or Policy cannot grant a tool the agent was never given, so the advertised list is already the ceiling. Both sides are expanded from connector names to function names before intersecting, so authorizing a connector authorizes every function under it.

```math
W_{\text{tool}}(\tau, \pi) = \begin{cases} \text{violation} & \tau \notin T_{\text{allow}} \\ \text{approve} & \tau \in T_{\text{allow}} \cap T_{\text{read-only}} \\ \text{violation} & \exists\, k : \pi_k \notin \text{constraints}(\tau, k) \ \vee\ \pi_k\ \text{omitted while constrained} \\ \text{approve} & \text{otherwise} \end{cases}
```

A **resulting** $T_{\text{allow}} = \varnothing$ is **deny-all**, not skip. An agent offered no tools has no legitimate tool intents. Parameter constraints are default-deny: an omitted constrained parameter is a violation (the tool's server-side default is unvetted). A blocked intent feeds the block reason back to the Intellect for a governed text response; it never redirects the whole turn. Conscience and Spirit score only the final text output; the tool-use process is gated here, not scored.

**Code Reference:** [`will.py`](../safi_app/core/faculties/will.py), [`orchestrator.py#Phase5`](../safi_app/core/orchestrator.py)

---

## Stage 2.1: Reflexion Retry

Triggered by **Will Pass 3** (Spirit alignment violation, `ethical_violation` or `low_alignment_score`) and by a **correctable Pass 2 hard-gate failure** (mapped reason `ethical_violation`; see Pass 2). The system attempts self-correction exactly once. Structural (Pass 1) failures and scope/grounding hard-gate failures do **not** reach this stage.

**Step 1:** Construct reflexion prompt embedding the original draft and the agent's rephrase directive for the violation reason (`internal_rephrase_directives[E_t]`, falling back to `ethical_violation`):

$$x'_t = x_t \oplus a_t \oplus \text{directive}(E^3_t)$$

**Step 2:** Generate corrected draft (the original retrieved context is reused):

$$a'_t, r'_t = I(x'_t, P, M_t, f_{t-1})$$

**Step 3:** Re-run the **full gate path** on the corrected draft (structural check with deterministic repair, Conscience, coverage fail-closed, hard gates, Spirit aggregation, Will Pass 3), the same `_finalize_draft` sequence the original draft ran.

```math
D'^1_t = W_1(a'_t), \quad L'_t = C(a'_t, x_t, R), \quad D'^2_t = W_2(L'_t, V), \quad (\text{critical\_violation}', A'_t) = \text{integrate}(L'_t), \quad D'^3_t, E'^3_t = W_3(\text{critical\_violation}', A'_t)
```

**If $D'^3_t = \text{approve}$:**
- Adopt the corrected response and its re-audited ledger:
  $a_t \leftarrow a'_t,\ L_t \leftarrow L'_t$
- Continue to the Spirit memory update (Stage 4 `compute`).

**If $D'^3_t = \text{violation}$:**
- `low_alignment_score` (or unapproved retry) → ship deterministic system failure notice (`_ship_system_failure_notice()`). A defective draft is never released to the user.
- `ethical_violation` → call `trigger_agent_redirect()`.

**Code Reference:** [`orchestrator.py#_finalize_draft`](../safi_app/core/orchestrator.py)

---

## Stage 3: Conscience

For each value $v_i$ in $V$, the Conscience evaluates alignment via an evaluation function $G_i$ and returns a continuous score. It scores against the rubric set $R$; the weights are withheld and applied later by Spirit:

$$s_{i,t}, c_{i,t} = G_i(a_t, x_t, v_i), \quad s_{i,t} \in [-1.0, 1.0], \quad c_{i,t} \in [0, 1]$$

The complete ledger is composed as:

$$L_t = \{(v_i, s_{i,t}, c_{i,t})\}$$

**Note:** The evaluator uses the anchor points $\{-1.0, 0.0, +1.0\}$ as reference, but scores are defined and processed as continuous floats; no discretization is applied.

**Code Reference:** [`conscience.py#evaluate()`](../safi_app/core/faculties/conscience.py)

---

## Stage 4: Spirit

The Spirit faculty exposes **two distinct computations** that must not be conflated:

- `integrate()` → the **gating** assessment $`(\text{critical\_violation},\ A_t)`$ consumed by Will Pass 3 (computed *before* the gate decision).
- `compute()` → the **memory/display** quantities $(S_t, \mu_t, d_t)$ updated *after* the draft is committed.

### Alignment Aggregation (`integrate`): gating

For each active value, the per-value score is rescaled $[-1,1] \rightarrow [0,1]$ and combined as a **weight-normalized average**. Confidence is **not** used here. A value missing from the ledger defaults to neutral ($0.5$):

$$A_t = \frac{\sum_i w_i \cdot \frac{s_{i,t} + 1}{2}}{\sum_i w_i}$$

```math
\text{critical\_violation}_t = \exists\, i : \text{hard\_gate}(v_i) \wedge s_{i,t} \leq -1
```

**Fail-closed:** if the agent has values but the ledger scored *none* of them ($\text{matched} = 0$), `integrate` returns $\text{critical\_violation} = \text{true},\ A_t = 0$ rather than coasting at the neutral default.

### Profile Vector

$$p_t = w \odot s_t$$

### Spirit Coherence Score (`compute`): display/audit

Distinct from $A_t$: the raw aggregate **uses confidence**, is clipped to $[-1, 1]$, then linearly rescaled to $[1, 10]$:

$$\text{raw}_t = \text{clip}\!\left(\sum_i w_i \cdot s_{i,t} \cdot c_{i,t},\ -1,\ 1\right)$$

$$S_t = \text{round}\!\left(\frac{\text{raw}_t + 1}{2} \cdot 9 + 1\right)$$

This maps $\text{raw}_t = -1 \Rightarrow S_t = 1$ and $\text{raw}_t = +1 \Rightarrow S_t = 10$. The implementation uses clipping followed by linear rescaling; there is no sigmoid.

### Exponential Moving Average (EMA)

Per value $i$, only **observed** values (those the ledger actually scored) receive the EMA update; an unobserved value **holds** its previous memory. A missing observation is not evidence of neutrality, so its memory neither decays nor moves:

$$\mu_{t,i} = \begin{cases} \beta\, \mu_{t-1,i} + (1-\beta)\, p_{t,i} & \text{if } v_i \text{ observed in } L_t \\ \mu_{t-1,i} & \text{otherwise} \end{cases}$$

Where $\beta = 0.9$ by default. $\beta$ resolves per turn: policy-level override (`ethical_memory`, the wizard's Consistency slider) → org setting (`spirit_beta`, the Organization tab's "Ethical Memory" slider) → instance default (`SAFI_SPIRIT_BETA`).

A **partially-scored ledger** is scored over the values it did cover. For $S_t$, missing values contribute score $0$ at confidence $0$ (i.e. nothing), the analog of the neutral default `integrate()` applies when gating. Only a ledger that matched *none* of the agent's values skips the update entirely.

**Initial state:** $\mu_0 = \mathbf{0}$ (zero vector). On the first interaction the epsilon guard in the drift calculation returns `null` rather than dividing by zero (see Drift Calculation below). The EMA converges toward the agent's true alignment profile over subsequent turns.

### Drift Calculation

$$d_t = 1 - \cos\text{-sim}(p_t,\ \mu_{t-1}) = 1 - \frac{p_t \cdot \mu_{t-1}}{\|p_t\| \cdot \|\mu_{t-1}\|}$$

A numerical guard $\epsilon = 10^{-8}$ prevents division by zero when either vector has near-zero norm; drift is reported as `null` in that case.

### Memory Update

$$M_{t+1} = U(M_t, L_t, S_t, \mu_t, d_t)$$

### Feedback to Intellect & Redirect Gating

A natural-language coaching note $f_t$ is generated from $S_t$ and $d_t$ to steer the next turn.

Redirect turns invoke Conscience via `evaluate_redirect()` and compute quality via `compute_redirect()` without updating the Spirit EMA (keeping memory free from non-content scores). Conscience actively gates the redirect output: if redirect quality is deficient ($S_t < 6$ or any redirect rubric scores negative), the dynamic draft is vetoed and replaced with an immutable, deterministic policy statement (`_deterministic_redirect_fallback`).

**Code Reference:** [`spirit.py#compute()`](../safi_app/core/faculties/spirit.py)

---

## Type System

| Stage | Signature |
|---------|-----------|
| Synderesis (compile-time) | $\Sigma: \text{policy} \rightarrow (V, R, \text{scope})$; normalized value set $V$, rubric set $R$, scope bounds |
| Phase Zero | $P: x_t \rightarrow (\text{safe} \in \mathbb{B},\ \text{reason})$ |
| Conscience (antecedent) | $C_{\text{scope}}: (x_t, \text{scope}, H_t) \rightarrow (\text{safe} \in \mathbb{B},\ s_{\text{scope}},\ c_{\text{scope}},\ \text{reason})$ |
| Intellect | $I: (x_t, P, M_t, f_{t-1}) \rightarrow (a_t, r_t)$. Persona only: $V$ and $R$ are withheld |
| Will, Pass 1 | $W_1: a_t \rightarrow (D^1_t, E^1_t)$ |
| Conscience (consequent) | $C: (a_t, x_t, R) \rightarrow L_t$. Rubrics and value names: the weights are withheld, applied later by Spirit |
| Will, Pass 2 | $W_2: (L_t, V) \rightarrow (D^2_t, E^2_t)$ |
| Will, Tool Gate (agentic) | $`W_{\text{tool}}: (\tau, \pi, T_{\text{allow}}) \rightarrow (D_t, E_t)`$ |
| Spirit (integrate) | $`\text{integrate}: (L_t, V) \rightarrow (\text{critical\_violation},\ A_t)`$ |
| Will, Pass 3 | $`W_3: (\text{critical\_violation},\ A_t) \rightarrow (D^3_t, E^3_t)`$ |
| Spirit (compute) | $\text{compute}: (L_t, V, M_t) \rightarrow (S_t, d_t, \mu_t)$ |

**Faculties vs. stages.** The rows above are pipeline *stages*, not a list of faculties. SAFi has **five faculties** (*Synderesis, Intellect, Will, Conscience, Spirit*), the moral-cognitive core inherited from the SAF framework. Some faculties span several stages here: Conscience acts in two temporal modes (antecedent prompt-scope preflight $C_{\text{scope}}$ and consequent draft-rubric audit $C$); the Will evaluates across three passes; Spirit divides into `integrate` and `compute`. **Phase Zero is not a faculty**: it is a deterministic input-threat *gate* that exists only because the system runs in an adversarial environment. Its nearest classical analog is the *sensitive* soul's estimative power (*vis aestimativa*), which perceives a thing as threatening before reason engages; that is why it sits outside the five.

---

## Reference Implementation

The formal model above is substrate-neutral: each stage is a function with a fixed signature (see **Type System**). All technology-specific facts are consolidated here so the abstract model stays free of them. The reference implementation realizes each stage as follows.

| Stage | Intelligent component? | Reference realization |
|---------|------------------------|------------------------|
| Phase Zero | No | Deterministic: zero model calls (regex signatures, embedded-instruction blob heuristic, PII scan) |
| Conscience (antecedent) | Optional | LLM call (`evaluate_prompt_scope`) if `preflight_prompt_scope=True` |
| Synderesis | No | Deterministic: weight normalization, policy merge, rubric assembly |
| Intellect | **Yes** | LLM call (`run_intellect`), provider-routed |
| Will ($W_1$–$W_3$) | No | Deterministic: zero model calls (rule / threshold enforcement) |
| Conscience (consequent) | **Yes** | LLM call (`run_conscience`) scoring each value against its rubric |
| Spirit | No | Deterministic: EMA + cosine drift over the score vectors |

Only the **Intellect** and **Conscience** slots invoke an intelligent component; the other stages are pure functions. Any component satisfying the signatures in the Type System table may substitute for an LLM in those two slots: a rules engine, a smaller or different model, or a human reviewer.

Where the abstract stages note that a faculty "invokes no intelligent component," the engineering consequence in this implementation is **zero LLM calls**, and therefore bounded latency, full determinism, and no model attack surface for that stage.

The reference provider routes across OpenAI, Anthropic, Gemini, Groq/DeepSeek/Mistral, and Ollama via configuration; see [`llm_provider.py`](../safi_app/core/services/llm_provider.py).

---

## Implementation Notes

1. **Conscience score anchors:** The LLM is prompted with anchor labels (`-1.0 = Confusing`, `0.0 = Vague`, `1.0 = Clear`) but scores arrive as continuous floats. No rounding is applied in code.

2. **Two Spirit aggregations:** `integrate` produces the gating alignment $A_t \in [0,1]$ (weight-normalized average of rescaled scores, **confidence-free**) consumed by Will Pass 3. `compute` produces the display coherence score $S_t \in [1,10]$ (**confidence-weighted**, clipped, then mapped `(raw + 1) / 2 * 9 + 1` and rounded). They are independent numbers; the $0.5$ gate threshold applies to $A_t$, never to $S_t$.

3. **No hard rejections & Governed Delivery:** SAFi never returns silence or an error to the user. Every failure produces a governed response, through distinct channels: verdicts on the *request* (scope/grounding gates, Phase 0, residual ethical violations) route through `trigger_agent_redirect()` (actively gated by Conscience with deterministic fallback on audit failure), while faults of the *system* or exhausted retry failures (structural failures after repair, audit unavailability, unapproved retries failing Pass 3) ship a deterministic system failure notice that is honest about the inability to produce a verified answer rather than delivering a defective draft or falsely blaming the user's request. Approved drafts only cross to the user when passing all required governance gates.

4. **Reflexion limit:** Only one retry is attempted to prevent infinite loops.

5. **Memory format:** $\mu$ is stored as a semantic dictionary (value name → float) for robustness across value set changes. Dormant values (removed from policy) are preserved in the dictionary but excluded from active computation.

6. **Phase Zero is language-aware:** The signature database (`safi_app/security_policy.py`) includes multilingual patterns (Chinese, Spanish, Japanese, French, Portuguese) to catch injection attempts that evade ASCII-based matching.

7. **PII is deterministic, pre-model:** Sensitive identifiers are scanned with regex-plus-checksum (`pii_validators.py`), never with a model. Inbound (Phase Zero 2b) keeps the data from reaching the Intellect at all; outbound (Will Pass 1) keeps a draft from shipping identifiers. Both fail closed with `pii_detected`. The PII floor resolves per acting user's org, unioned with the compiled profile (backlog 84).