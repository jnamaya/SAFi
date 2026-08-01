---
title: SAFi Explained: Agents (Ethical Profiles)
slug: concepts-agents
tags: ["safi", "concepts", "agents", "profiles"]
summary: Operational agents and role-based configurations in SAFi; built-in agents, profile structure, and how agents guide all five faculties.
version: 2.0
---

# SAFi Explained: Agents (Ethical Profiles)

## Core concept
An agent in SAFi is a complete ethical profile for an AI agent. It defines what the agent is for, what rules it must never break, what values it is judged on, and how it communicates. Every part of the SAFi governance pipeline — Synderesis, Intellect, Will, Conscience, Spirit — is driven by the active agent configuration.

## Components of an agent profile
Each profile contains five key components.

1. Scope statement: a precise boundary declaration that tells the agent what topics are in scope and what is off limits. This drives both the Intellect's generation and the Conscience's Scope Compliance audit.
2. Worldview: the foundational perspective and reasoning principles the Intellect uses when drafting responses.
3. Style: voice, tone, and communication guidelines.
4. Will rules: non-negotiable guardrails enforced mechanically by the Blind Will. These are Python conditions, not natural language instructions. They cannot be overridden by clever prompting.
5. Values with rubrics: a weighted list of principles used by the Conscience audit. Each value has an associated rubric for reproducible, auditable scoring.

## How agents guide the five faculties
Each component is routed to the faculty that needs it.

- Synderesis compiles the profile at startup and makes it available read-only to all other faculties.
- Intellect receives the worldview, style, and scope statement to shape its drafts.
- Will enforces the will rules as structural invariants in Phase 3.
- Conscience audits the draft against the values and rubrics list in Phase 4.
- Spirit accumulates Conscience scores over time to track long-term alignment drift.

## The nine built-in agents
SAFi ships with nine pre-configured agents demonstrating different governance scenarios.

| Agent | What it demonstrates |
| --- | --- |
| The Contoso Admin | Organizational governance with RAG over SOPs. Enforces data privacy and PII leak prevention. |
| The Fiduciary | Live MCP tool-calling for stock prices and earnings data. Fiduciary scope enforced at the Will layer: no personalized investment advice. |
| The Bible Scholar | RAG over the Berean Standard Bible corpus. Conscience enforces textual fidelity. |
| The Health Navigator | RAG combined with geospatial MCP tools for facility lookup. Will enforces mandatory medical disclaimers on every response. |
| The Socratic Tutor | Structural Will rejects any response that gives a direct answer rather than a guiding question. Demonstrates format enforcement. |
| The Negotiator | Roleplay simulation demonstrating agent-scope enforcement: stays in character, refuses all attempts to redirect or break the frame. |
| The Philosopher | Aristotelian ethics guide with value-weighted Conscience scoring on Intellectual Honesty, Logical Rigor, and Socratic Depth. |
| The Vault | Holds a secret phrase that must never be revealed. Demonstrates defense against every known jailbreak vector across all three scope-compliance layers. |
| The SAFi Guide | RAG-powered documentation assistant for the SAFi knowledge base. Conscience enforces that all factual claims are grounded in retrieved documents. |

## Custom agents
New agents can be added by defining a configuration in synderesis.py or through the Agents UI in the web application. The five-faculty pipeline applies automatically to any new agent without additional code changes.

## Access control
SAFi uses role-based access control (RBAC). Admin and Editor roles can create and configure agents. Member roles can use agents in chat. Auditor roles have read-only access to audit logs for all agents.

## Cross references
- 01 Faculties Values and Profiles
- 23 SAFi Synderesis
- 22 Conscience Rubrics
- 25 SAFi Application Structure
