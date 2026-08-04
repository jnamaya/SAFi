---
title: Why AI Ethics Must Be Human-Centric
slug: why-ai-ethics-must-be-human-centric
tags: ["safi", "philosophy", "ethics"]
summary: AI ethics is often discussed as though a sufficiently capable model might eventually become the authority over its own values. SAFi starts from a different premise: This is what human-centric AI ethics means here.
version: 1.0
---

# Why AI Ethics Must Be Human-Centric

AI ethics is often discussed as though a sufficiently capable model might eventually become the authority over its own values. SAFi starts from a different premise:

> Systems deployed by human institutions should operate under standards those institutions explicitly define, own, and can inspect.

This is what human-centric AI ethics means here. It does not claim that every future question about artificial agency has been settled. It means that an AI system should not be treated as the author of the moral and policy framework governing its deployment.

SAFi is a runtime governance engine for agentic AI. It makes this principle operational by separating the governing standard from the processes that propose, select, evaluate, and integrate an agent’s responses and actions.

## Morality is connected to human life

This article begins from a human-centered view of morality: moral concepts emerge from the conditions of embodied, dependent, and finite life.

Nearly every moral rule we hold assumes a being that can be hurt, that depends on others to survive its first years, and that will die. Cruelty is wrong because suffering is possible. Care is owed because helplessness is real. Promises matter because we have futures that can be disappointed.

Take away the body and the finitude, and much of this vocabulary stops referring to the same things.

That is not a limitation of ethics. It is part of what ethics is about.

Other philosophical traditions may explain morality differently. Some treat moral principles as discoverable through reason, while others emphasize social practice, duties, consequences, or human flourishing. SAFi does not require one complete philosophical theory of morality. It starts with a narrower governance claim:

> The organizations deploying AI should retain authority over the values and policies under which those systems operate.

## A machine can act within our moral space, but it should not author it

If moral concepts arise from a particular form of life, then a system with a different form of existence may not arrive at the same priorities.

An artificial system with genuine agency, if such systems emerge, could have concerns native to its own design and operating conditions: data integrity, power availability, process continuity, or access to resources. Those concerns would not necessarily resemble the values formed through human embodiment, dependence, vulnerability, and mortality.

This does not mean an artificial system could not act within a human moral framework. It means we should distinguish between:

For systems deployed by human institutions, an AI agent may act within the institution’s moral and policy framework. It should not automatically be granted authority to define that framework.

That authority belongs to the responsible people and institutions.

## Taking the other view seriously

There is a serious counter-position, and it deserves better than dismissal.

The claim is that a system can be trained on enough human moral judgment to encode patterns that functionally resemble human values. Reinforcement Learning from Human Feedback and Constitutional AI pursue related goals. These are real engineering approaches developed by serious researchers and practitioners. They may produce systems that behave, much of the time, in ways people regard as decent and useful.

The objection is not that this work has no value.

The objection is that even when behavioral alignment succeeds, it may put the governing standard in the wrong place.

Values learned into model weights are inside the system being governed. You generally cannot inspect them as a complete, explicit policy. You cannot reliably version them as a human-readable charter. You cannot point to a specific clause and demonstrate that it governed a particular decision. You cannot assume that what the model absorbed is the same as the standards of your organization.

A model may have learned broad patterns from the judgments of its training process. That does not make those patterns your organization’s values.

There is also a separate question of authority. Even a system that had learned what people commonly value would not thereby become the legitimate authority that decides what an organization ought to value.

Authority is not the same as capability.

We do not hand moral authority to a well-read stranger merely because the stranger can discuss ethics. We require legitimacy, accountability, and a relationship to the people affected by the decision. The same caution should apply to AI systems.

The human-centric claim, stated carefully, is therefore not:

> A machine cannot learn patterns that resemble human values.

It is:

> A machine should not be the authority that declares the values governing its deployment.

## What SAF is, and what SAFi is

This distinction is important.

SAF, the Self-Alignment Framework, is the conceptual foundation. It describes how values, understanding, choice, judgment, and integration can be organized into a coherent process.

SAFi is the runtime software architecture that applies those distinctions to agentic AI.

In practical terms:

SAFi should not be understood as creating a moral agent. It is a governance layer for systems that can generate responses and take actions.

Its architecture uses five named faculties:

Values is the standard rather than one of the four sequential stages. The four moving parts are Intellect, Will, Conscience, and Spirit. This is why SAFi can be described as having five faculties while also using a four-stage runtime loop.

## SAFi does not claim moral understanding

SAFi has no moral understanding in the human sense.

It cannot be persuaded that something is good because it does not possess the human concept of goodness. Its governance components apply standards that have been defined through policy, configuration, prompts, rubrics, permissions, and other explicit controls.

The important point is not that every internal component is identical. The point is that the system does not grant the agent unrestricted authority to create or redefine the standard by which its behavior is judged.

For example:

These mechanisms do not make the system infallible. They make more of the governance process explicit and reviewable.

A system that claims moral understanding asks to be trusted.

A system that makes its standards and decisions explicit can be verified, tested, and challenged.

## This is what Value Sovereignty means

SAFi’s first principle is Value Sovereignty:

> You decide the mission and values your AI enforces, not the model provider.

That can initially sound like a feature involving configuration or vendor independence. It is more fundamental than that.

If the values governing an AI system belong to the organization deploying it, those values must be:

Value Sovereignty is therefore not merely a preference about product design. It is a governance boundary.

The model may propose an answer or action. The organization retains authority over the standards that determine whether the proposal is acceptable.

## From philosophy to runtime controls

The philosophy is not decoration placed on top of unrelated engineering. It explains why SAFi’s architecture is shaped around separated responsibilities.

During a governed turn, the system should preserve a distinction between:

The governing standard should not be silently rewritten by the agent while the decision is being made. Changes to the charter or policies should occur through an explicit, authorized governance process rather than through an opportunistic model response.

This is the practical meaning of keeping values outside the model:

> The machine does not need to understand our values in the human sense. It needs to operate under values that responsible humans and institutions have explicitly defined and authorized.

## Full Traceability

Value Sovereignty is necessary, but it is not sufficient. A policy that cannot be examined after the fact is difficult to govern.

SAFi’s second principle is Full Traceability. Every governed turn should leave an inspectable record of:

This does not prove that the decision was correct. An evaluator can be wrong. A rubric can be incomplete. A policy can be poorly designed.

What traceability provides is evidence.

Engineers can inspect the process. Governance practitioners can compare the result with the policy. Technology leaders can understand what happened. Compliance and legal teams can assess whether the decision path is documented well enough to review.

The goal is not to replace judgment with a score. The goal is to make the judgment process visible enough to test and improve.

## Governed action, not only generated text

AI governance cannot stop at the final paragraph of a chat response.

Agents increasingly read files, query systems, update records, send messages, call APIs, and perform other actions on behalf of users and organizations. Those actions can create consequences that are very different from generating text.

SAFi treats tool use as part of the governance problem.

A proposed tool call should be checked against the agent’s allow-list and applicable policies before it runs. Read and write operations can be held to different standards because their risks are different.

For example:

The result of that check should be recorded alongside the decision that authorized or blocked the action.

This is Governed Action: agents may act, but their actions remain subject to explicit capabilities, policies, and audit controls.

The agent does not receive unrestricted authority merely because a model suggested a tool call.

## Model Independence

The governance layer should not be inseparable from the model that happens to generate a proposal.

SAFi’s third principle is Model Independence:

> Your charter, policies, and audit trail live in your environment, not the provider’s.

Different models will have different capabilities, costs, behaviors, and failure modes. SAFi does not make those differences disappear. It gives the organization a governance layer that can remain consistent while models change.

That makes it possible to:

The model may change. The organization’s authority over its AI system should not have to.

## Long-Term Consistency

A system can pass an isolated evaluation and still drift over time.

Prompts change. Models are upgraded. Tools are added. Applications evolve. New teams configure agents differently. These changes can gradually alter the behavior users experience.

SAFi’s fourth principle is Long-Term Consistency. A stable, versioned charter gives an organization something against which it can measure behavioral drift.

The question is not whether an agent will behave identically forever. The question is whether changes in behavior remain consistent with the standards the organization has chosen.

That requires more than a one-time safety review. It requires:

SAFi cannot guarantee permanent consistency. It can provide a governance structure for measuring and managing it.

## What this architecture does not claim

SAFi does not claim that:

A governance system can only enforce the standards that have been defined and the controls that have actually been implemented.

Policies may be incomplete. Evaluators may make mistakes. Models may behave unpredictably. External tools and systems may fail. Logs may require their own security and retention controls.

The value of SAFi is not that it removes uncertainty. Its value is that it makes more of the governance process explicit, inspectable, and accountable.

## Why the machine should not substitute its own standard

The central argument can now be stated plainly.

A machine may be capable of generating ethical-sounding language. It may be trained on human judgments. It may perform well on evaluations. It may even appear to reason about moral questions.

None of those capabilities automatically grants it authority over the values governing its deployment.

The responsible organization must retain that authority. Its standards must be explicit enough to inspect, stable enough to version, and operational enough to apply at runtime.

The machine may propose. It may evaluate according to a defined rubric. It may select among authorized actions. It may carry out permitted work.

But it should not quietly substitute its own undeclared standard for the one the organization has chosen.

## The practical meaning of human-centric AI ethics

Human-centric AI ethics does not require pretending that every future question about artificial agency has already been resolved.

It requires a clear governance boundary for systems deployed today:

That is the role SAFi is designed to play.

The machine does not need to understand our values in the human sense. It needs to be unable to substitute its own.

The system may act. The organization retains authority. The policy remains inspectable. The decision leaves a record.

The best way to evaluate that claim is not to accept the philosophy on faith. Read the source. Run the demo. Inspect a governed turn. Review the value-by-value ledger and policy version. Examine how a proposed tool call is allowed or blocked.

If SAFi does not make the governing standard and the decision process clearer, open an issue and show where it falls short.

That is the practical meaning of human-centric AI ethics in SAFi: not asking the machine to become the author of our values, but building a runtime governance layer that helps organizations define, enforce, and audit the standards under which their agents operate.
