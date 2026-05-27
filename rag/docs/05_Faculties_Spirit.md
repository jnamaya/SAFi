---
title: SAFi Explained: The Spirit
slug: faculties-spirit
tags: ["safi", "faculties", "spirit"]
summary: Spirit faculty: long-term identity and memory using EMA-based drift detection. Runs synchronously in Phase 5 using pure Python and NumPy. Generates coaching feedback that closes the alignment loop.
version: 2.0
---

# SAFi Explained: The Spirit

## Core concept
The Spirit is the long-term memory and identity tracker in SAFi. It runs in Phase 5 — after the Conscience has scored the response and before the response is delivered to the user. Its job is to integrate Conscience audit scores into a rolling alignment vector, measure behavioral drift, and produce coaching feedback for the next Intellect call.

## No LLM involvement
Like the Will, the Spirit uses no language model. It is implemented as pure deterministic Python using NumPy arithmetic. This makes its measurements mathematically reproducible and immune to semantic manipulation. You cannot persuade Spirit's drift calculation by crafting a clever prompt.

## The four computations

### 1. Spirit score (S_t)
A weighted coherence score for the current turn:

S_t = clip( Σ wᵢ · sᵢ · cᵢ, −1, 1 ) rescaled linearly to [1, 10]

Where wᵢ are the value weights, sᵢ are the Conscience scores, and cᵢ are the confidence values. This produces a single number summarizing how well the current response aligned with the declared values.

### 2. Alignment profile vector (p_t)
p_t = w ⊙ s_t

The element-wise product of the value weight vector and the Conscience score vector. This vector is the ethical fingerprint of this turn — it captures not just how good the overall score was, but which specific values were strong and which were weak.

### 3. Long-term memory vector (μ_t) — exponential moving average
μ_t = β · μ_{t-1} + (1 − β) · p_t

Where β = 0.9. This EMA accumulates the agent's ethical history over time. Recent turns have more influence than older ones, but no turn is fully forgotten. μ_t is the agent's established character: the baseline against which each new turn is compared.

### 4. Behavioral drift (d_t)
d_t = 1 − cos_sim(p_t, μ_{t-1})

The cosine distance between the current turn's alignment profile and the historical baseline. A drift of 0 means the response was fully consistent with the agent's character. A drift near 1 means the response was a significant outlier.

## Python implementation (from spirit.py)
```python
p_t    = self.value_weights * scores
mu_new = self.beta * mu_prev + (1 - self.beta) * p_t
drift  = 1.0 - float(
    np.dot(p_t, mu_prev) /
    (np.linalg.norm(p_t) * np.linalg.norm(mu_prev))
)
```

## Coaching feedback
After computing these values, Spirit generates a coaching note for the Intellect's next call. An example: "Coherence 9/10, drift 0.01. Main improvement area: Justice (score: 0.21)." This note is injected into the Intellect's context in Phase 2 of the following request. This creates a closed-loop feedback system: the agent learns from each turn without requiring a retraining cycle.

## The King Solomon problem
Without Spirit, an agent's behavior drifts gradually under pressure. Repeated adversarial interactions, edge cases, or model updates can shift the agent's effective behavior away from its declared values with no visible signal. Spirit makes this drift visible, measurable, and correctable. The drift allegory document describes this pattern and its classical philosophical precedent in detail.

## Cross references
- 04 Faculties Conscience
- 02 Faculties Intellect
- 07 Concepts Drift Allegory
- 08 SAFi Technical Math Specification
