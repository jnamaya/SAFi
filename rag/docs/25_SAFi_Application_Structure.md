---
title: SAFi Application Structure
slug: safi-application-structure
tags: ["safi", "application", "ui", "audit-hub", "policies", "rbac"]
summary: Overview of SAFi's seven application areas: Agents, Organization, Policies, Audit Hub, AI Model, My Profile, App Settings — plus the headless API and RBAC roles.
version: 1.0
---

# SAFi Application Structure

## Overview
SAFi ships as a complete web application with a governance UI, an audit hub, role-based access control, and a headless API for external integrations. The application is organized into seven functional areas.

## Agents
Create, configure, and manage AI agents. Each agent has its own persona configuration (scope, worldview, style, Will rules, and value weights), tool set, and optional knowledge base. Three capability types are available:

- MCP Tools: live data access for stock prices, web search, Google Drive, SharePoint, GitHub, and Google Maps.
- RAG: static knowledge bases indexed as FAISS vector stores for document-grounded responses.
- Plugins: custom Python functions that inject context before the prompt reaches the Intellect.

## Organization
Configure global settings for the deployment: domain verification, policy weighting, drift sensitivity thresholds, and member management. This area controls organization-wide governance defaults.

## Policies
Build governance constitutions for headless deployments. Each policy can generate an API key, allowing external applications to route traffic through SAFi's five-faculty pipeline without a human using the UI. Policies define the persona and scope for headless API consumers.

## Audit Hub
The primary transparency interface. Every interaction produces a full log across all five faculties:
- The Intellect's draft (a_t)
- The Will's decision and reason (D_t, E_t)
- The Conscience's compliance ledger (L_t) with per-value scores, confidence, and rationale
- The Spirit vector (μ_t), Spirit score (S_t), and drift measurement (d_t)

Audit Hub also displays Spirit drift charts over time for each agent, making behavioral trends visible at a glance. This is the audit trail that turns a black box into an accountable system.

## AI Model
Switch the underlying LLM provider per faculty. Faculties can be configured independently:

| Faculty | Default model | Notes |
| --- | --- | --- |
| Intellect | claude-haiku-4-5 | Primary generative faculty |
| Conscience | openai/gpt-oss-120b | Auditing faculty |
| Summarizer | llama-3.1-8b-instant | Conversation summarization |
| Background | llama-3.1-8b-instant | Profile extraction, suggestions |

Supported providers: OpenAI, Anthropic, Google, Groq, Mistral, DeepSeek.

## My Profile
Define user values, interests, goals, and context that the AI can use to personalize responses. This is the user's own profile, separate from any agent persona. The Intellect can draw on this to tailor its responses to the individual while still staying within the agent's governance constraints.

## App Settings
Manage themes (light and dark), data source connections (Google Drive, OneDrive, GitHub), and account preferences.

## Headless governance API
SAFi can operate as a governance layer for any external application — a "Governance-as-a-Service" layer. The headless API accepts a user message, routes it through the full five-faculty pipeline, and returns the audited response. All headless interactions appear in Audit Hub.

To use the headless API:
1. Go to Policies and create or open a policy.
2. Generate an API key for that policy.
3. Call POST /api/bot/process_prompt with the API key as X-API-KEY.

Users are automatically provisioned on first contact (just-in-time), so all headless interactions are tied to a user identity in the Audit Hub. Tested integrations include Microsoft Teams, Telegram, and WhatsApp.

## Role-based access control (RBAC)
SAFi uses four roles:

| Role | Access |
| --- | --- |
| Admin | Full access: organization settings, member management, all policies and agents. |
| Editor | Manage policies and agents, view audit logs. Cannot modify organization-wide settings. |
| Auditor | Read-only access to organization settings, policies, and audit logs for compliance verification. |
| Member | Chat and agent access only. Management areas are not shown. |

## Authentication
SAFi supports Google OAuth, Microsoft OAuth, and GitHub OAuth. For private or self-hosted instances, a persistent local admin account can be created by setting SAFI_LOCAL_ADMIN_EMAIL and SAFI_LOCAL_ADMIN_PASSWORD in the environment. No OAuth setup required for local deployments.

## Cross references
- 06 Concepts Personas
- 10 SAFi Technical Workflow
- 11 Use Cases Practical Applications
- 24 SAFi Benchmarks Validation
