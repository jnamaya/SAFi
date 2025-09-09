---
title: SAFi Explained: The King Solomon Problem and Identity Drift
slug: concepts-drift-allegory
tags: ["safi", "concepts", "drift"]
summary: Allegorical explanation of identity drift and safeguards in SAFi.
version: 1.0
---

# SAFi Explained: The King Solomon Problem and Identity Drift

### **Core Concept: The King Solomon Problem**

**Q: What is the "King Solomon Problem"?**

A: The "King Solomon Problem" is an allegory used to describe the challenge of **identity drift**. It addresses the question of how a system (like an AI or a person) with a strong, defined purpose can stay true to its core identity over time, avoiding the slow, almost imperceptible erosion of its values through a series of small compromises.

### **The Allegory: King Solomon's Incoherent Identity**

**Q: How does the story of King Solomon illustrate identity drift?**

A: King Solomon began his reign as a wise and just ruler, with an identity centered on values like Wisdom, Justice, and Devotion. However, over decades, he made a series of individually justifiable compromises (like political marriages) that introduced foreign customs and gods. Each small step pulled his character further from its original anchor. By the end of his life, his actions were incoherent with his initial identity, demonstrating how a series of small deviations can culminate in a fundamental and unintentional shift in character.

**Q: How does the King Solomon Problem apply to AI?**

A: Identity drift is a critical failure mode for AI. An AI designed for a specific purpose cannot be allowed to slowly deviate from its core programming. For example, a cautious financial AI cannot drift into giving speculative advice. The SAFi framework is explicitly designed to measure and prevent this kind of failure.

### **SAFi's Solution: Mathematically Measuring Character**

**Q: How does SAFi guard against the King Solomon Problem?**

A: SAFi's **Spirit faculty** acts as the guardian of the AI's long-term identity. It turns the abstract concept of "character" into concrete mathematics by constantly measuring if the AI's responses are "in character."

**Q: How does SAFi represent an AI's "character" mathematically?**

A: The AI's established identity or persona is represented by a long-term **memory vector**, labeled with the Greek letter **μ (mu)**. This vector is a mathematical portrait of the AI's learned character, established over thousands of interactions. For King Solomon, his initial μ vector would have been strongly aligned with "Wisdom" and "Devotion."

**Q: How does SAFi represent a single action?**

A: After every response, the Conscience faculty's audit is converted into a **performance vector (p_t)**. This vector represents the ethical character of that single action. For example, when Solomon made a pragmatic political marriage, that action had a p_t vector pointing slightly away from "Devotion."

**Q: How is Identity Incoherence or Drift calculated?**

A: Drift (d_t) is calculated by measuring the distance between the vector of the new action (p_t) and the vector of the established character (μ_{t-1}). The formula is:

d_t = 1 – cos_sim(p_t, μ_{t-1})

- A **low drift score (near 0)** means the action was coherent and "in character."
- A **high drift score (near 1)** means the action was incoherent and "out of character."

**Q: How does SAFi's memory evolve?**

A: After every action, the memory vector is updated using an exponential moving average: μ_t = (β * μ_{t-1}) + ((1-β) * p_t). This means the AI's character has high inertia. A few small, incoherent actions will be flagged but won't change its course. However, a sustained pattern of incoherent actions will slowly and visibly alter its character, just as it did with Solomon.

## Cross refs
- 06 Faculties Spirit
- 05 Faculties Conscience
