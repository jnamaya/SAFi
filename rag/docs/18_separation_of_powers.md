---
title: The Separation of Powers in SAF
slug: saf-separation-of-powers
tags: ["safi", "governance", "faculties", "checks-and-balances"]
summary: How SAF’s faculties mirror the separation of powers in constitutional government — and why the separation is enforced by denying each faculty the information that would let it do another’s job.
version: 2.0
---

# The Separation of Powers in SAF

## Why separation matters
The resilience of the Self-Alignment Framework (SAF) does not come only from its individual faculties, but from how they work together as a complete system. The best analogy is constitutional government, one of the most stable governance structures ever designed.

## The Constitution: the role of Values
In government, the constitution provides the anchor—the collection of foundational principles and inalienable rights that define the nation.  

In SAF, this role belongs to **Values**. They are externally defined and non-negotiable, and the mechanism matters: the value set is compiled before a turn begins and held read-only while that turn runs. No faculty can alter what it is judged against while being judged — which is what it means for a constitution not to be rewritable by the branches operating under it.

## The Legislative Branch: the role of the Intellect
A constitution requires a legislative body to propose laws and policies consistent with its principles.  

In SAF, this is the **Intellect**. It is the generative faculty that proposes a course of action—an “answer” or a “response.”

A legislature does not enforce its own bills, and neither does the Intellect. It holds no execution rights: when it wants a tool used it can only ask, and the request is captured as a proposal rather than run.

## The Executive Branch: the role of the Will
A government needs an executive branch to enforce laws, not to debate them. Its role is fast, decisive action.  

In SAF, this is the **Will**. It enforces the rules without discretionary judgment — but note precisely what it does: it **authorises or refuses**, it does not act. Permission comes first, and only then does anything happen.

It also holds **no language model at all**. Every decision is a string comparison, a list membership test or a numeric threshold, so it cannot read what a response means, cannot be persuaded by phrasing, and cannot quietly reinterpret the rule it applies. Same input, same verdict, every time — an executive that cannot reinterpret, achieved by making interpretation structurally impossible rather than merely forbidden.

The Will is consulted five times in a single turn: screening the incoming prompt before any model runs, authorising a proposed tool, checking a draft's structure, enforcing the hard gates, and ruling on the final alignment figure.

## The Judicial Branch: the role of the Conscience
A judiciary prevents overreach by reviewing laws and actions against the constitution.  

In SAF, this is the **Conscience**. It is the reflective auditor, scoring value by value against the rubrics with a reason and a confidence for each.

It reviews the **draft**, before anything reaches the user — closer to a constitutional court examining a bill before promulgation than a court hearing a case afterwards. An audit that ran after delivery would be a report; running it first is what makes it a control.

Its independence is structural: the Conscience is the same kind of machinery as the Intellect, but instantiated separately with its own prompt, its own rubrics, and no stake in defending the draft it reads. The judge cannot be the defendant.

## The Spirit of the Nation: the role of the Spirit
A nation’s long-term health is measured by its overall character—whether it is coherent, peaceful, or fractured.  

In SAF, this is the **Spirit**. It integrates audits over time, measuring long-term alignment and how far a response sits from the character the agent has established.

It has no authority. It computes, and the Will decides. A branch that both measured the nation's health and could act on its own measurement would be two branches wearing one name.

## What actually makes it a separation
Saying each faculty is essential and that removing one would cripple the system describes a **division of labour**, not a separation of powers. A team where everyone has a job but anyone could do anyone else's is not separated at all.

What makes this a genuine separation is that each faculty is **denied the information that would let it do another's job**:

- The **Intellect** never sees the rubrics it will be judged against, nor any score. Give a drafter the marking scheme and it writes to the marking scheme, and the assessment stops measuring anything (Goodhart).
- The **Conscience** never sees the weights, so it cannot shade a score for its downstream effect.
- The **Will** cannot read meaning at all, which is why its decisions are reproducible — and a decision that cannot be reproduced cannot be audited.
- The **Spirit** has no authority, only arithmetic.
- **Values** cannot be edited by anything operating under them.

Each is a deliberate deprivation. Together they are why the record at the end of a turn is worth reading: no faculty in the chain was ever in a position to write its own verdict. That is what checks and balances actually means — not five parts that cooperate, but five arranged so none can quietly become the others.

## Cross references
- 01_Faculties_Values_and_Profiles.md  
- 02_Faculties_Intellect.md  
- 03_Faculties_Will.md  
- 04_Faculties_Conscience.md  
- 05_Faculties_Spirit.md  
- 10_SAFi_Technical_Workflow.md  
