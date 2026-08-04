---
title: Introducing SAFi
slug: safi
tags: ["safi", "overview"]
summary: Open source, self-hosted, and independent of your model provider. You declare the values; SAFi enforces them on every turn — before an answer ships and before any tool runs — records every decision, and measures whether your agents hold to those values over time.
version: 1.0
---

# Introducing SAFi

### The Runtime Governance Engine for Agentic AI

Open source, self-hosted, and independent of your model provider. You declare the values; SAFi enforces them on every turn — before an answer ships and before any tool runs — records every decision, and measures whether your agents hold to those values over time.

### The problem

Your organization is deploying AI agents, and legal and compliance are asking hard questions. How do we enforce our AI policy? How do we know the agents actually follow it? How do we catch drift and prevent unauthorized actions? How do we prove any of it to an examiner?

The answers usually live in a policy document — a PDF on an intranet. Nothing in your AI stack reads it, and nothing checks a response against it.

The industry's answer to that gap is the filter. Guardrails inspect output: they can tell you a filter fired, not whether your policy was upheld. When the answer to *who approved this response?* is *a content filter*, the governance conversation is over.

### What SAFi does instead

SAFi governs agents with the instruments you already use — a charter, policies, supervision, and a record.

An agent can be governed by your **Organizational Charter**, by a specific **Policy** for a business unit, or by both. Charter values are not background context the model may weigh if it feels like it: they are compiled into the value set the agent is scored against, taking a fixed share of every evaluation — 40% by default, configurable per organization.

Enforcement is deterministic. Every response is drafted, evaluated value by value against the governing policy, then approved, blocked or redirected by rules rather than vibes, *before* it ships.

And every one of those decisions leaves evidence. Each turn produces an encrypted governance record — the draft, the evaluation ledger, the enforcement decision, and the exact policy version in force — journaled to a hash-chained audit trail. That record feeds an **Audit Hub** for analytics and drill-down, a **supervisory review queue** for human oversight, and custody-logged exports for whoever comes asking.

### **The Five Principles Behind SAFi**:

### Who this is for

Three groups tend to arrive here for different reasons. In practice they also arrive in this order: engineers establish that it works, leadership decides whether it is worth it, and governance practitioners judge whether the evidence it produces is any good.

#### Platform engineering

You own the infrastructure where the agents actually run, and you feel the integration pain across models, frameworks and tools. **SAFi adds a deterministic governance layer to your AI agents without tying your policies or your audit history to a single model provider.**

It does not require rebuilding your stack. The [`/evaluate` gateway](https://github.com/jnamaya/SAFi/blob/main/docs/DEVELOPER_GUIDE.md#9-the-evaluate-gateway) governs the output of an agent you have already built — your orchestration stays where it is, and SAFi sits in front of the response. If you would rather run the whole thing, the [Quick Start](https://github.com/jnamaya/SAFi#quick-start) is Docker plus a database and nothing else.

#### IT directors and technology leaders

You may not deploy this yourself, but you decide whether it is a sound bet. **SAFi keeps your organisation's values in control of AI behaviour, preserves an auditable record of decisions, and holds that governance in place when the underlying models change.**

The portability is the strategic point. Your charter, your policies and your audit trail live in *your* database, not a provider's — so switching or upgrading a model does not restart your governance or orphan your evidence. The [readiness documents](https://github.com/jnamaya/SAFi/blob/main/docs/SEC_COMPLIANCE_READINESS.md) set out what ships today against what is still roadmap, which is the honest version of that conversation.

#### AI governance practitioners

You already know what a policy should do; the gap is making it operate. **SAFi turns organisational values into enforceable runtime policy, preserves the evidence behind every decision, and measures behavioural drift against the standard you defined.**

The clearest way to judge that is a worked example rather than a claim: [a governed agent built for a real organisation](https://selfalignmentframework.com/building-a-mission-aligned-agent-with-safi/), showing its value set, the answer it produced, the value-by-value ledger with a confidence figure on each score, and the audit entry for that turn. Policies are versioned, and the version in force is recorded with the decision. The [specification](https://selfalignmentframework.com/safi-math-specification/) has the arithmetic, including what each faculty is deliberately denied.

### How a governed turn runs

Values are settled before the turn begins and held read-only while it runs. Then the loop runs — and the Will is consulted at five separate points, because governing an agent that can *act* means authorising before the action, not reviewing after the result.

### Built for regulated industries

SAFi's architecture was designed for auditability first, which is why it maps onto the strictest AI and record-keeping regimes. Each readiness document states exactly what ships today and what remains on the roadmap.

**The honest fine print:** these are platform capabilities designed to *support* a compliance program, not substitutes for one. Contractual items — BAAs and zero-data-retention agreements with model providers, SOC 2 attestation — remain the deploying organization's to execute.

### SAF and SAFi

**SAF** — the Self-Alignment Framework — is the philosophical framework underneath: five faculties describing how anyone, a person or an institution, moves from what they believe to what they actually do. It was conceived before AI was in the picture, and it applies well beyond it.

**SAFi** is its implementation for AI: the Self-Alignment Framework Interface. SAF is the larger claim. SAFi is the proof that it works. [Read what SAF is →](https://selfalignmentframework.com/the-birth-of-the-self-alignment-framework/)

### Try it, or run it yourself

### Read more
