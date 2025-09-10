---
title: SAFi Explained: The Spirit
slug: faculties-spirit
tags: ["safi", "faculties", "spirit"]
summary: Spirit faculty: long-term identity and memory; integrates audits into patterns, tracks alignment and coherence; produces Spirit score S_t.
version: 1.0
---

# SAFi Explained: The Spirit

## Core concept: role of the Spirit
The Spirit is the integrator and long term memory of the SAFi loop. It acts as the historian of ethical performance. After the Conscience audit, the Spirit integrates the results to identify patterns, update the ethical character, and give feedback to close the loop.

## Core functions
The Spirit takes the ledger L_t from the Conscience and performs three main functions.

1. Calculate the Spirit score (S_t): a single coherence score.  
2. Update the long term memory (μ_t): the memory vector that evolves over time.  
3. Measure ethical drift (d_t): the deviation from the system’s character.

## Spirit score
The score is a weighted average of the value scores s_i,t and their confidences c_i,t. It produces a single metric of coherence, typically scaled from 1 to 10.

## Long term memory
The Spirit updates the memory vector μ using an exponential moving average:

μ_t = (β * μ_{t-1}) + ((1 - β) * p_t)

- μ_t: new memory state  
- μ_{t-1}: previous memory state  
- p_t: performance vector from the current audit  
- β: smoothing factor controlling adaptation

## Ethical drift
Drift d_t measures how out of character a response was compared to μ_{t-1}. It is calculated as:

d_t = 1 – cos_sim(p_t, μ_{t-1})

A drift of 0 means the action was fully in character. A drift near 1 means it was a strong outlier.

## Closing the loop
After updating memory, the Spirit produces feedback for the Intellect. This coaching highlights which values to emphasize in the next response. Lessons from each audit feed back into generation, so the system adapts while preserving its integrity.

## Cross references
- 05 Faculties Conscience
- 03 Faculties Intellect
