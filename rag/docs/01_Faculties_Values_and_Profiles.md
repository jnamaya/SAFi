---
title: SAFi Explained: Values
slug: faculties-values-and-profiles
tags: ["safi", "faculties", "agents", "values"]
summary: Foundational values and policies that condition SAFi's reasoning and agent behavior.
version: 1.1
---

# SAFi Explained: Values

## Core concept: the role of values
Faculties define the how, the fixed repeatable process of alignment. Values define the what, the ethical content and principles the process works on. Values act as the setpoint for the system.

## Who defines the values
The responsibility lies with the human or institution implementing the system. SAFi is a tool for alignment. The user provides the core principles that set its direction.

## The SAFi profile
SAFi turns abstract principles into a machine readable object called a profile. The profile is the master blueprint for the system’s ethical character and behavior. In practice it is a dictionary compiled by `synderesis.py` with several components.

### Values and Synderesis are not the same thing
In SAF — the framework — the first faculty is **Values**. In SAFi — the implementation — the component occupying that position is **Synderesis**, and the two names are not interchangeable. Values are the *input*: the principles an institution declares in its Charter and its policies. Synderesis is the *machinery*: the compiler that turns those declared principles into the weighted, rubric-bearing value set the Conscience actually scores against.

The file was originally called `values.py`. Renaming it to `synderesis.py` was the moment the distinction became visible in the codebase: the file was never holding the values, it was generating the object the rest of the system evaluates against. When discussing the framework, say Values; when discussing the software, say Synderesis.

### Profile components
- Worldview: a short constitution that defines purpose, goals, and principles. It guides the Intellect.
- Style: the agent and tone, for example “empathetic, clear, educational.” It instructs the Intellect on voice.
- Will rules: a list of non negotiable rules enforced by the Will. These are hard guardrails.
- Values: a list of ethical principles, each with a weight. The Conscience uses them for audits. The Spirit uses them for long term scoring.

## How profiles guide faculties
Each profile component instructs one of the faculties.

1. Intellect reads worldview and style to draft a response.
2. Will applies the will rules to block or approve.
3. Conscience checks the response against weighted values and produces its audit.
4. Spirit uses the weights to calculate memory updates and long term performance.

## Cross references
- 07 Concepts Agents
