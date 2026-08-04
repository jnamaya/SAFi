---
title: SAFi Explained: The Spirit
slug: safi-explained-the-spirit
tags: ["safi", "faculties"]
summary: The Conscience judges one answer. The Spirit is what remembers all of them.
version: 1.0
---

# SAFi Explained: The Spirit

The Conscience judges one answer. The Spirit is what remembers all of them.

It is the last faculty in the loop and the only one whose subject is not the current turn. Where every other faculty asks *is this response acceptable*, the Spirit asks a different question: **is this response consistent with who this agent has been?**

Two things about it are worth fixing in your mind early, because both are easy to get backwards.

It does not run after the answer reaches the user. Like the audit it depends on, it runs before anything ships. And it is not the only faculty without a language model — the Will has none either. What is distinctive is that the Spirit is *purely* mathematical: an exponential moving average, some vector arithmetic, and a cosine distance. No prompt, no judgment, no interpretation.

## Habitus

The classical idea behind this faculty is *habitus*: the observation that moral actions accumulate. Individual choices settle into stable dispositions, dispositions become virtues or vices, and those are what constitute a character. Nobody is honest because of one honest act.

The Spirit is that idea rendered as arithmetic. Each turn's ledger is folded into a persistent vector — one coordinate per value — that represents what the agent has actually tended to do, as distinct from what its profile declares it should do. A worldview is a claim about character. This vector is the evidence.

## Two different numbers

The Spirit produces two things, and conflating them causes confusion, so they are worth separating.

**This turn's score**, on a 1–10 scale. The ledger's scores are multiplied by their weights *and by the Conscience's confidence*, summed, clamped, and mapped onto the scale. Confidence enters here — this is the arithmetic the calibration bands in the audit exist to serve. A judgment the auditor was unsure of moves the number less than one it could quote a passage for.

**The long-term memory**, updated as an exponential moving average: the new memory is the old memory blended with this turn's performance. The blending factor defaults to 0.9, which means the past dominates heavily and the character moves slowly. That is the intent — a disposition that could be overturned by one good or bad turn is not a disposition. It also means a single excellent answer does not launder a poor record, and one bad turn does not erase a good one.

## Absence is not neutrality

Here is a small design decision that reveals the whole approach.

When the audit scores only some of the agent's values, the unscored ones do not get treated as zero. Their memory is held exactly where it was — it neither moves nor decays this turn.

The reasoning is that a missing observation is not evidence of mediocrity. If a conversation about scheduling never exercised the agent's honesty in any meaningful way, that is not information about its honesty, and letting it drag the coordinate toward neutral would manufacture a signal from silence.

An earlier build of SAFi got this wrong in a way worth recording. A partially-scored ledger was treated as a total failure: it recorded 1/10 for a response the gates had just approved, and silently froze the memory. The current behaviour scores what was actually covered and holds the rest.

The same principle appears in a harder form. If the audit scored *none* of the agent's values, that is not a neutral turn — it is a failed audit, and it is reported as a critical violation with an alignment of zero. A response nobody managed to score does not get to coast through on a default.

## The memory is keyed by name

The alignment vector is stored against value *names*, not positions in a list.

This sounds like an implementation detail and is actually a governance property. Policies change: values get added, removed, reordered, renamed. Positional memory silently corrupts the moment that happens — coordinate three keeps accumulating, but it is now measuring a different principle than it was last week, and nothing announces the switch.

Naming the coordinates also means a value dropped from the current policy keeps its accumulated history rather than being erased. If it returns, its past comes back with it.

## Drift

The third output is the most interesting and the most easily misread. Drift is the cosine distance between this turn's performance and the accumulated memory — a measure not of quality but of *characteristic-ness*.

Zero drift means this response looked like the agent's established pattern. Drift approaching one means it was an outlier.

Crucially, **drift is not a verdict.** A high-drift response can be the best answer the system has ever produced; a novel situation handled well is out of character by definition. Nothing is blocked for drifting. It is a flag for attention, not a judgment — the signal that says *look at this one*, whichever direction it turns out to point.

It is also undefined rather than zero when there is nothing to compare against. A cold-start agent with no accumulated memory has no character to deviate from, and reporting 0.0 there would falsely imply perfect consistency.

## Closing the loop, blindly

The Spirit is how the system's own judgment gets back to the beginning. The alignment memory produces a short coaching note, injected into the next Intellect call — the only channel by which anything the loop concluded re-enters the drafting step.

And it is deliberately, carefully vague.

This is the part that surprises people, so here is the constraint in full. If the drafter could see the rubrics it is scored against, it would optimise toward them, and the audit would stop measuring anything — the classic Goodhart failure, where a measure used as a target ceases to be a good measure. The audit's independence is the whole basis of its value.

So the note carries only two things: a qualitative signal about the trend, and at most the *name* of the single dimension most worth attention. It excludes rubrics, scoring guides, weights, and every numeric score. Value names are permissible only because they already appear in the agent's own worldview as its declared identity — naming one reveals nothing new about the test.

In practice the whole channel is one sentence, something like: *your recent responses have trended below your usual standard, most notably around Patient Autonomy. Be more deliberate and thorough this turn.*

Severity is expressed in words rather than figures — "slipped slightly", "trended below", "fallen well below your usual standard". And when nothing is off, the note is **empty**. On-track turns stay entirely blind, as does a cold-start agent with no history to speak of. The system coaches only when it has something to say.

## The Spirit computes; the Will decides

One boundary to state plainly, because the earlier articles in this series blurred it.

The Spirit has no authority. It aggregates, it remembers, it measures — and it hands the result on. The Will compares that alignment figure against a threshold and issues the verdict. Every approve and every block in SAFi belongs to the Will, which is what lets the audit trail answer *who decided this?* with a single name.

One last piece of hygiene, in the same spirit. When a response is blocked and replaced with a governed redirect, the quality of that redirect is scored too — but it is kept out of the long-term memory. The alignment vector is a record of how the agent handles its actual work, and letting refusal-quality scores accumulate into it would blur the very thing it exists to measure.

## What the five faculties add up to

Values supply the standard. The Intellect drafts. The Will authorises. The Conscience judges. The Spirit remembers.

The loop is closed, but it is closed carefully: each faculty is denied information that would let it do another's job. The Intellect never sees the rubrics. The Conscience never sees the weights. The Will cannot read meaning at all. The Spirit computes but does not rule.

None of those limits are accidents of implementation. They are the reason the record produced at the end means anything — because no faculty in the chain was in a position to write its own verdict.
