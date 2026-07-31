---
title: "SAFi Explained: The King Solomon Problem and Identity Drift"
slug: concepts-drift-allegory
tags: ["safi", "concepts", "drift"]
summary: Allegorical explanation of identity drift, why a moving average cannot be its own standard, and what actually guards identity in SAFi.
version: 2.0
---

# SAFi Explained: The King Solomon Problem and Identity Drift

## Core concept: the King Solomon problem
The King Solomon problem is an allegory for identity drift. It shows how a system with a strong purpose can lose coherence over time through small compromises, none of them scandalous on the day they happen. The danger is a slow erosion that ends in a fundamental shift of character.

## The allegory
King Solomon began as a wise ruler anchored in wisdom, justice, and devotion. Over decades he made many small, individually defensible compromises, such as political marriages that brought foreign gods into his kingdom. First he tolerated their worship, then he built shrines, and finally the man who built the Temple was bowing to other gods. By the end of his life his actions were incoherent with his original anchor. Identity drift is not a betrayal; it is an accumulation.

## Application to AI
Identity drift is a real failure mode for a governed agent. A prudent financial guide must not gradually become a source of speculative tips. A patient-safety-first health assistant must not slowly relax into diagnosis.

## Character as a vector
The Spirit faculty keeps a long-term memory vector, mu, holding one coordinate per value the agent is governed by. It records what the agent has actually tended to do, as distinct from what its profile declares. A worldview is a claim about character; the vector is the evidence. The memory is keyed by value name rather than list position, so changing a policy cannot silently repoint a coordinate, and a value removed from a policy keeps its history.

## Action as a vector
Each turn, the Conscience's value-by-value scores are weighted into a performance vector p_t representing that single action.

## Measuring drift
Drift is the cosine distance between the action and the accumulated character:

d_t = 1 - cos_sim(p_t, mu_{t-1})

A drift near 0 means the response looked like the agent's established pattern. Near 1 means it was an outlier. Drift is reported as undefined rather than 0.0 when there is no accumulated memory to compare against, because an agent with no history has no character to deviate from.

## Memory update
The memory evolves as an exponential moving average:

mu_t = (beta * mu_{t-1}) + ((1 - beta) * p_t)

Beta defaults to 0.9, so the past dominates and character moves slowly. A disposition that could be overturned by a single turn would not be a disposition.

## Why drift alone is not a safeguard
This is the important part, and earlier versions of this document got it wrong by claiming SAFi measures and prevents identity drift.

Character updates after every action, and drift is measured against the previous character. The baseline therefore moves toward whatever the agent has recently been doing. Each of Solomon's compromises was only slightly off from the man he was that year, because the previous years had already shifted what that meant. Solomon never had a high-drift day; he would have passed a per-turn drift check every year of his reign.

A measure that learns from what it observes cannot also be the standard those observations are judged against. It will ratify anything that arrives slowly enough. This is a limit on what any moving average can do, not a defect in the implementation.

## Drift has no authority
Nothing in SAFi is ever blocked for drifting. A high-drift response can be the best answer the system has produced, because a novel situation handled well is out of character by definition. When a turn's drift crosses the organisation's threshold, default 0.4, a drift_spike alert queues that turn for supervisory review by a human. Drift's role is to say "look at this one", never to rule on it.

## What actually guards identity
The defence against gradual drift is structural rather than statistical, and it rests on standards held outside the thing being measured.

- The Charter does not move. Organisational values are compiled by Synderesis before every turn and held read-only while the turn runs, taking a fixed share of every evaluation (40% by default). They are never blended with recent behaviour, so a hundred turns of compromise leave the Charter where it started.
- Hard gates are absolute. A hard-gate value is not weighed against anything; violating it blocks the response regardless of how healthy the averages look. No accumulation of good turns buys permission for a bad one.
- The alignment floor is fixed. The aggregated score is compared against a constant threshold, not against a trailing average of the agent's own performance.
- The record persists. Because each turn's alignment and drift are written to the audit trail, character can be compared across arbitrary spans — this month against last quarter, or against deployment day. A per-turn metric cannot see a reign-long slide; a retained history can.

Solomon's failure was not that nobody was measuring. It was that the only available yardstick was himself.

## How drift appears in the interface
Drift is surfaced to users as Consistency, computed as (1 - drift) * 100%, and displayed as N/A when drift is undefined. A turn that crossed the drift threshold appears in the review queue labelled "Consistency drop".

## Cross references
- 04 Faculties Conscience
- 05 Faculties Spirit
- 23 SAFi Synderesis
