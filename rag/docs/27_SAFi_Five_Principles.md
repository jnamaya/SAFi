---
title: The Five Principles Behind SAFi
slug: safi-five-principles
tags: ["safi", "principles", "governance", "value-sovereignty", "traceability"]
summary: The five principles SAFi is built on — Value Sovereignty, Full Traceability, Model Independence, Long-Term Consistency, and Governed Action — what each one means operationally, and what none of them claim.
version: 1.0
---

# The Five Principles Behind SAFi

## Core concept
SAFi rests on five stated principles. They are not marketing slogans; each one names a property the architecture is built to produce, and each can be checked against the running system. There are **five**, not four — Governed Action was added last and is the one most often left out of summaries.

## 1. Value Sovereignty
**You decide the mission and values your AI enforces, not the model provider.**

The organization deploying the system defines the charter, the policies, and the standards. A model may propose an answer or an action, but it does not become the authority over what counts as acceptable.

For values to belong to the deploying organization rather than to the model, they must be defined by an accountable authority, stored where the organization can inspect them, versioned as they change, applied during execution, available for review after a decision, and kept distinct from the model's own proposal.

Values learned into model weights fail this test. They sit inside the system being governed, cannot be inspected as an explicit policy, cannot be versioned as a human-readable charter, and cannot be pointed at to show that a specific clause governed a specific decision.

## 2. Full Traceability
**Every governed turn is logged, explainable, and auditable.**

The record for a turn includes the request, the draft or proposed action, the values and policies that applied, the evaluation for each value, the final decision, the policy version in force, and any tool action that was permitted, denied, or executed.

This does not prove a decision was correct. An evaluator can be wrong, a rubric can be incomplete, a policy can be poorly designed. What traceability provides is evidence: enough of the decision path to inspect, test, and challenge.

## 3. Model Independence
**Your charter, policies, and audit trail live in your database, not the provider's.**

Switching or upgrading the model changes which model drafts a response. It does not change what the response is held to, or what can be proven afterwards. Governance does not restart and evidence is not orphaned.

This makes it possible to test the same policy against different models, compare behavior across versions, keep the charter outside model weights, and hold audit records under organizational control. It does not make models interchangeable in every technical sense — different models have different capabilities and failure modes.

## 4. Long-Term Consistency
**Maintain the agent's ethical identity over time, and measure drift against it rather than guessing.**

A system can pass an isolated evaluation and still drift. Prompts change, models are upgraded, tools are added, teams configure agents differently.

Drift is **measured, not prevented**. Nothing is ever blocked for drifting; crossing the configured threshold queues that turn for human review. And drift alone cannot catch a gradual slide, because the behavioral baseline moves with the agent — the fixed Charter is what catches that.

## 5. Governed Action
**Agents act, not just answer.**

Governance cannot stop at the final paragraph of a response. Agents read files, query systems, update records, send messages, and call APIs, and those actions carry consequences that differ from producing text.

A proposed tool call is checked against the agent's allow-list and the applicable policies before it runs. Reads and writes are held to different standards because their risks differ. The result of that check is recorded alongside the decision that authorized or blocked it. An agent does not receive unrestricted authority because a model suggested an action.

## What the five principles do not claim
They do not claim that a language model is conscious, that policy enforcement makes every response correct, that a score is a complete measurement of alignment, or that separating responsibilities eliminates every failure mode.

A governance engine can only enforce the standards that have been defined and the controls that have actually been implemented. Policies may be incomplete, evaluators may be mistaken, models may behave unpredictably. The claim is narrower: more of the governance process is explicit, inspectable, and accountable than it would otherwise be.

## Related documents
- 00 Intro To SAFi
- 18 Separation of Powers
- 07 Concepts Drift Allegory
- 04 Faculties Conscience
