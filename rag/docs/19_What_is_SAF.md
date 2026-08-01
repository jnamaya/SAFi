---
title: What is SAF
slug: saf-overview
tags: ["safi", "overview", "philosophy", "ai-alignment"]
summary: Introduces SAF as a philosophical framework rooted in classical thought, and SAFi as its technical implementation for AI governance.
version: 1.0
---

# What is SAF

## A philosophical framework
At its core, the Self-Alignment Framework (SAF) is a philosophical system rooted in classical thought. It continues a line of moral reasoning that began with **Plato, Aristotle, St. Augustine, and Thomas Aquinas**.  

SAF synthesizes this tradition and extends it with a new functional faculty: the **Spirit**. From this perspective, SAF is an abstract philosophical blueprint, a universal architecture for human alignment.

## The five functions
SAF describes a loop of five functions. None of them presuppose software: the framework describes how a person, a team or an institution moves from what it believes to what it actually does, and stays recognisable while doing it.

- **Values** — what a person or institution has decided to stand for, held explicitly enough that action can be measured against it.
- **Intellect** — understanding the situation: what is known, what is missing, what is actually being asked.
- **Will** — choosing what to do, including choosing to wait, to ask, or to refuse.
- **Conscience** — judging that choice against the values.
- **Spirit** — integrating the result, so character holds together across many decisions rather than one at a time.

Most of this vocabulary is inherited. Aquinas treats intellect and will at length and uses the term *synderesis* for the habit that holds first principles without deliberating about them, which is close to the role Values plays. SAF departs from him in two ways: Conscience is placed **after** the Will, as the function that evaluates a proposed action, and the **Spirit** is introduced as the integrator of the whole loop. The Spirit is the genuine addition.

## From blueprint to application
To validate the framework, I built an AI application called **SAFi** (Self-Alignment Framework Interface). The name also echoes “Sophie,” associated with wisdom.  

SAFi translates SAF’s philosophical structure into code. It functions as an **operating system for ethics**: a governance layer that runs on top of any AI model to ensure alignment.

## Human alignment first, AI alignment later
Originally, SAF was conceived for human alignment. AI was not part of the early picture. But once I learned about the AI alignment problem, it became clear that SAF was well-suited to address it. Building SAFi provided a real-world testbed for the framework.

## How SAF differs
Other approaches to AI alignment—such as **Reinforcement Learning from Human Feedback (RLHF)** used by OpenAI, and **Constitutional AI** developed by Anthropic—are primarily **training methods**. They attempt to embed values directly into an AI’s internal weights before deployment, aiming to create an inherently “good” model.  

SAF takes a different route. It assumes that any model, no matter how well-trained, may still produce errors or drift.  

- SAFi is **not a training method**.  
- It is a **runtime governance system**.  
- It enforces an **external loop of checks and balances** in real time.  

This makes SAF distinct: it governs outputs dynamically rather than relying only on pre-training.

## The constitutional analogy
RLHF and Constitutional AI are like giving someone an excellent education and upbringing, hoping to have raised a good citizen. SAF is like building the republic.

- **Values** are the **constitution** — the founding document every branch is bound by, which no branch may rewrite while acting under it, and which changes only by deliberate amendment.
- **The Intellect** is the **legislature**, drafting what is proposed.
- **The Will** is the **executive**, which enacts or vetoes.
- **The Conscience** is the **judiciary**, reviewing what was done against the constitution.
- **The Spirit** is the **historical record**, the long view showing whether the republic is still the one it was founded as.

The load-bearing idea is not any single branch but that no branch can quietly become the others, and none can amend the constitution by acting under it. A good citizen may still err; a good constitution assumes they will and arranges for the error to surface and be answerable. This is why SAF applies to people and institutions as readily as to a model.

## Cross references
- 00_Intro_To-SAFi.md  
- 01_Faculties_Values_and_Profiles.md  
- 05_Faculties_Spirit.md  
- 18_separation_of_powers.md  
- 07_Concepts_Drift_Allegory.md  
- 08_SAFi_Technical_Math_Specification.md  
- 10_SAFi_Technical_Workflow.md  
- 11_Use_Cases_Practical_Applications.md  
- 12_Community_and_Licenses.md  
