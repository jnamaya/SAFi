---
title: Pricing and SLA — How RunSAFi Charges
slug: pricing-and-sla
tags: ["runsafi", "pricing", "sla", "scoping", "billing"]
summary: RunSAFi pricing. Phase one Setup billed hourly against a not-to-exceed cap; Phase two Run is a flat monthly fee with Team and Enterprise SLA tiers; model spend is always billed directly by the customer's own AI provider. Includes the SLA outline, what moves the quote, and what the monthly fee does not cover.
version: 1.0
---

# How RunSAFi Charges

Hourly to get live, then a flat monthly fee. The customer pays the hosting provider for the machine at cost, with no markup from RunSAFi. Model usage is billed by the AI provider directly because the keys are the customer's.

Pricing and service levels are scoped directly to the deployment, operating requirements, support window, and recovery objectives. Quotes are finalized in a written statement of work and service agreement.

## Phase one: Setup (time and materials)

Installing SAFi is quick; getting the organization live involves the customer's security review, access provisioning, environment setup, and policy design. That work is billed hourly against an estimate with a not-to-exceed cap agreed up front. Setup includes:

- Environment scoping and sizing
- Deployment from a published, integrity-verified release
- Domain, TLS, and first-run configuration
- TCB Fingerprint verification of the running Core Loop
- Policy and agent setup tailored to requirements
- Support for the internal security review and access provisioning

Why setup is hourly rather than fixed: those processes move at the customer's pace. Billing the setup phase hourly against a capped estimate is the honest way to price work whose duration the customer controls. Once live in production, the monthly fee is flat and predictable.

## Phase two: Run (flat monthly)

A predictable flat monthly fee with SLA tiers for teams and enterprises. Run includes:

- Updates on the release cadence and security hotfixes
- System monitoring and alerting
- Automated backups configured in the customer's own storage
- Tested restores executed on an agreed schedule
- Severity-based incident response
- Recurring integrity attestation reports
- Resource tuning and log rotation

## Always: Bring your own keys

- You pay your AI provider directly for tokens.
- RunSAFi never fronts, marks up, or pools model spend.
- You pay your hosting provider for the machine at cost.
- You own and rotate the API keys.

## SLA outline: Team and Enterprise

This outlines the baseline service agreement. Specific targets, maintenance windows, and recovery objectives are defined in writing during scoping.

- **Availability.** A monthly uptime target measured on the SAFi service, excluding the hosting provider's outages and mutually agreed maintenance windows.
- **Response times.** Severity-based routing. A service-down incident triggers immediate acknowledgement and continuous work to restore. Lower severities receive next-business-day handling.
- **Backups and recovery.** Automated backups in customer-controlled storage with an agreed retention period. Restore procedures are tested on a set schedule.
- **Updates and security.** Feature releases deployed on the SAFi cadence with the customer's sign-off on the change window. Security hotfixes are applied promptly upon release.
- **Integrity attestation.** Regular reports proving the running Core Loop matches a published SAFi release by its TCB Fingerprint.
- **Data and exit.** The customer's data stays on their machine and is never used for training. On exit, the customer keeps the infrastructure, the keys, and the data following a clean handover protocol.

## What moves the quote

- **Deployment path.** Docker or bare-metal, and the required operating standards.
- **Expected load.** The number of users and governed turns, and how the machine scales.
- **Support window.** Business hours versus extended coverage, and strict severity definitions.
- **Recovery objectives.** The data loss and downtime thresholds the agreement must guarantee against.
- **Policy design.** The level of assistance required to author the initial charter and agent policies.
- **Tooling.** The complexity and number of MCP tool servers and external endpoints.
- **Access controls.** Standard admin access versus bastion access with full session logging.
- **Handover ambition.** The training schedule required to transition operations to the internal IT team.

## What the monthly fee does not cover

- **Model tokens.** Billed directly to the customer by their AI provider.
- **The machine.** Paid to the hosting provider at cost.
- **Custom engineering.** Operating stock SAFi is the service. Bespoke plugins or feature development require a separate engagement.
- **Your compliance decisions.** SAFi produces the evidence. Deciding corporate policies and interpreting audit trails remains the customer's responsibility.
- **End-user support.** RunSAFi keeps the engine running. Supporting internal staff remains with the customer's IT help desk.