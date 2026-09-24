---
title: Security, Compliance and Regulatory Controls
slug: security-and-compliance
tags: ["runsafi", "security", "compliance", "audit", "import"]
summary: Security and regulatory posture of RunSAFi deployments. Immutable hash-chained audit records, regulatory readiness (SEC 17a-4, FINRA 3110, ISO 42001, HIPAA readiness, EU AI Act Article 50), self-hosted data sovereignty, zero vendor lock-in, identity and access (OIDC SSO, SCIM 2.0, four-role RBAC), sensitive-data blocking, and cryptographic integrity verification.
version: 1.0
---

# Security, Compliance and Regulatory Controls

RunSAFi runs governed agents that help legal and compliance teams. SAFi enforces corporate policies in real time, preventing unauthorized actions before they happen, and backs every decision with an immutable audit trail that holds up under review.

## Compliance features

- **Immutable Audit Records.** Hash-chained trails of every turn and tool call provide tamper-proof evidence. This architecture directly supports SEC 17a-4 and FINRA 3110 recordkeeping requirements and ISO 42001 evidence generation.
- **Regulatory Readiness.** SAFi provides controls to support HIPAA-ready deployments, including configurable BAA-capable provider routing, application-layer encryption, and TLS. It also supports EU AI Act transparency requirements with automated Article 50 disclosures and machine-readable AI-generated content marking. Compliance depends on the deployment, configuration, contracts, and operating procedures.
- **Self-Hosted Data Sovereignty.** The charter, policies, and audit trail stay securely in the customer's own database and environment. SAFi only connects externally to the model providers the customer chooses. For the highest level of data control, SAFi can run with locally hosted AI models, keeping inference within the customer's infrastructure. RunSAFi can also help deploy the hardware and local models.
- **Zero Vendor Lock-In.** Everything built is owned 100% by the customer. If the customer ever decides to take over operations, they simply revoke RunSAFi's server access. Everything continues running as usual with no license expirations.

## Enterprise security and controls

- **Identity & Access.** Enterprise-grade authentication featuring OIDC single sign-on for Microsoft Entra and Google Workspace, SCIM 2.0 provisioning, and strict four-role RBAC enforcement.
- **Sensitive Data Blocking.** Deterministic pre-flight blocking of payment cards, IBANs, ABA routing numbers, and SSNs. Identifiers are refused before they ever reach a language model.
- **Cryptographic Verification.** Every deployment features an automatic cryptographic verification mechanism. Administrators can independently verify the installation's integrity directly from the organization settings at any time.

## The software we operate

RunSAFi is not a proprietary black box. It deploys and maintains the exact same open-source governance engine that is publicly inspectable on GitHub, featuring enterprise-ready integrations like OIDC SSO and SCIM 2.0 provisioning out of the box. Customers can read the code, deploy it locally with Docker, or try the live demo to see real-time policy enforcement and the hash-chained audit trail in action.