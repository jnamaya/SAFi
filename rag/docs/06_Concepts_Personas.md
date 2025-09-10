---
title: SAFi Explained: Personas (Ethical Profiles)
slug: concepts-personas
tags: ["safi", "concepts", "personas"]
summary: Operational personas and role-based configurations used by SAFi.
version: 1.0
---

# SAFi Explained: Personas (Ethical Profiles)

## Core concept: purpose of personas
Personas solve the problem of an AI lacking a clear compass. Values alone are complex and rules are not enough. A persona provides a guiding purpose by defining a coherent ethical character for the AI to embody. This ensures actions are consistent and aligned.

## What is a persona
A persona in SAFi is the practical application of an ethical profile. This profile is a structured, machine readable blueprint defined in configuration files such as values.py. It turns abstract values into operational guidance.

## Components of a persona profile
Each profile contains four key parts.

1. Worldview: the foundational perspective and core principles.  
2. Style: the voice, tone, and character for communication.  
3. Rules (will_rules): non negotiable guardrails that must never be broken.  
4. Values: a weighted list of nuanced principles used for judgment and audits.

## How personas guide the faculties
Each component maps to one faculty in the SAFi loop.

- Intellect uses the worldview and style to draft its response.  
- Will enforces the rules as strict boundaries.  
- Conscience audits the final output against the values list.  
- Spirit integrates the audit to track long term alignment and give coaching feedback.

## Benefits of personas
Personas make SAFi flexible and auditable. Instead of one fixed ethic, SAFi can embody context specific roles such as a fiduciary, a health navigator, or a jurist. This approach turns values into operational roles and allows SAFi to function as a transparent moral actor.

## Cross references
- 02 Faculties Values and Profiles
