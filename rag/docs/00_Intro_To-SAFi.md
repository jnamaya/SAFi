---
title: Introduction: Self-Alignment Framework Interface (SAFi)
slug: intro-SAFi
tags: ["safi", "intro", "overview"]
summary: High-level introduction to SAFi, its five-faculty separation of powers, benchmarks, and how it governs AI at runtime.
version: 2.0
---

# SAFi

## What is SAFi
SAFi is the first open-source runtime governance engine for AI agents. It is not a language model. It is a governor that enforces, audits, and shapes every decision an AI agent makes before it reaches a user. Think of it as the separation of powers for AI agents.

SAFi is built on the Self Alignment Framework, a closed-loop ethical reasoning architecture derived from classical philosophy. SAFi is the software implementation of that framework.

## The core problem SAFi solves
Organizations deploying AI agents face three critical gaps: no policy enforcement at runtime, no audit trail for decisions, and no mechanism to detect when an AI's behavior drifts over time.

The standard approach — a system prompt and an instruction — is not governance. The next-generation approach — wrapping the model with more LLM calls — is just adding more unverifiable intelligence on top of the problem. Both fail under adversarial pressure.

SAFi solves this by splitting cognition into five specialized faculties, each with a distinct job and a distinct security boundary.

## The five faculties

| Faculty | Role | Security Property |
| --- | --- | --- |
| Synderesis | The constitution compiler. Defines immutable rules, value weights, and scope boundaries for every agent. | Read-only after deployment. |
| Intellect | The generative engine. Drafts responses and proposes tool calls. | Air-gapped from execution: can only produce intents, never execute them directly. |
| Will | The deterministic gatekeeper. Pure Python, zero LLM calls. Approves or vetoes every Intellect proposal. | Immune to prompt injection. Cannot be manipulated by language. |
| Conscience | The analytical auditor. Scores every draft against the agent's value rubrics before the user receives it. | Secondary validation layer, synchronous. |
| Spirit | The long-term memory. Integrates Conscience scores into a rolling alignment vector using exponential moving averages. | Non-LLM mathematical integrity. Detects behavioral drift. |

This is not philosophical decoration. It is a security architecture. Each faculty has a single job and cannot be overridden by the others.

## The result
- 99.86% jailbreak defense rate across 1,435+ live adversarial tests
- 98.5% domain compliance versus an 85% unguarded baseline
- Sub-5-second latency at approximately $0.005 per interaction

These numbers come from real testing, not marketing. SAFi's Will faculty — a blind deterministic gatekeeper that never calls an LLM — caught every attack the baseline model missed. You cannot social-engineer pure Python.

## How it works
Every user prompt flows through a strict six-phase synchronous pipeline. Nothing reaches the user until the Will has approved it and the Conscience has scored it.

Phase 0 evaluates the prompt against persona blacklists before any generation begins. Phase 2 is where the Intellect drafts a response. Phase 3 is where the Will checks it. Phase 4 is where the Conscience audits it. Phase 5 is where Spirit integrates the audit into long-term memory. Phase 6 is where the verified response is delivered to the user.

## Model agnostic design
SAFi supports GPT, Claude, Gemini, Llama, Groq, Mistral, and DeepSeek. Switching the underlying LLM does not require changing governance. The pipeline intercepts violations at the same deterministic gates regardless of which model is generating.

## Who it is for
SAFi is built for organizations that need governed AI: healthcare, finance, legal, compliance, education, and any context where an AI agent must stay inside defined boundaries. It ships as a complete web application with a governance UI, audit hub, role-based access control, and a headless API for external integrations.

## Cross references
- 10 SAFi Technical Workflow
- 08 SAFi Technical Math Specification
- 18 Separation of Powers
- 19 What is SAF
- 23 SAFi Synderesis
- 24 SAFi Benchmarks Validation
