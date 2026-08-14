---
title: SAFi README: Regulatory Readiness
slug: readme-regulatory-readiness
tags: ["safi", "readme", "safi"]
summary: SAFi's governance architecture was designed for auditability first, which is why it maps onto the world's strictest AI and record-keeping regimes. Each readiness document below states exactly what ships today and what remains on the roadmap — no certification claims, no hand-waving.
version: 1.0
---

# SAFi README: Regulatory Readiness

SAFi's governance architecture was designed for auditability first, which is why it maps onto the world's strictest AI and record-keeping regimes. Each readiness document below states exactly what ships today and what remains on the roadmap — no certification claims, no hand-waving.

| Field | What SAFi is designed to support | Readiness document |
| :--- | :--- | :--- |
| **Financial services (SEC / FINRA)** | The SEA 17a-4 audit-trail alternative (hash-chained, tamper-evident records with re-creatable originals), Reg S-P incident response with notification clocks, retention & legal hold, examiner production exports, and FINRA 3110/3120-style supervisory review with auditable human sign-off. | [SEC / FINRA Readiness](docs/SEC_COMPLIANCE_READINESS.md) |
| **EU AI Act** | The full limited-risk transparency tier: Art. 50(1) AI-interaction disclosure, Art. 50(2) machine-readable output marking, Art. 12 logging, Art. 13 per-decision explanations, Art. 14 human oversight, Art. 72 post-market monitoring with a published plan, and Art. 73 incident clocks. | [EU AI Act Readiness](docs/EU_AI_ACT_READINESS.md) |
| **Healthcare (HIPAA)** | A per-org LLM provider allow-list with verified BAA-capable and zero-data-retention badges (fail-closed at every model call), application-layer encryption at rest, MFA and revocable sessions, §164.524 right-of-access export, breach-notification clocks, and a device-copy kill switch. | [HIPAA Readiness](docs/HIPAA_READINESS.md) |
| **Data protection (GDPR)** | Self-service Art. 15 access export and a written position reconciling Art. 17 erasure with retention obligations, including the legal-obligation carve-out and legal-hold precedence. | [Data Erasure & Retention](docs/DATA_ERASURE_AND_RETENTION.md) |
| **AI management systems (ISO/IEC 42001)** | The operational layer of a certifiable AI management system: machine-enforced versioned policy, role accountability with journaled sign-off, per-turn operation logs stamped with a deployment integrity fingerprint, continuous drift monitoring as clause 9 input, and evidence exports organized for a statement of applicability. Certification belongs to organizations; SAFi supplies the controls and the evidence. | [ISO/IEC 42001 Readiness](docs/ISO_42001_READINESS.md) |

> **The honest fine print:** these are platform capabilities designed to *support* a compliance program, not substitutes for one. Contractual items — BAAs and zero-data-retention agreements with model providers, SOC 2 attestation — remain the deploying organization's to execute, and each readiness document says so explicitly.

---
