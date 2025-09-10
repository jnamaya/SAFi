---
title: SAFi Explained: The King Solomon Problem and Identity Drift
slug: concepts-drift-allegory
tags: ["safi", "concepts", "drift"]
summary: Allegorical explanation of identity drift and safeguards in SAFi.
version: 1.0
---

# SAFi Explained: The King Solomon Problem and Identity Drift

## Core concept: the King Solomon problem
The King Solomon problem is an allegory for identity drift. It shows how a system with a strong purpose can lose coherence over time through small compromises. The danger is slow erosion of values that ends in a fundamental shift of character.

## The allegory
King Solomon began as a wise ruler, anchored in values like wisdom, justice, and devotion. Over decades, he made many small compromises such as political marriages. Each step pulled him further from his core identity. By the end of his life, his actions were incoherent with his original anchor. This illustrates how small deviations accumulate into identity drift.

## Application to AI
Identity drift is a critical failure mode for AI. A cautious financial system must not drift into speculative advice. SAFi was designed to measure and prevent such failures.

## SAFi’s solution
The Spirit faculty acts as the guardian of long term identity. It turns the abstract notion of character into mathematics by measuring whether responses stay in character.

## Character as a vector
An AI’s persona is represented by a long term memory vector μ (mu). This vector is built over thousands of interactions. For Solomon, his initial μ would have been aligned with wisdom and devotion.

## Action as a vector
Each response is represented by a performance vector p_t. This comes from the Conscience audit. For example, a pragmatic marriage may yield a p_t that drifts from devotion.

## Measuring drift
Drift d_t is the distance between the current action and the established memory. It is calculated as:

d_t = 1 – cos_sim(p_t, μ_{t-1})

A drift near 0 means the action was coherent. A drift near 1 means it was out of character.

## Memory update
The memory vector evolves with an exponential moving average:

μ_t = (β * μ_{t-1}) + ((1 - β) * p_t)

The AI’s character has high inertia. A few incoherent actions are flagged but do not reset the vector. A sustained pattern will slowly alter its character, just as with Solomon.

## Cross references
- 06 Faculties Spirit
- 05 Faculties Conscience
