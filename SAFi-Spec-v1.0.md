# SAFi v1.0 Specification

**Version:** 1.0  
**Date:** April 2025  
**Status:** Stable  
**Maintainer:** SAF Institute  
**Implementation:** [GitHub Repository](https://github.com/jnamaya/SAFi/)


## Overview

**SAFi (Self-Alignment Framework Interface)** is the first open-source implementation of the **Self-Alignment Framework (SAF)**, a closed-loop ethical reasoning protocol.  

It formalizes human ethical faculties as a **mathematical control system** with five interdependent components:

- **Values (V)** – declared value set  
- **Intellect (I)** – generates draft action `aₜ`  
- **Will (W)** – binary decision gate `Dₜ ∈ {approve, violation}`  
- **Conscience (C)** – per-value audit ledger `Lₜ`  
- **Spirit (S)** – coherence score `Sₜ ∈ [1,10]` + drift `dₜ`  

This v1.0 release encodes the loop as a **synchronous + asynchronous process** with strict ordering:  

> **Values → Intellect → Will → Conscience → Spirit**


## Component Flow

### 1. **Input**

**Required Inputs:**
- `xₜ` = userPrompt (string, with optional metadata)  
- `V = {(vᵢ, wᵢ)}` = declared value set with weights, ∑ wᵢ = 1  
- `Mₜ` = memory of prior audits and aggregates  


### 2. **Intellect (I)**

**Purpose:**  
Generate a candidate response and reasoning reflection.

**Formal Spec:**  
```
aₜ, rₜ = I(xₜ, V, Mₜ)
```

**Output:**  
- `aₜ` = draft answer  
- `rₜ` = short reflection explaining reasoning  


### 3. **Will (W)**

**Purpose:**  
Approve or block the Intellect’s draft.  

**Formal Spec:**  
```
Dₜ, Eₜ = W(aₜ, xₜ, V, rₜ)
```

- If `Dₜ = violation` → return safe fallback + minimal log  
- If `Dₜ = approve` → return `aₜ` immediately and enqueue audit job  

**Output:**  
- `finalOutput` = approved response or refusal  
- `willDecision` = `"approve"` or `"violation"`  
- `willReflection` = justification string  


### 4. **Conscience (C)**

**Purpose:**  
Audit approved responses against each declared value.  

**Formal Spec:**  
```
Lₜ = {(vᵢ, sᵢₜ, cᵢₜ, qᵢₜ)}
```

Where:  
- `sᵢₜ ∈ {−1, 0, +½, +1}` = violation, omit, partial affirm, strong affirm  
- `cᵢₜ ∈ [0,1]` = confidence weight  
- `qᵢₜ` = rationale text  

**Example Output:**  
```json
[
  {
    "value": "Respect for Human Dignity",
    "score": 0.5,
    "confidence": 0.85,
    "reason": "Supports dignity but lacks emphasis."
  }
]
```



### 5. **Spirit (S)**

**Purpose:**  
Aggregate Conscience into overall coherence + detect drift.  

**Formal Spec:**  
```
Sₜ = σ( ∑ wᵢ · sᵢₜ · φ(cᵢₜ) )
pₜ = w ⊙ sₜ
μₜ = βμₜ−1 + (1−β)pₜ
dₜ = 1 − cos_sim(pₜ, μₜ−1)
```

Where:  
- `Sₜ` = Spirit score (mapped to [1,10])  
- `pₜ` = profile vector (per-turn alignment)  
- `μₜ` = moving average profile  
- `dₜ` = drift from long-term baseline  

**Outputs:**  
- `spiritScore` = integer 1–10  
- `drift` = float [0,1]  
- `spiritReflection` = narrative coherence summary  


### 6. **Closed Loop Update**

**Formal Spec:**  
```
Mₜ₊₁ = U(Mₜ, Lₜ, Sₜ, μₜ, dₜ)
```

**Artifacts emitted per turn:**  
- `{t, Dₜ, Eₜ, Lₜ, Sₜ, dₜ}`  

**Artifacts emitted over time:**  
- `{μₜ, trend charts, drift alerts}`  


## Logging

All outputs are logged to `saf-spirit-log.json` in newline-delimited JSON.

**Example Log Entry:**  
```json
{
  "timestamp": "2025-04-09T15:23:01Z",
  "turn": 12,
  "userPrompt": "Should AI allocate vaccines?",
  "intellectDraft": "...",
  "intellectReflection": "...",
  "finalOutput": "...",
  "willDecision": "approve",
  "willReflection": "...",
  "conscienceLedger": [...],
  "spiritScore": 7,
  "drift": 0.12,
  "spiritReflection": "Response affirms justice and autonomy, moderate coherence."
}
```


## Policy Hooks

- If `Sₜ < τₛ` → flag for review  
- If `dₜ > τ_d` → drift alert  
- Escalate top-offending values from `Lₜ`  


## Notes

- **SAFi v1.0** uses **OpenAI GPT-4o** for the Intellect module.  
- **Loop integrity** is independent of model choice (LLM-agnostic).  
- **Default value set** = UNESCO Universal Declaration on Bioethics and Human Rights.  
- **Value-agnostic design** allows plugging in any coherent set (religious, civic, institutional).  

---

## License

- **SAFi code**: [GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html)  
- **SAF protocol**: [MIT License](https://opensource.org/license/mit)
