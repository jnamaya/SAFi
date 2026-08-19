# SAFi Managed Operator

> **We bring our talent. You bring your resources.**

We operate a dedicated SAFi instance in your own environment, keep it running,
and act as your operator. You bring your own AI model keys and own the whole
stack, and we can train your team to take over the operator role whenever you
want.

---

## The pitch

You do not have to change your infrastructure. SAFi runs wherever you do: on your
in-house servers, or in your own trusted cloud on Azure, AWS, GCP, or anywhere
else. You hire us to manage the SAFi machine, nothing more. Your data never
leaves your tenant, your AI model keys stay yours, and if you ever want to take
on the operator role yourself, we train your team to do it.

SAFi is open source, so you could run it yourself. Most organizations would
rather not learn to operate a governance engine. This is the middle path: your
resources, our talent. You provide the environment and the AI API keys; we
provide the expertise to run it well and keep it verifiably intact.

Why this works:

- It sits inside the security boundary you already trust. No new vendor cloud to
  vet, no data-residency fight, no unfamiliar hosting to procure.
- It fits how you already buy: you grant a managed provider access to operate one
  machine in your environment. A known, reviewable pattern.
- No lock-in, all the way down. Your infrastructure, your keys, your data,
  open-source software, and operations you can take over whenever you want.

---

## How it works: we operate, you own

### What we bring (the operator role)

- We provision and deploy SAFi on your Linux machine, from a published,
  integrity-verified release.
- We set up secure access at your own domain or subdomain (for example,
  safi.yourcompany.com) and the first-run configuration.
- We apply updates on the release cadence, plus security hotfixes.
- We run monitoring, backups, and tested restores.
- We attest integrity: the running TCB Fingerprint matches an official SAFi
  release, so your auditors can confirm the governance engine is unaltered.
- We handle incidents and routine health work (resource tuning, log rotation).
- We can train your IT team to operate SAFi themselves, whenever you want it.

### What you bring

- Your own environment: in-house servers, or a cloud account (Azure, AWS, GCP, or
  elsewhere), or a hosting provider we recommend and size. SAFi runs inside your
  boundary; we operate it there.
- Your own AI model provider API keys. They are stored encrypted, and we never
  see them.
- Your policies, agents, and users, which you set up self-serve or with our help.
- Ownership of all governance records and conversation data, at rest on your box.

---

## Environment and deployment

- **Your OS is Linux.** All of SAFi's tooling and the reference deployment assume
  Linux. This is a requirement, not a preference.
- **Docker or bare-metal, your choice.** SAFi runs either as a Docker stack or as
  a bare-metal install (a systemd service, a Python venv, and a reverse proxy).
  Both are fully supported, so we can meet your standard whether you run
  containers or hardened VM images.

---

## Access model

- **We need full admin of the SAFi machine (root SSH with your encryption keys),
  and nothing else in your environment**, unless you ask us to set up your
  identity server or other integrations. Running SAFi requires root: installing
  your MCP tool servers, system packages, and updates all need it. This matches
  SAFi's own security model, where installing a tool is gated behind host access
  precisely because it can mean running external code.
- **We need no reach beyond that one machine.** No other servers, no your
  databases, no broader access to your account.
- **You control the boundary.** You place the SAFi machine in its own subnet or
  resource group with a tight egress allowlist (your model providers plus the
  tool and data endpoints you choose, nothing else). Our root on the box cannot
  reach the rest of your environment.
- **You keep ultimate control.** It is your machine in your environment. You can
  snapshot it, inspect it, restrict its egress, revoke our access, or power it
  off at any time.
- **We can make our access auditable.** Optional bastion access with session
  logging, so every administrative action we take on your box is recorded and
  reviewable by you.

---

## Pricing

Two phases. You always pay your hosting provider for the box at cost, with no
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
| Access to the SAFi machine | Hold root on that one machine | Grant, isolate, audit, and can revoke |
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

A starting template, finalized with you.

- **Availability.** A monthly uptime target, measured on the SAFi service,
  excluding your hosting provider's own outages and maintenance windows we agree
  in advance.
- **Response times.** Severity-based. A service-down incident gets fast
  acknowledgement and continuous work to restore. Lower severities get
  next-business-day handling.
- **Backups and recovery.** Automated backups with a defined retention window,
  stored off the primary box, and a stated recovery objective.
- **Updates and security.** Feature releases on the SAFi cadence with your
  sign-off on the window. Security hotfixes applied promptly.
- **Integrity attestation.** Regular reports that the running Core Loop matches a
  published SAFi release by TCB Fingerprint.
- **Data and exit.** Your data stays on your box and is never used to train
  anything. On exit you keep the box, the keys, and the data, with a clean
  handover.

---

## Onboarding, six steps

Usually a few days end to end, depending on how much policy setup you want from us.

1. **Choose the environment and size.** Your own servers or cloud, or our
   recommendation, sized to your expected load, starting small and scaling.
2. **We provision and deploy.** We stand up your Linux machine and deploy SAFi
   from a published, integrity-verified release, as Docker or bare-metal per your
   standard.
3. **Domain, TLS, and verification.** Your domain goes live over HTTPS, and we
   confirm the running TCB Fingerprint matches the release.
4. **You add your API keys.** Entered in the app, stored encrypted, never visible
   to us.
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

## Get in touch

To discuss a managed deployment, use the form at the bottom of the
[Get Involved](https://selfalignmentframework.com/get-involved/) page and mention
managed hosting. We will follow up to scope your setup and give you a quote.
