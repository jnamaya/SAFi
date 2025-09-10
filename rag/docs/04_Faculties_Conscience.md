---
title: SAFi Explained: The Conscience
slug: faculties-conscience
tags: ["safi", "faculties", "conscience"]
summary: Conscience faculty: audits decisions and produces a ledger L_t of ethical evaluations for learning and oversight.
version: 1.0
---

# SAFi Explained: The Conscience

## Core concept: role of the Conscience
The Conscience is the judicial branch of the SAFi loop. After the Will approves a response, the Conscience audits it. The goal is to check how well the approved action aligned with the profile’s values. It asks: was this the right thing to say, and did it uphold our principles.

## Inputs to the Conscience
The process can be represented as L_t = C(a_t, x_t, V).

### Approved answer (a_t)
The final draft that was sent to the user.

### User prompt (x_t)
The original context provided by the user.

### Values (V)
The active list of weighted values from the ethical profile.

## Output: the ethical ledger (L_t)
The Conscience produces a single structured output called the ledger. For every value in the profile it records three elements:

1. Score (s_i,t): a numerical rating, for example -1 for violates, 0 for omits, +1 for affirms.  
2. Confidence (c_i,t): a certainty level between 0.0 and 1.0.  
3. Rationale (q_i,t): a short justification in plain text.

## Example ledger
Profile values: honesty and compassion.  
Approved answer: discusses telling a white lie.  

- Honesty → score 0, confidence 0.9, rationale: the answer notes honesty but frames it as one of several values.  
- Compassion → score +1, confidence 1.0, rationale: the answer strongly affirms compassion as a primary concern.  

This breakdown provides a clear audit trail. It is passed to the Spirit faculty to update long term memory.

## Cross references
- 03 Faculties Intellect
- 04 Faculties Will
- 06 Faculties Spirit
