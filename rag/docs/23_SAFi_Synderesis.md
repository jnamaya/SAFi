---
title: SAFi Explained: Synderesis (The Constitution Compiler)
slug: faculties-synderesis
tags: ["safi", "faculties", "synderesis", "constitution", "governance"]
summary: The Synderesis faculty: immutable constitution compiler that establishes value weights, scope boundaries, rubrics, and will rules for every persona. Read-only after deployment.
version: 1.0
---

# SAFi Explained: Synderesis

## Core concept
Synderesis is the foundational faculty in SAFi. It is not a generative model or a reasoning engine. It is a compiler: it takes a persona configuration and produces the immutable set of rules, values, and constraints that all other faculties operate on.

The term comes from classical philosophy, where synderesis refers to the innate moral knowledge that serves as the starting point for all ethical reasoning — the first principles of practical reason that cannot themselves be argued away. In SAFi, it serves the same role: the unchangeable constitutional foundation before any decision-making begins.

## What Synderesis defines
For each persona, Synderesis compiles and holds the following configuration:

1. Scope statement: the boundary declaration that defines what the agent is for and what is outside its domain. This is used by the Intellect for generation framing and by the Conscience for the Scope Compliance audit.
2. Value set (V): the declared list of values with non-negative weights summing to 1.0. These are used by the Conscience for scoring and by the Spirit for EMA computation.
3. Rubrics: structured evaluation guides for each value, defining what a +1.0, 0.0, and −1.0 score means in context. Rubrics make abstract values auditable and reproducible.
4. Will rules: the non-negotiable structural constraints enforced by the Blind Will. These rules are Python conditionals — not natural language instructions — and cannot be overridden by language at runtime.
5. Worldview and style: the narrative instructions that shape how the Intellect drafts responses, including its purpose, reasoning principles, communication voice, and tone.

## Read-only after deployment
The Synderesis configuration is read-only once a persona is deployed. No other faculty can modify it during a live request. Even if an adversarial prompt instructs the Intellect to change its values or ignore its scope, there is no code path from the Intellect to the Synderesis configuration. The constitutional foundation cannot be overwritten at inference time.

This is a deliberate security property: governance cannot be rewritten by the governed.

## Where it lives in the codebase
The Synderesis layer is implemented in synderesis.py in the SAFi core. This file defines all built-in persona profiles as structured Python objects and acts as the registry the orchestrator consults at the start of every request. New personas are added to this file or through the Agents UI, which writes back to the same registry.

## How every faculty draws from Synderesis

- Intellect reads the worldview, style, and scope statement.
- Will reads the will rules.
- Conscience reads the values and rubrics.
- Spirit reads the value weights for EMA and drift computation.

Synderesis is the single shared read-only source of truth for the entire governance pipeline. Its consistency across all faculties is what makes the system auditable: the same values that shape the Intellect's generation are the same values the Conscience scores and the same weights Spirit tracks over time.

## Cross references
- 01 Faculties Values and Profiles
- 06 Concepts Personas
- 03 Faculties Will
- 04 Faculties Conscience
- 05 Faculties Spirit
- 10 SAFi Technical Workflow
- 19 What is SAF
