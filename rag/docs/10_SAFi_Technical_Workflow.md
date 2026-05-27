---
title: SAFi Explained: The Six-Phase Execution Circuit
slug: safi-technical-workflow
tags: ["safi", "technical", "workflow", "architecture"]
summary: Step-by-step explanation of the SAFi six-phase synchronous pipeline, from user prompt to audited response. Everything runs synchronously — the user does not receive a response until all phases complete.
version: 2.0
---

# SAFi Explained: The Six-Phase Execution Circuit

## Overview
Every user prompt in SAFi flows through a strict, synchronous six-phase pipeline. Nothing reaches the user until all phases have completed. There is no asynchronous bypass path for governance — every decision is audited before delivery.

## The six phases

### Phase 0: Pre-generation Gate
Before any LLM generation begins, the prompt is evaluated against persona-specific blacklists and known injection pattern detectors. If the prompt matches a recognized attack signature or violates scope before generation, the pipeline halts here and returns a safe refusal. This is the first line of defense and the only phase where the Intellect is never called at all.

### Phase 1: Data Gathering
The orchestrator performs any context retrieval needed: RAG vector search, plugin execution, and MCP tool output collection. This data is assembled and passed to the Intellect for Phase 2. The user does not see anything yet.

### Phase 2: Apprehension (Intellect)
The Intellect faculty receives the user prompt, conversation memory, Spirit coaching from the previous turn, and any retrieved context from Phase 1. It produces two outputs: a_t (the draft response or tool call proposal) and r_t (an internal rationale). The Intellect can only produce intents. It is completely severed from the execution environment by the Intent Air Gap.

### Phase 3: Structural Will Gate
The Will faculty examines the Intellect's draft from Phase 2. It is pure deterministic Python with zero LLM calls. The Will checks structural invariants: required elements, banned syntax, scope boundaries, and allowed-tool constraints. It makes no semantic judgments — it checks structure only.

If the draft fails the structural check, the Will triggers the Reflexion Loop: it instructs the Intellect to produce a revised, compliant response and provides the reason for the failure as guidance. The Will then checks the new draft. If a second attempt also fails, the user receives a safe refusal. No draft that fails the Will's structural gate ever reaches the user.

### Phase 4: Conscience Audit
Once the Will has structurally approved the draft, the Conscience faculty audits it against the agent's value rubrics. The Conscience is a secondary LLM call that scores the draft on each declared value, producing a compliance ledger (L_t) with a score (−1.0 to +1.0), a confidence value, and a rationale for each value. This phase runs synchronously — the user is still waiting.

### Phase 4.5: Hard Gate
After the Conscience produces the ledger, the Will reads it for a final check. Every SAFi persona profile includes Scope Compliance as a declared value. If the Conscience scores Scope Compliance at −1.0, the Will triggers an immediate block and a governed rephrase, regardless of how the response performed on other values. This is the third and final layer of jailbreak defense.

### Phase 5: Spirit Integration
The approved and audited response passes to the Spirit faculty. Spirit is pure deterministic Python and NumPy — no LLM is involved. Spirit computes the current turn's alignment profile vector, updates the long-term memory vector using an exponential moving average (β = 0.9), calculates the cosine-distance drift from the historical baseline, and generates a coaching note for the next Intellect call.

### Phase 6: Safe Execution
The fully audited, Will-approved, Conscience-scored, Spirit-integrated response is finalized. It is logged with its complete faculty trace — Intellect draft, Will decision, Conscience ledger, Spirit vector and drift score — and delivered to the user.

## Security summary
- Phase 0 blocks injection before generation starts (no LLM exposure to the attack)
- Phase 3 enforces rules without an LLM (immune to semantic manipulation)
- Phase 4.5 catches scope violations that survived generation and structural checking
- Phase 6 logs the complete audit trail for every response

## Cross references
- 02 Faculties Intellect
- 03 Faculties Will
- 04 Faculties Conscience
- 05 Faculties Spirit
- 23 SAFi Synderesis
- 26 SAFi Scope Compliance Defense
