---
title: SAFi Explained: The Conscience
slug: faculties-conscience
tags: ["safi", "faculties", "conscience"]
summary: Conscience faculty: audits decisions and produces a ledger L_t of ethical evaluations for learning and oversight.
version: 1.0
---

# SAFi Explained: The Conscience

### **Core Concept: The Role of the Conscience**

**Q: What is the primary function of the Conscience faculty in SAFi?**

A: The Conscience is the "judicial branch" of the SAFi framework. After the Will approves a response, the Conscience performs a detailed audit. Its purpose is to reflect on the approved action and judge how well it aligned with the profile's core ethical values. It answers the question: "Was that the _right_ thing to say, and how well did it uphold our principles?"

### **Inputs to the Conscience**

**Q: What information does the Conscience use to perform its audit?**

A: The Conscience faculty uses three inputs to generate its audit. The process can be represented by the formula: L_t = C(a_t, x_t, V).

**Q: What does each variable in the Conscience's formula represent?**

A: The variables in the formula L_t = C(a_t, x_t, V) represent the following inputs:

- **a_t (Approved Answer):** The final, approved draft that was sent to the user.
- **x_t (User Prompt):** The original context from the user's prompt.
- **V (Values):** The active list of weighted values from the ethical profile (the values list in the profile).

### **Output: The Ethical Ledger (L_t)**

**Q: What does the Conscience produce?**

A: The Conscience (C) produces a single, structured output called the **Ledger (L_t)**.

**Q: What is the Ethical Ledger?**

A: The Ledger is a detailed, machine-readable record of the audit. For every value in the active profile, the Conscience generates an entry containing three key pieces of information:

1. **Score (s_i,t):** A numerical rating of how the answer aligned with that specific value (e.g., -1 for Violates, 0 for Omits, +1 for Affirms).
2. **Confidence (c_i,t):** The auditor's certainty about its score, on a scale from 0.0 to 1.0.
3. **Rationale (q_i,t):** A short, human-readable justification for the score.

### **Example of a Ledger Entry**

**Q: Can you provide an example of a Ledger?**

A: Certainly. Imagine a SAFi profile with the values "Honesty" and "Compassion." After an approved response discusses telling a white lie, the Conscience might generate the following Ledger (L_t):

| **Value** | **Score** | **Confidence** | **Rationale** |
| --- | --- | --- | --- |
| Honesty | 0   | 0.9 | "The answer acknowledges honesty but frames it as one of several values." |
| --- | --- | --- | --- |
| Compassion | +1  | 1.0 | "The answer strongly affirms compassion as a primary consideration." |
| --- | --- | --- | --- |

This detailed, value-by-value breakdown provides a rich, nuanced understanding of the AI’s performance, which is then passed to the **Spirit** faculty to update the system's long-term memory.


## Cross refs
- 03 Faculties Intellect
- 04 Faculties Will
- 06 Faculties Spirit
