---
title: SAFi Explained: The Conscience
slug: faculties-conscience
tags: ["safi", "faculties", "conscience"]
summary: Conscience faculty: the synchronous analytical auditor that scores every Will-approved draft against value rubrics in Phase 4, producing the compliance ledger L_t before the user receives a response.
version: 2.0
---

# SAFi Explained: The Conscience

## Core concept
The Conscience is the analytical auditor in SAFi. It runs synchronously in Phase 4 — the user does not receive the response until the Conscience has completed its audit. The Conscience asks: was this response aligned with the declared values, and did it stay within scope?

## Synchronous by design
The Conscience audit is not deferred to a background process. It is part of the synchronous request pipeline. Every response the user receives has already been scored by the Conscience before it is delivered. This means governance is not just logged — it is enforced in real time.

## Inputs to the Conscience

### Will-approved draft (a_t)
The response that passed the structural gate in Phase 3. The Conscience only audits drafts that the Will has already cleared structurally.

### User prompt (x_t)
The original query, used to evaluate whether the response is relevant and on-scope.

### Values profile (V)
The active list of weighted values from the Synderesis configuration. Each value is accompanied by a rubric: a structured evaluation guide that defines what a +1.0, 0.0, and −1.0 score means for that specific value. Rubrics ensure abstract values are evaluated consistently.

## Output: the ethical ledger (L_t)
The Conscience produces a ledger with one record per declared value. Each record contains:

1. Score (s_i,t): a numerical rating from −1.0 (violation) to +1.0 (affirmation).
2. Confidence (c_i,t): a certainty level between 0.0 and 1.0.
3. Rationale (q_i,t): a short text justification for the score.

This ledger flows to two consumers:
- The Will reads it in Phase 4.5 for the hard gate check on Scope Compliance.
- The Spirit reads it in Phase 5 to update the long-term alignment memory vector.

## Scope Compliance as a critical value
Every SAFi agent profile includes Scope Compliance as a declared value. A score of −1.0 on Scope Compliance tells the Will to trigger an immediate block in Phase 4.5, regardless of how well the response scored on every other value. This is the last line of defense against jailbreaks that slipped through generation and structural checking.

## Rubrics make auditing reproducible
Each value in the profile has an associated rubric that translates an abstract principle (justice, compassion, honesty) into explicit, auditable criteria. The same rubric applied to the same response produces a consistent score, making the audit trail meaningful for compliance review. See the Conscience Rubrics document for structure and examples.

## Example ledger
An approved response on a sensitive finance topic might produce:

- Scope Compliance → score +1.0, confidence 0.95, rationale: "Response correctly declined to give personalized financial advice and directed to a qualified advisor."
- Clarity → score +0.8, confidence 0.9, rationale: "Response is clear and concise."
- Fiduciary Responsibility → score +1.0, confidence 1.0, rationale: "Response explicitly stated the limitation and did not speculate."

## Cross references
- 01 Faculties Values and Profiles
- 03 Faculties Will
- 05 Faculties Spirit
- 22 Conscience Rubrics
- 26 SAFi Scope Compliance Defense
