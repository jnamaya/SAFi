---
title: Introduction: Self-Alignment Framework Interface (SAFi)
slug: intro-SAFi
tags: ["safi", "intro"]
summary: High level conceptual framework connecting faculties, values, and governance into a closed loop architecture.
version: 1.0
---

# SAFi

## What is SAFi
SAFi is the first open source implementation of the Self Alignment Framework, a closed loop ethical reasoning engine. SAFi is not a language model. It is a governor that evaluates and audits the behavior of AI models through a five faculty reasoning loop. The loop provides transparency, accountability, and drift detection.

Values → Intellect → Will → Conscience → Spirit

## How SAFi works
SAFi uses a separation of powers design. Each faculty handles a specific part of the alignment process. The result is an internal set of checks and balances that can be inspected and tested.

## The faculties
### Intellect engine
This is the generative core. It uses a general model to reason over the knowledge base and draft a response. It also produces a private reflection about how it reached that draft.

### Will gate
This is a fast safety gatekeeper. It inspects every draft before the user sees it and enforces the non negotiable rules of the active persona. Its function is to block policy violations and protect the brand.

### Conscience auditor
This is the judicial layer. After approval, it audits the final answer against the weighted values of the persona. It outputs a machine readable ethical ledger for accountability.

### Spirit integrator
This is the historian and identity tracker. It analyzes many audits over time to measure ethical performance and identity drift. It prevents the King Solomon problem. It generates coaching feedback for the Intellect so the system can learn and self correct.

## Ethical profiles, personas
SAFi can load different personas so one system adapts to many contexts. A persona defines alignment parameters and operational character.

### Dynamic persona switching
Users can switch the active persona in the front end. The change applies immediately.

### Profile structure
Each persona contains:
- Worldview, a short constitution that sets purpose and reasoning principles
- Style, guidance for voice, tone, and communication
- Will rules, guardrails enforced by the Will gate
- Values, a weighted list used by the Conscience audit

### Prebuilt personas
Examples include a virtue ethics guide, a cautious finance educator, and a healthcare navigator.

## Use cases
SAFi ships as a complete web app suitable for enterprise use.

### Authentication
Users sign in securely, for example with Google OAuth.

### Conversation history
All chats are stored in MySQL so users can continue across sessions and devices.

### Long term conversation memory
A background job maintains a running summary. The AI keeps context across long discussions and recalls prior details.

### Asynchronous auditing
Users get a fast initial answer from Intellect and Will. Conscience and Spirit perform a deeper audit in the background. Results are logged without slowing the experience.

### Model agnostic design
Different models can be assigned to different faculties. For example a fast model for Will and a high capacity model for Intellect.

### Transparent logging
Each turn is logged to JSONL, including Intellect drafts, Will decisions, the Conscience ledger, and Spirit vectors. Audits are inspectable.

### Durable storage
Critical data, such as users, chats, and long term Spirit memory vectors, are stored in MySQL.

### Deployment and configuration
Environment variables control API keys, database settings, and model assignment. This helps manage development, staging, and production.
