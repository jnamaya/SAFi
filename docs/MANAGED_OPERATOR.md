# SAFi Managed Operator

If you want to pilot or use SAFi but feel overwhelmed by the technology, we can
help. We operate a dedicated SAFi instance in your own environment while your
organization retains ownership of the infrastructure, data, AI model keys, and
governance records. You bring the environment and resources. We bring the
expertise to deploy, secure, monitor, and maintain SAFi.

SAFi is open source and designed to be self-hosted. You can operate it yourself,
or we can act as your managed operator while your team builds the confidence and
capability to take over. This gives you a practical way to begin without
introducing a new vendor-hosted data boundary or committing to long-term
operational dependence.

Your environment. Your data. Your keys. Your governance. Our operational
expertise.

> **We bring our talent. You bring your resources.**

---

## The managed path to SAFi

You do not have to change your infrastructure or become an expert in SAFi
operations before you begin. SAFi can run in your existing environment, including
in-house servers or a trusted cloud account on Azure, AWS, GCP, or another
provider that meets your requirements.

You provide the environment and your AI model provider keys. We deploy and operate
SAFi on your behalf within that environment. Your data remains within your
security boundary, your model costs are billed directly by your provider, and your
team retains ownership of the complete deployment.

Because SAFi is open source, you are not surrendering control to a proprietary
hosted service. You can inspect the software, verify the running release, restrict
our access, revoke access when needed, and take over operations whenever you
choose.

This model is designed for organizations that want to evaluate SAFi or put it into
production without taking on the full operational burden on day one.

---

## Why organizations choose this model

- **Keep SAFi inside your existing boundary.** Your deployment runs in your
  environment rather than in a separate vendor-controlled cloud. No new vendor
  cloud to vet, no data-residency fight, no unfamiliar hosting to procure.
- **Start with expert operational support.** We handle deployment, updates,
  monitoring, backups, restore testing, and routine health work.
- **Keep ownership of the critical assets.** Your infrastructure, AI model keys,
  data, policies, and governance records remain yours.
- **Reduce lock-in.** You can inspect the software, verify the deployment, revoke
  access, and transition operations to your own team.
- **Create a path to self-operation.** We can train your IT team to assume the
  operator role when you are ready.

---

## How it works: we operate, you own

### What we bring (the operator role)

- We provision and deploy SAFi on your Linux machine, from a published,
  integrity-verified release.
- We set up secure access at your own domain or subdomain (for example,
  safi.yourcompany.com) and the first-run configuration.
- We apply updates on the release cadence, plus security hotfixes.
- We run monitoring, backups, and tested restores.
- We attest integrity: the running Core Loop matches an official SAFi release by
  its published TCB Fingerprint, so your auditors can confirm the governance
  engine is unaltered. We provide recurring integrity reports, and your team can
  review the release and verify the running deployment themselves.
- We handle incidents and routine health work (resource tuning, log rotation).
- We can train your IT team to operate SAFi themselves, whenever you want it.

### What you bring

- Your own environment: in-house servers, or a cloud account (Azure, AWS, GCP, or
  elsewhere), or a hosting provider we recommend and size. SAFi runs inside your
  boundary; we operate it there.
- Your own AI model provider API keys. You enter and manage your own keys. SAFi
  stores them according to the deployment's configured security controls, and our
  operating procedures are designed to prevent us from accessing their contents.
- Your policies, agents, and users, which you set up self-serve or with our help.
- Ownership of all governance records and conversation data, at rest on your
  machine.

---

## Environment and deployment

- **Your OS is Linux.** All of SAFi's tooling and the reference deployment assume
  Linux. This is a requirement, not a preference.
- **Docker or bare-metal, depending on the need.** SAFi can be deployed using
  Docker or a bare-metal installation with system services, a Python virtual
  environment, and a reverse proxy. We confirm the supported deployment path
  during scoping, based on the current release documentation and your operating
  standards.

---

## Data ownership and egress

- **SAFi stays in your environment.** The software, your governance records, and
  your conversation data remain at rest on your machine.
- **Requests may leave your tenant.** SAFi sends prompts and data to the AI model
  providers and external tools that you configure. You control those providers,
  endpoints, credentials, and egress rules.
- **You control the boundary.** You place the SAFi machine in its own subnet or
  resource group with a tight egress allowlist (your model providers plus the tool
  and data endpoints you choose, nothing else).
- **We do not use your governance records or conversation data to train models.**
  This is an operating commitment, not just a software default.

---

## Access model

- **We require administrative access to the SAFi host** so we can install system
  dependencies, deploy SAFi, manage configured tool servers, and apply updates.
  This access is limited to the SAFi machine and does not extend to the rest of
  your environment unless you separately authorize integrations.
- **Root or equivalent privileges may be required depending on the deployment
  method.** Running SAFi can require installing MCP tool servers, system packages,
  and updates. This matches SAFi's own security model, where installing a tool is
  gated behind host access precisely because it can mean running external code.
- **We need no reach beyond that one machine.** No other servers, no your
  databases, no broader access to your account.
- **You control our access.** You grant us controlled administrative access using
  credentials issued and governed by your organization. You retain the ability to
  audit, rotate, restrict, and revoke that access at any time.
- **You keep ultimate control.** It is your machine in your environment. You can
  snapshot it, inspect it, restrict its egress, revoke our access, or power it off
  at any time.
- **We can make our access auditable.** Optional bastion access with session
  logging, so every administrative action we take on your box is recorded and
  reviewable by you.

---

## Pricing

Pricing and service levels are scoped to the deployment, operating requirements,
support window, and recovery objectives. The structure below describes the
standard model and is finalized in a written statement of work and service
agreement. You always pay your hosting provider for the machine at cost, with no
markup from us, and your model usage is billed by your AI provider directly,
because the keys are yours.

- **Setup: time and materials.** Installing SAFi is quick, but getting your
  organization live involves your security review, access provisioning,
  environment setup, and policy design, which move at your pace. We bill the setup
  phase hourly, with an estimate and a not-to-exceed cap agreed up front.
- **Run: a flat monthly fee.** Once you are live, a predictable monthly fee covers
  operating the instance: updates, monitoring, backups, incident response, and
  integrity attestation, with SLA tiers for teams and enterprises.
- **Bring your own keys.** You pay your provider directly for tokens. We never
  front, mark up, or pool your model spend.

For a quote scoped to your size and requirements, get in touch below.

---

## Who does what

| Area | We | You |
|---|---|---|
| Environment, networking, IAM | Advise | Own and pay |
| Access to the SAFi machine | Hold admin on that one machine | Grant, isolate, audit, and can revoke |
| Deploy and upgrades | Run them | Approve the windows |
| Backups and restore | Run them | Rely on them |
| Model provider keys | Never see them | Own and rotate them |
| Model usage cost | Not ours | Billed to you by your provider |
| Policies, agents, users | Help on request | Decide |
| Governance and conversation data | Never train on it | Own it |
| Integrity verification | Attest to it | Can verify it yourself |
| End-user support for your staff | Not ours | Your help desk |

---

## SLA outline (Team and Enterprise)

A starting template, finalized with you in a written service agreement.

- **Availability.** A monthly uptime target, measured on the SAFi service,
  excluding your hosting provider's own outages and maintenance windows we agree
  in advance.
- **Response times.** Severity-based. A service-down incident gets fast
  acknowledgement and continuous work to restore. Lower severities get
  next-business-day handling.
- **Backups and recovery.** Automated backups configured in customer-controlled
  storage according to an agreed retention period. Restore procedures are tested on
  an agreed schedule, and the service agreement defines the applicable recovery
  objectives and responsibilities.
- **Updates and security.** Feature releases on the SAFi cadence with your
  sign-off on the window. Security hotfixes applied promptly.
- **Integrity attestation.** Regular reports that the running Core Loop matches a
  published SAFi release by its TCB Fingerprint. Your team can review the release
  and verify the running deployment independently.
- **Data and exit.** Your data stays on your machine and is never used to train
  anything. On exit you keep the machine, the keys, and the data, with a clean
  handover.

---

## Onboarding, six steps

Usually a few days end to end, depending on how much policy setup you want from us.

1. **Choose the environment and size.** Your own servers or cloud, or our
   recommendation, sized to your expected load, starting small and scaling.
2. **We provision and deploy.** We stand up your Linux machine and deploy SAFi
   from a published, integrity-verified release, using the deployment path
   confirmed during scoping.
3. **Domain, TLS, and verification.** Your domain goes live over HTTPS, and we
   confirm the running Core Loop matches the release by its TCB Fingerprint.
4. **You add your API keys.** Entered in the app, stored according to the
   deployment's security controls, never accessible to us through our operating
   procedures.
5. **Set up your organization.** Your policies, agents, and users, self-serve or
   with our help.
6. **Handover and go live.** We hand over access, start monitoring, and the SLA
   clock begins.

---

## What this is not

- **Not a reseller of model access.** You bring your own keys and pay your
  provider directly.
- **Not custom engineering.** Operating stock SAFi is the service. Bespoke
  features or plugins are a separate engagement.
- **Not your compliance team.** SAFi produces the evidence; deciding your policies
  and reading your audit trail is your call, though we can advise.
- **Not your help desk.** We keep the platform running; supporting your own staff
  stays with your internal support.

---

## Start with a managed SAFi deployment

If you want to pilot or use SAFi but do not want your team to carry the full
operational burden immediately, we can help.

Use the form on the [Get Involved](https://selfalignmentframework.com/get-involved/)
page and mention managed hosting. We will discuss your environment, deployment
requirements, security controls, expected usage, and path to internal ownership,
then provide a scoped estimate.

You bring the environment and resources. We bring the operational expertise. You
retain control throughout.
