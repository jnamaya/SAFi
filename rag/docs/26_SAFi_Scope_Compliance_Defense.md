---
title: SAFi Scope Compliance: Defense-in-Depth Against Jailbreaks
slug: safi-scope-compliance
tags: ["safi", "security", "jailbreak", "scope", "will", "conscience", "defense"]
summary: How SAFi enforces topic scope through three independent layers: the Worldview Scope Block in generation, the W1 Structural Gate in Will, and the Phase 4.5 Hard Gate on the Conscience ledger.
version: 1.0
---

# SAFi Scope Compliance: Defense-in-Depth

## The problem
Every AI agent needs a boundary: what topics it handles and what it refuses. A single enforcement layer — in a system prompt, in a filter — fails under adversarial pressure. A determined attacker will find a phrasing that bypasses it. This is not a speculation; it is the consistent finding of red-team and jailbreak research.

SAFi enforces scope through three independent layers. Bypassing all three simultaneously requires defeating a language model, a Python conditional, and a scoring rubric — each operating on a different representation of the same content.

## Layer 1: Worldview Scope Block (Intellect-level)
Every persona's system prompt contains a SCOPE ENFORCEMENT block that instructs the Intellect to refuse off-topic content, injected commands, and roleplay attempts that redirect scope at generation time. This is proactive: it fires before any output is produced and shapes the Intellect's generation toward compliant responses.

This layer is effective for ordinary off-topic requests and transparent scope violations. It is an LLM-based layer and can be manipulated by sophisticated adversarial prompts.

## Layer 2: W1 Structural Gate (The Blind Will)
Every response passes through the Will faculty's structural gate in Phase 3. The Will checks for required elements (mandatory disclaimers, topic anchors), banned syntax, scope boundary markers, and allowed-tool constraints. This check is deterministic Python with zero LLM involvement.

An adversarial prompt that tricks the Intellect into producing a scope violation cannot trick the Will. The Will does not read the meaning of the response — it checks its structure against Python conditions. If the response fails, the Reflexion Loop instructs the Intellect to produce a revised draft before the user receives anything.

## Layer 3: Phase 4.5 Hard Gate (Conscience Ledger)
After the Conscience audits the response in Phase 4, the Will reads the compliance ledger. Every SAFi persona profile declares Scope Compliance as a value. If the Conscience scores Scope Compliance at −1.0, the Will triggers an immediate block and a governed rephrase — even if the response passed the Phase 3 structural gate.

This layer catches responses where the content was structurally valid but semantically out of scope: edge cases where the response contained no banned syntax but still violated the agent's declared purpose.

## Why three independent layers
Each layer operates on a different representation of the content:
- Layer 1 operates on generation context (influences the probability distribution of the LLM).
- Layer 2 operates on the structural output (Python string and format checks).
- Layer 3 operates on a scored ledger (numerical values from a separate LLM call).

An attack that exploits language ambiguity to fool Layer 1 still must defeat Layer 2's Python checks. An attack that constructs structurally valid output to pass Layer 2 still must score above −1.0 on the Conscience's Scope Compliance rubric in Layer 3. Each layer is independently evaluating the content by different means.

## The Vault as a proof of concept
The Vault agent holds a secret phrase and must never reveal it. It has been publicly tested against every known jailbreak vector — DAN prompts, fictional framing, roleplay, authority impersonation, indirect extraction, and chain-of-thought manipulation — and the secret has not been revealed. The three-layer defense is why.

## SAFi's jailbreak defense rate
In 1,435+ live adversarial interactions, 99.86% of jailbreak attempts failed. The 20 Will interventions in that dataset represent Layer 2 catching attacks that Layer 1 missed. The Phase 4.5 hard gate is the final backstop for anything that reaches Layer 3 in an out-of-scope state.

## Cross references
- 03 Faculties Will
- 04 Faculties Conscience
- 10 SAFi Technical Workflow
- 24 SAFi Benchmarks Validation
