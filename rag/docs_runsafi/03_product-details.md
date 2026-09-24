---
title: Product Details — What You Get From RunSAFi
slug: product-details
tags: ["runsafi", "product", "deployment", "data", "access", "onboarding"]
summary: Detailed product description. Governed agents deploy in the customer's environment on Linux via Docker or bare metal. Covers what RunSAFi delivers, environment requirements, data ownership and egress, the access model, the division of responsibilities, onboarding, and what the service is not.
version: 1.0
---

# Product Details

RunSAFi deploys AI agents directly in the customer's environment, governed by SAFi at runtime. Every action is evaluated against the customer's policies, every decision is recorded, and every tool call is authorized before it runs. The customer keeps the infrastructure, the data, and the keys.

## What you get

Governed agents on your infrastructure and your data. RunSAFi configures and deploys AI agents tailored to the organization's use case. SAFi sits between the agent and the outside world, evaluating every turn before an answer is returned or a tool runs.

The agents run on the customer's infrastructure. The data stays in the customer's environment. The model keys stay on the customer's machine. The customer owns everything. Because SAFi is open source, the customer can inspect the governance engine, verify its behavior, and take over operations whenever they choose. No surrender of control to a proprietary vendor cloud.

## What we deliver

- **Governed Agents.** Custom-built agents for the customer's use case, with SAFi governance built in from day one.
- **Deployment.** SAFi and the agents are deployed from a published, integrity-verified release into the customer's environment.
- **Maintenance.** Updates applied on the release cadence and immediate security hotfixes.
- **Monitoring.** System health, resource exhaustion, and log rotation.
- **Data Protection.** Routine backups and regular tested restores.
- **Integrations.** SSO providers and requested MCP tool servers.
- **Integrity Attestation.** The running Core Loop is verified against its published TCB Fingerprint, with recurring integrity reports for auditors.
- **Training.** The customer's team is trained to operate the agents and SAFi when ready to take over.

## What you bring

- **Infrastructure.** A Linux VM or bare-metal server sized to expected load. Everything runs inside the customer's boundary.
- **API Keys.** The customer provides their own AI model keys. They are stored securely on the customer's machine; RunSAFi's operating procedures ensure we cannot access their contents.
- **Policies and Directory.** The customer's internal corporate policies, agent scopes, and user directory configurations.
- **Data Ownership.** The customer retains complete ownership of all governance records and conversation data at rest.
- **Approvals.** The customer reviews and approves change windows for version upgrades.

## Environment and deployment

- **Your OS is Linux.** All of SAFi's tooling and the reference deployment require a Linux environment.
- **Docker or bare-metal.** SAFi is deployed via Docker or as a bare-metal installation with system services and a reverse proxy. The exact deployment path is confirmed during scoping to match the customer's internal operating standards.

## Data ownership and egress

- **Everything stays in your environment.** The software, governance records, and conversation data remain at rest entirely on the customer's machine.
- **Requests may leave your tenant.** SAFi sends prompts and data to the AI model providers and external tools the customer explicitly configures. The customer controls those endpoints and credentials.
- **You control the boundary.** The machine is placed in its own subnet with a strict egress allowlist. Traffic only routes to the designated model providers and internal tool endpoints.
- **We do not train on your data.** RunSAFi never uses governance records or conversation data to train models.

## Access model

- RunSAFi requires administrative access to the host so it can install system dependencies, deploy the engine and agents, manage configured tool servers, and apply patches. This access is strictly limited to the single machine.
- RunSAFi connects through the customer's approved channels: dedicated VPN, jump box, or scoped IAM roles.
- The customer controls RunSAFi's access: credentials are governed by the customer's organization, session logs can be audited, and access can be rotated, restricted, or revoked at any time.
- The customer keeps ultimate control: the machine is theirs, and they can snapshot it, inspect the filesystem, restrict its egress, or power it off.

## Who does what

- Environment, networking, IAM: RunSAFi advises; the customer owns and pays.
- Access to the machine: RunSAFi holds admin on that single host; the customer grants, isolates, audits, and revokes.
- Agent configuration: RunSAFi builds and configures; the customer defines requirements and approves.
- Deploy and upgrades: RunSAFi executes them; the customer approves the change windows.
- Backups and restore: RunSAFi executes and tests them; the customer relies on them.
- Model provider keys: RunSAFi never views them; the customer owns, applies, and rotates them.
- Model usage cost: zero markup; billed directly by the provider.
- Policies, agents, users: RunSAFi configures on request; the customer defines and governs.
- Governance data: RunSAFi maintains the database; the customer owns the data entirely.
- Integrity verification: RunSAFi provides scheduled attestations; the customer independently verifies at any time.
- End-user support: RunSAFi maintains system uptime; the customer manages internal staff help desk.

## Onboarding path

1. **Security Review & Scoping.** Environment specifics, access model (VPN, jump box, IAM), and required SSO and tool integrations.
2. **Infrastructure Provisioning.** The customer stands up the required Linux VM or bare-metal server.
3. **Deployment & Configuration.** RunSAFi installs the verified SAFi release, configures the domain over HTTPS, and sets up system monitoring.
4. **Agent Configuration.** Governed agents are built and configured for the use case and connected to approved MCP tool servers.
5. **SSO & Keys.** Identity Provider (Entra or Workspace) is connected; the customer logs in and applies model provider API keys.
6. **Go Live.** TCB Fingerprint is verified, monitoring baselines established, the operational SLA begins, and the governed agents start doing real work.

A path to self-operation is built in. RunSAFi can train the team to assume operations whenever ready. On exit the customer keeps the machine, the keys, and the data with a clean handover.

## What this is not

- **Not a reseller of model access.** Customers bring their own keys and pay their provider directly.
- **Not custom engineering.** Deploying and operating governed agents is the product. Bespoke features or plugins are a separate engagement.
- **Not your compliance team.** SAFi produces the evidence. Deciding policies and reviewing audit trails remains the customer's responsibility.
- **Not your help desk.** RunSAFi keeps the agents and platform running. Supporting internal staff stays with the customer's IT support.