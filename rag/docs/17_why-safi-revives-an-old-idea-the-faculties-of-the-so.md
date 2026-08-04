---
title: Why SAFi Revives an Old Idea: The Faculties of the Soul
slug: why-safi-revives-an-old-idea-the-faculties-of-the-soul
tags: ["safi", "faculties", "philosophy"]
summary: When people hear that SAFi is built around Values, Intellect, Will, Conscience, and Spirit, the language can sound unusual. The terminology is partly classical, but the engineering problem is modern: How do you govern an AI agent’s reasoning and actions at runtime in a way that is structured, inspec
version: 1.0
---

# Why SAFi Revives an Old Idea: The Faculties of the Soul

When people hear that SAFi is built around Values, Intellect, Will, Conscience, and Spirit, the language can sound unusual. The terminology is partly classical, but the engineering problem is modern:

How do you govern an AI agent’s reasoning and actions at runtime in a way that is structured, inspectable, and auditable?

SAFi uses the language of faculties to give that problem clear boundaries. Values define the standard. Intellect proposes. Will selects. Conscience evaluates. Spirit integrates.

These are not claims that a machine has a soul. They are architectural roles. Each role has a defined responsibility, restricted inputs, and an observable place in the governance process.

The result is a runtime governance engine for agentic AI, not another agent framework or prompt wrapper.

## From SAF to SAFi

The distinction between SAF and SAFi is important.

The Self-Alignment Framework, or SAF, is the conceptual framework. It explores how understanding, choice, judgment, and coherence can be represented as distinct parts of a larger process.

SAFi is the software implementation. It applies that framework as a runtime governance architecture for AI agents. SAFi evaluates proposed responses and actions against declared policies, controls access to tools, and records the decisions made during a governed turn.

In simple terms:

The classical language helps explain the architecture. The software is what makes the architecture operational.

## What is genuinely classical

The idea that human reasoning involves different faculties has a long history in Western philosophy.

Aristotle and Thomas Aquinas described the human person in terms of powers or faculties. The soul, in this tradition, was not treated as one undifferentiated capability. It included distinct powers associated with understanding, choosing, remembering, and judging.

SAFi draws on selected distinctions from that tradition, but it does not claim to reproduce it exactly.

Two of its faculties have especially clear classical parallels.

### Intellect

Intellect is the power of apprehension and understanding. It takes in information and develops an interpretation or proposed response.

In SAFi, Intellect is responsible for producing a draft or proposal. It can reason about the request, available context, and possible responses, but it is not the final authority on whether the response should be released or an action should be taken.

### Will

Will is the power of choice. It selects among available possibilities.

SAFi inherits this dependency in a practical form: Will does not independently generate meaning or invent policy. It acts on the proposals and permissions supplied by the surrounding governance process.

This separation matters because the component proposing an action should not automatically be the component authorizing it.

### Values and synderesis

Aquinas used the term synderesis for the habit associated with awareness of first moral principles. It refers to standards that are held as foundational rather than reconsidered from scratch in every individual situation.

SAFi’s Values faculty plays a related architectural role. Values establish the standards against which proposals and actions are assessed.

The analogy should not be overstated. SAFi is not claiming that its Values component is a direct software translation of Aquinas’s account. It is using a related idea for a contemporary governance problem:

> Values should define the standard an agent is expected to follow, rather than being improvised by the model during each turn.

That is the foundation of value sovereignty. The organization deploying the system defines the charter, policies, and standards. The model provider does not become the final authority over the agent’s mission.

## What SAFi adds

Not every part of SAFi’s architecture is classical.

### Conscience

Aquinas did not describe conscience as a separate faculty alongside Intellect and Will. He treated conscience as an act of intellect applying moral knowledge to a particular case.

SAFi agrees with the underlying relationship: Conscience is a reasoning function. It does not represent a supernatural property or an independent machine mind.

Where SAFi departs is architectural. It gives Conscience a separate position in the runtime process, with a different responsibility from the component that drafts the response.

Intellect proposes. Conscience evaluates.

That separation is adversarial rather than metaphysical. A reasoning process reviewing its own output can inherit the same assumptions and blind spots that shaped the original output. A separate evaluation stage creates a clearer boundary between drafting and judgment.

The separation does not guarantee that every judgment is correct. It makes the judgment process more structured, testable, and auditable.

### Spirit

Spirit is also a SAFi-specific addition.

Its design is informed by the classical idea of stable dispositions and character, sometimes discussed through the concept of habitus. But Spirit’s role as the integrator of the loop is not a direct restatement of any one classical doctrine.

In SAFi, Spirit asks whether the proposed decision remains coherent with the agent’s broader identity, charter, and operating commitments.

This supports long-term consistency. The goal is not merely to evaluate isolated turns, but to help an organization preserve a stable ethical identity as models, prompts, and workflows change.

## Five faculties, four steps

A common source of confusion is the relationship between the five faculties and the runtime loop.

Values is not one of the four sequential steps. It is the standard to which the loop remains accountable.

The four moving parts are:

Values grounds the process before and throughout the turn. It is the reference point against which the other faculties are measured.

So both statements are accurate:

The distinction is useful because it separates the governing standard from the operations that apply it.

## From faculties to runtime governance

The faculties matter because they correspond to different governance responsibilities.

### Values defines the standard

Values and policies describe what the agent is expected to preserve.

They can express requirements such as:

These standards belong to the SAFi deployment. They are not dependent on a particular model provider’s hidden preferences.

### Intellect produces a proposal

Intellect interprets the request and produces a proposed answer or action.

That proposal may include:

The proposal is not automatically approved merely because the language model generated it.

### Will selects an available action

Will selects from the actions that remain available under the system’s policies and permissions.

This distinction is especially important for agents that can use tools. The model may propose an action, but the governance layer must determine whether that action is within the agent’s allowed capabilities.

Will is therefore not an unrestricted execution path. It operates within defined boundaries.

### Conscience evaluates

Conscience evaluates the proposal against the applicable values, policies, and decision criteria.

It can identify concerns such as:

The evaluator’s role is not to rewrite the policy or quietly change the standard. Its role is to apply the standard to the case.

### Spirit integrates

Spirit evaluates coherence at the level of the whole agent.

It asks whether the decision is consistent with the agent’s broader identity, purpose, and commitments, rather than only with the immediate request.

This supports long-term consistency. An organization can compare behavior over time against its declared charter instead of relying on memory or intuition to detect drift.

## Separation of powers is the point

The faculty model is not valuable merely because the names are memorable. It is valuable because it creates separation.

A component that drafts a response should not be the sole authority deciding whether that response is acceptable. A component that evaluates a proposal should not be allowed to rewrite the governing standard without authorization. A tool gate should not need to interpret more information than necessary to determine whether an action is permitted.

In a governed turn, these boundaries can produce a record of:

That structure supports full traceability. It does not prove that every decision was correct. It gives engineers, technology leaders, and governance practitioners evidence they can inspect, test, and challenge.

This is a more useful standard than simply claiming that an agent is aligned.

## Governed actions, not only generated text

AI governance cannot stop at the final paragraph of a chat response.

Agents increasingly read files, query systems, send messages, update records, call APIs, and perform other actions on behalf of users or organizations. Those actions have different consequences from producing text, so they should not all be governed by the same standard.

SAFi treats tool use as part of the governance problem.

A proposed tool call is checked against the agent’s allow-list and applicable policies before it runs. Read operations and write operations can be held to different standards because their risks are different. The result is recorded alongside the decision that authorized or blocked it.

This matters operationally:

The important point is that the agent does not receive unrestricted authority merely because the model suggested an action.

## Why this supports value sovereignty

Many AI systems inherit important behavioral assumptions from the model provider, the agent framework, or a prompt assembled by an application team.

Those mechanisms can be useful, but they do not provide a durable governance foundation by themselves.

SAFi places the organization’s declared charter and policies in the governance layer. The deployer decides which values matter, how they are interpreted, and what actions are permitted.

That is value sovereignty:

> You decide the mission and values your AI enforces, not the model provider.

This does not mean every organization will define good policies. It means the source of authority is explicit and accountable. The values can be reviewed, versioned, tested, and changed through an intentional governance process.

## Why this supports model independence

The faculties are governance roles, not features that belong to a particular language model.

That distinction gives SAFi model independence. The underlying model can change while the charter, policies, decision process, and audit trail remain part of the organization’s governance environment.

This is important because models will continue to change. A system that embeds its governance assumptions inside one provider’s model or orchestration layer may have to reconstruct its controls whenever the model changes.

With SAFi, the governance layer can move with the organization:

SAFi does not make models interchangeable in every technical sense. Different models will have different capabilities and failure modes. It does make governance less dependent on any one model provider.

## Why the old language still earns its place

Modern psychology moved away from faculty psychology as a literal empirical account of the brain, and rightly so. There is no separate organ of the Will waiting to be found through neuroscience.

That is not the claim SAFi is making.

SAF does not assert that these faculties are biological structures. SAFi uses them as architectural distinctions: named responsibilities that can be separated, constrained, tested, and recorded.

That distinction matters. The question is not whether a machine has a soul. The question is whether a complex artificial system can be organized so that its reasoning and actions are subject to clearer boundaries.

The vocabulary turns abstract terms into operational roles:

Words such as “alignment,” “ethics,” and “responsibility” can remain vague when they are used only as aspirations. They become more useful when connected to inputs, outputs, permissions, policies, and records.

SAFi’s use of the old vocabulary is therefore deliberate but limited. It is inspired by classical distinctions, reorganized for runtime governance, and evaluated as software.

## What this architecture does not claim

SAFi does not claim that:

A governance engine can only enforce the standards that have been defined and the controls that have actually been implemented. Policies may be incomplete. Evaluators may make mistakes. Models may behave unpredictably. External systems may fail.

The value of SAFi is not that it removes uncertainty. Its value is that it makes more of the governance process explicit and reviewable.

## A practical architecture for a modern problem

SAFi revives an old vocabulary because the vocabulary gives runtime governance clear boundaries.

Values define the standard. Intellect proposes. Will selects. Conscience evaluates. Spirit integrates.

The names are historically informed, but the purpose is practical:

That is how a philosophical framework becomes a software architecture.

The best way to evaluate the claim is not to accept the vocabulary on faith. Read the implementation. Run the demo. Inspect a governed turn. Review the value-by-value ledger and the policy version in force. Examine how a proposed tool call is allowed or blocked. Compare the documented behavior with the source and the audit trail.

If the separation does not produce clearer evidence about what the agent proposed, what standard applied, and why an action was permitted or denied, open an issue and say where the architecture falls short.

SAFi is not claiming that ancient language solves AI governance. It is claiming something more practical:

> A well-defined separation of responsibilities can make agent behavior more governable, more traceable, and more accountable.

That is the idea SAFi carries forward.
