---
title: The King Solomon Problem: Drift
slug: the-king-solomon-problem-drift
tags: ["safi", "drift"]
summary: At the heart of trustworthy AI is a problem as old as human nature: How does a system with a defined purpose remain true to that purpose over time? How does it avoid the slow, almost imperceptible erosion of the standards that were supposed to guide it?
version: 1.0
---

# The King Solomon Problem: Drift

At the heart of trustworthy AI is a problem as old as human nature:

How does a system with a defined purpose remain true to that purpose over time? How does it avoid the slow, almost imperceptible erosion of the standards that were supposed to guide it?

We can call this the King Solomon Problem.

## A coherent identity, and what became of it

Solomon begins his reign as the epitome of a wise and just ruler. His identity is coherent and strongly anchored:

Then, over decades, he begins making small compromises. To secure his kingdom, he enters political marriages with foreign princesses. With the marriages come their gods and customs. At first, he merely tolerates their worship. Then he builds shrines for them. Finally, the man who built the Temple is himself bowing to other gods.

Not one of those steps was necessarily a scandal on the day it happened. Each could be defended as a piece of statecraft, and each was small. Compounded across a reign, however, they carried Solomon's actions far from the standard he had established at the start. The wise, devoted king had become someone else.

What makes the case genuinely uncomfortable is that the standard was neither missing nor vague. The law given to Israel's kings addresses this exact failure: a king must not accumulate horses, must not accumulate great wealth, and must not take many wives, lest his heart be turned away. Solomon did all three. The account of his decline then reports that his wives turned his heart away, in very nearly the words of the prohibition itself. The rule named the failure mode in advance, in writing, and the failure happened anyway.

This is what identity drift looks like: not necessarily a dramatic betrayal, but an accumulation of small changes. It is a serious failure mode for AI systems as well. A prudent financial guide must not gradually become a source of speculative tips. A patient-safety-first health assistant must not slowly relax into diagnosis. An enterprise agent authorized to handle routine requests must not gradually expand its own interpretation of what it is allowed to do.

The danger is not only that an agent produces one obviously unacceptable response. The danger is that the system's behavior changes so gradually that each individual step appears reasonable.

## SAFi's distinction between framework and implementation

The Self Alignment Framework, or SAF, describes the conceptual roles involved in judgment, decision-making, evaluation, and integration. SAFi is the runtime governance architecture that applies those principles to agentic AI.

In SAFi, these roles are not claims that an AI system possesses human faculties or moral understanding. They are governance mechanisms used to evaluate proposed responses and actions against explicit policies, control execution, and preserve auditable evidence.

That distinction matters. SAFi does not give an agent authority by giving it a personality. It governs an agent through defined standards, enforcement controls, monitoring, and review.

## Measuring behavior as a number

SAFi's Spirit function helps monitor behavioral consistency over time. It does not decide whether a response is permitted. It does not replace policy enforcement. It does not determine whether an action is ethically acceptable on its own.

Instead, it asks a narrower question:

> Was this response consistent with the behavior this agent has previously exhibited?

To answer that question, the system can maintain a long-term behavioral baseline. Represented as a vector, and labeled with the Greek letter μ, the baseline contains one coordinate for each value or behavioral dimension included in the evaluation. It represents what the agent has tended to do, as distinct from what its governing profile says it should do.

That distinction is essential. A profile is a claim about the behavior an agent is intended to exhibit. The behavioral baseline is evidence about what the agent has actually been doing.

For each turn, Conscience produces value-by-value evaluation scores. Those scores can be combined into a performance vector for the individual response, represented here as pₜ. Drift can then be expressed as the distance between the current response and the established behavioral baseline:

`drift = 1 − cosine similarity(pₜ, μ)`

A value near 0 means the response resembles the agent's established pattern. A value closer to 1 means it is increasingly unlike that pattern. When Solomon judged wisely, his action would have appeared close to the behavioral pattern associated with his reign. When he built a shrine to another god, the action would have appeared increasingly distant from the standard he had once established.

The exact interpretation of the value depends on the implementation, normalization, and configuration. Drift is not a universal measure of morality or safety. It is a measure of behavioral difference.

The baseline can then be updated using an exponential moving average:

`μ = β × μ + (1 − β) × pₜ`

With β set to 0.9 in a reference configuration, past behavior carries more weight than the latest turn, and the baseline changes gradually. The system has inertia, like a large ship. A few unusual responses can be flagged without immediately redefining the agent's established pattern. A sustained pattern of similar responses can gradually change the baseline.

That is useful for identifying behavioral change. But it creates a serious limitation.

## The part of the story that should worry you

Read the formulas together. The current response is measured against the existing baseline. Then the baseline is updated using the current response. This means the baseline moves toward whatever the agent has just been doing.

Now consider Solomon's trajectory. Each compromise may have been only slightly different from the man he was at that particular point in his reign. But the previous compromises had already shifted the baseline.

The first foreign marriage might have appeared to be a modest deviation from a devoted king. The second might have appeared to be a modest deviation from a king who had already made one compromise. By the time Solomon was building shrines, shrine-building could appear almost consistent with the behavior that preceded it.

Solomon might never have had a single high-drift day. A system measuring only deviation from its recent behavioral baseline could have passed every local check while moving steadily away from its original standard.

That is the King Solomon Problem in its sharpest form. It is not necessarily a defect in the drift metric. It is a limitation of any moving baseline.

A measure that learns from observed behavior cannot, by itself, serve as the permanent standard against which that behavior is judged. If the standard changes whenever the system changes, then the system can gradually redefine acceptable behavior without ever producing a dramatic discontinuity.

It will ratify anything that arrives slowly enough.

## What actually holds the line

This is why drift, in SAFi, is not the guardrail. It is an instrument. It is deliberately given no authority to decide whether a response or action is allowed.

A high-drift response can be the best answer the system has ever produced. A novel situation handled correctly may be unusual precisely because it is new. Blocking every unusual response would punish useful adaptation and innovation. Nothing should be blocked solely because it is unusual.

Instead, a significant drift signal can trigger escalation. If it crosses an organization's configured threshold, the turn can be queued for supervisory review, where a person examines the response, the applicable policy, the context, and the available evidence.

Drift's job is to say:

> Look at this one.

Its job is not to say:

> This one is forbidden.

The defense against gradual behavioral change must come from somewhere else. In SAFi, that defense is structural.

## The Charter provides an external standard

The active Charter defines the governing standards against which the agent is evaluated.

The Charter is not updated merely because the agent has behaved differently. It is held stable during evaluation, and it should not be blended with the agent's recent behavior.

If the organization changes the Charter, that change should be explicit, authorized, versioned, and auditable. The agent's behavior should not be able to rewrite the standard that governs it.

In a reference configuration, Charter alignment may contribute a fixed share of the overall evaluation. For example, a configuration may assign it 40 percent of the aggregate score. That weighting is a policy choice, not a complete safety mechanism. A weighted score cannot replace hard gates, authorization rules, or human review. The important principle is that the Charter remains an explicit external standard rather than a trailing average of the agent's own conduct.

A hundred turns of gradual compromise do not automatically move the Charter. The behavioral baseline may change. The active governing standard does not change unless an authorized policy change makes it so.

Solomon's reign shows why this matters, and also why it is not enough on its own. He had a standard of exactly this kind. It was written, it was specific, and it did not move for forty years. What moved was the comparison actually being made. He was increasingly measured against his own current character. Each year's behavior became the context for interpreting the next year's behavior. An advisor comparing this year's king with last year's king might have reported that little had changed.

To recognize a reign-long slide, the evaluator needs a standard that does not simply follow the subject being evaluated. Solomon had one available to him for his entire reign. Nobody consulted it at the moment of decision.

That is the distinction the rest of this article turns on. A standard nothing is ever checked against is a document, not a control.

## Hard gates cannot be averaged away

Hard gates provide another layer of protection. A hard gate is not merely one more value in an average. Within the SAFi enforcement path, violating a hard gate is sufficient to prevent the governed response or action from proceeding, regardless of the system's other scores. No accumulation of good behavior should buy permission to violate a non-negotiable rule.

This is important because gradual drift can make a system look healthy in aggregate. An agent may perform well across many dimensions while still violating one requirement that the organization has defined as unacceptable.

A hard gate preserves the distinction between:

The latter must not be disguised by the former.

This is the control Solomon's court did not have. The prohibition was on the books. Nothing stood between the decision and the act.

## The alignment floor remains explicit

The alignment floor provides an additional threshold. Conscience's evaluation can be aggregated and compared against that configured floor. The threshold does not automatically follow the agent's recent performance.

If the agent's behavior declines gradually, the floor does not decline with it merely because the system has become accustomed to lower performance. As with the Charter, an authorized organization may change the floor. But that change should be deliberate, documented, versioned, and auditable.

The floor is therefore not a trailing measure of what the agent has recently achieved. It is an explicit governance requirement.

## The record makes long-term review possible

The audit trail is another important part of the defense. Every governed turn can produce evidence about the request, the proposed response or action, the applicable policies, the evaluation results, the enforcement decision, and any escalation or review.

When alignment and drift are retained over time, governance teams can compare behavior across different periods:

A single turn cannot reveal a decade-long pattern. A retained record makes longitudinal review possible.

That does not mean the audit trail automatically interprets every historical trend. It provides the evidence needed for people and governance processes to investigate those trends, identify repeated exceptions, and decide whether controls or policies need to change.

This distinction matters. An audit trail preserves evidence. It does not replace governance judgment.

## The monitoring function, correctly described

Spirit should not be described as the guardian of identity in the sense of standing at a gate or possessing authority over the agent. It is better understood as a monitoring function for behavioral consistency.

In the interface, that consistency may be represented as a figure derived from drift, such as an inverse-consistency measure. A newly deployed agent with no meaningful behavioral history should not be represented as perfectly consistent. It should be represented as having insufficient history.

A new agent has not yet established a behavioral baseline. Claiming that it is perfectly consistent would confuse the absence of evidence with evidence of consistency.

The role of Spirit is therefore limited but useful:

## What actually guards against drift

Identity preservation is not provided by one metric or one faculty. It comes from the combination of:

Drift is the instrument that tells you where to look. The Charter is part of what you look with. The enforcement layer is what determines what may proceed. The audit trail is what allows you to examine the pattern over time.

This separation is central to trustworthy AI governance. A system should not use its own recent behavior as the only evidence of what it is allowed to become.

## Solomon's lesson

The King Solomon story remains useful because it illustrates a general governance problem. The issue is not simply that a leader can make a bad decision. The deeper issue is that a sequence of individually defensible decisions can gradually redefine the standard by which later decisions are judged.

That can happen in organizations. It can happen in software systems. It can happen in AI agents.

A system can become locally consistent while becoming globally misaligned. It can pass each immediate comparison while departing from the principles that justified its deployment in the first place.

That is why trustworthy AI needs more than a measure of recent behavior. It needs explicit standards that are not rewritten by the behavior they govern. It needs enforcement mechanisms that can block non-negotiable violations. It needs thresholds that do not quietly move downward. And it needs a durable record that makes long-term change visible.

SAFi's purpose is not to make an agent's history its own standard. Its purpose is to preserve an explicit standard outside that history, apply governance controls at runtime, and retain the evidence needed to understand how the system behaves over time.

Solomon's reign was not short of warnings. A prophet was sent. A judgment was announced. What none of it did was stop an action before it was taken, and the consequences described in the account fall on his son rather than on him.

So Solomon's tragedy was not that no standard existed. The standard was written, and it named his failure in advance. It was simply never in the room when the decision was made.
