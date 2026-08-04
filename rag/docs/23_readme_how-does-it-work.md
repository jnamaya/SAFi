---
title: SAFi README: How Does It Work?
slug: readme-how-does-it-work
tags: ["safi", "readme", "safi"]
summary: SAFi's architecture is a closed loop of five interlocking faculties — Values → Intellect → Will → Conscience → Spirit — rooted in two thousand years of thinking about human cognition, from Aquinas to modern cognitive science. The structure is a separation of powers: the Intellect proposes, the Will 
version: 1.0
---

# SAFi README: How Does It Work?

SAFi's architecture is a closed loop of five interlocking faculties — Values → Intellect → Will → Conscience → Spirit — rooted in two thousand years of thinking about human cognition, from Aquinas to modern cognitive science. The structure is a separation of powers: the Intellect proposes, the Will decides, the Conscience evaluates, and the Spirit integrates.

> **Curious where the five faculties come from?** Read the origin story: [How SAF Was Born](https://selfalignmentframework.com/the-birth-of-the-self-alignment-framework/).

## The Five Faculties

| Faculty | Module | Role |
| :--- | :--- | :--- |
| **Synderesis** | `synderesis.py` | The foundational compiler. Establishes immutable baseline rules, governance policies, scope boundaries, and value weights for every agent. |
| **Intellect** | `intellect.py` | The generative engine. Drafts responses or proposes tool calls. Operates entirely within an **Air Gap**: it can only produce *intents*, never execute them directly. |
| **Will** | `will.py` | Approves or vetoes the Intellect's proposals based on structural checks and the Conscience's mathematical ledger. |
| **Conscience** | `conscience.py` | The evaluator. It evaluates the Intellect's proposal against the agent's rubrics, generating a precise compliance ledger (−1.0 to +1.0 per value). |
| **Spirit** | `spirit.py` | The long-term memory. Integrates Conscience scores into a rolling alignment vector using an EMA, detecting behavioral drift over time and generating coaching for future turns. |

**Why these five?** See [The Faculties of the Soul](https://selfalignmentframework.com/why-safi-revives-an-old-idea-the-faculties-of-the-soul/) for what is inherited from the tradition, what is not, and why the vocabulary earns its place.

## The Seven-Phase Execution Loop

Every user prompt flows through a strict, synchronous pipeline:

| Phase | Name | What Happens |
| :--- | :--- | :--- |
| **Phase 0** | Pre-generation Gate | Before any model runs, the raw prompt is screened by deterministic threat checks, known-injection signatures, per-agent blocked-phrase lists, and an entropy heuristic. Anything flagged is redirected immediately. |
| **Phase 1** | Data Gathering | The Intellect retrieves the context it needs (RAG lookups, memory, and tool/plugin context). This runs as part of the Intellect call rather than as a separate gate. |
| **Phase 2** | Apprehension | The Intellect drafts a response or proposes a tool call. |
| **Phase 3** | Structural Will | The Will deterministically checks the draft against structural invariants (required disclaimers, allowed syntax). A failure here is sent straight to a governed redirect, with no rewrite at this pass. |
| **Phase 4** | Conscience Audit | The Conscience scores the structurally valid draft against the agent's rubrics, producing the compliance ledger (−1.0 to +1.0 per value). |
| **Phase 5** | Spirit & Alignment Gate | The Will checks the ledger for hard-gate failures. If it passes, Spirit integrates the scores into the agent's alignment vector and the Will applies the alignment threshold. A low or unethical score triggers one Reflexion retry (regenerate, then re-audit). |
| **Phase 6** | Safe Execution | The fully audited response is finalized, logged with its vector coordinates, and delivered to the user. |

For the formal model, see the full [Math Specification](https://selfalignmentframework.com/safi-math-specification/) — every formula, the two different alignment numbers, and what each faculty is deliberately denied.

---
