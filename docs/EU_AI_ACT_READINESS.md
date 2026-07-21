# EU AI Act Compliance Readiness

**Last updated:** July 2026 (post-Omnibus). Part of SAFi's per-regime
readiness series, with `SEC_COMPLIANCE_READINESS.md` and
`HIPAA_READINESS.md`.

This document describes how the EU AI Act applies to a SAFi deployment, the
platform capabilities that ship today (§2), and what remains pending (§3).

> **This is not legal advice, and nothing here is a compliance certification.**
> SAFi is a governance platform; regulatory compliance is always the deploying
> organization's responsibility, made with its own counsel. The capabilities
> below are design features intended to *support* a deployer's obligations,
> not substitutes for them.

---

## 1. How the Act applies (as of July 2026)

- **Role.** SAFi is an AI-system *provider* that builds on third-party
  foundation models — it is not a general-purpose AI (GPAI) model provider.
  The organization deploying SAFi is a *deployer* with its own obligations
  (notably Art. 26 and the Art. 50 transparency duties toward its users).
- **Risk tier.** A governed chat assistant is a limited-risk (transparency)
  system under **Art. 50**. A deployment only enters the **high-risk**
  Chapter III regime if it is used for an Annex III purpose (for example
  creditworthiness decisions, employment screening, or access to essential
  services) — that is a property of the use case, not of the platform.
- **Deadlines after the 2026 Digital Omnibus:** Art. 50(1) AI-interaction
  disclosure applies from **August 2, 2026**; Art. 50(2) machine-readable
  marking of AI-generated content from **December 2, 2026**; Annex III
  high-risk obligations are deferred to **December 2, 2027**.

## 2. What SAFi provides today

Everything in this section is shipped and running, not planned.

- **Art. 50(1) — AI-interaction disclosure.** The chat interface carries a
  permanent, always-visible notice that the user is interacting with an AI
  system, with a policy-linked variant for governed agents. The evaluation
  gateway (`/evaluate`) repeats the disclosure duty to external callers in
  every response (`caller_obligations`), because the disclosure obligation
  travels with whoever faces the end user.
- **Art. 50(2) — machine-readable marking.** Every AI-output surface carries
  a provenance marker: chat, bot, and gateway responses embed an
  `aiProvenance` object and an `X-AI-Generated` HTTP header; synthesized
  audio carries the header; exported records mark each AI message
  individually. The gateway's marker uses evaluator-only semantics — SAFi
  never claims authorship of an external agent's output.
- **Art. 12 — record-keeping.** Every governed turn produces a hash-chained,
  tamper-evident audit trail entry and an encrypted per-turn governance
  record (the full evaluation evidence), with per-message integrity
  verification.
- **Art. 13 — transparency of operation.** Each response carries an
  itemized, human-readable evaluation against the governing policy's values
  (per-value scores, confidence, and written justifications), visible to the
  end user and in the org's Audit Hub.
- **Art. 14 — human oversight.** A supervisory review queue samples governed
  turns by deterministic, recomputable rules (every hard-gate block, gateway
  violations, low-alignment turns, consistency drops, plus a random sample).
  Reviewers approve or override with a mandatory written reason; each
  disposition is appended to the same tamper-evident trail as the record it
  supervises.
- **Art. 72 — post-market monitoring.** Threshold alerting on rolling
  alignment degradation, per-turn consistency drops, and review backlog,
  journaled append-only, surfaced in-app, and optionally delivered to a
  signed webhook. The written monitoring plan is published at
  `docs/MONITORING_PLAN.md`.
- **Art. 73 — serious-incident reporting clocks.** The incident registry
  computes the AI Act's reporting deadlines (15 days; 10 days for death;
  2 days for widespread infringement) alongside other regimes' clocks, from
  the moment of awareness, with examiner-ready export.
- **Data governance supports.** A per-org provider allow-list with
  EU-hostable and zero-data-retention badges lets a deployer constrain
  which model providers may receive its content (enforced fail-closed at
  every dispatch point); encryption at rest covers content and governance
  evidence; the retention engine, right-of-access export, and the written
  erasure position (`docs/DATA_ERASURE_AND_RETENTION.md`) cover the GDPR
  boundary.

## 3. Pending / roadmap

- **Bot-channel disclosure preambles.** The Art. 50(1) notice ships in the
  web app; first-message disclosure preambles for the Teams/Telegram bot
  channels and the WordPress widget (maintained outside this repository)
  remain to be added. Deployers using those channels today should add the
  disclosure at the channel level.
- **EU data residency is a configuration, not a default.** The provider
  allow-list gives deployers the lever (restrict to EU-hostable providers),
  but residency itself depends on the deployer's provider contracts and
  hosting choice. Self-hosting in the EU is fully supported.
- **High-risk (Annex III) conformity track — demand-triggered, due
  December 2027 only if a high-risk use case appears:** Annex IV technical
  documentation (the published mathematical specification and this
  readiness series cover a substantial part), Art. 9 risk-management
  system, Art. 17 quality-management system, Annex VI internal-control
  conformity assessment, CE marking, EU database registration, and an
  Art. 22 authorized representative for non-EU providers. None of this is
  required for limited-risk deployments.

## 4. Deployer notes

- If you deploy SAFi's outputs through your own interface (including via
  the `/evaluate` gateway), the Art. 50(1) disclosure duty to your end
  users is yours; SAFi repeats this in every gateway response.
- Whether your use case is Annex III high-risk is a legal determination
  about *your* use, not about the platform — make it with counsel before
  the December 2027 deadline becomes relevant to you.
