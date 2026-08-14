# ISO/IEC 42001 Readiness

**Last updated:** August 2026. Part of SAFi's per-regime readiness series,
with `EU_AI_ACT_READINESS.md`, `SEC_COMPLIANCE_READINESS.md`, and
`HIPAA_READINESS.md`.

This document describes how ISO/IEC 42001 relates to a SAFi deployment, the
platform capabilities that ship today (§2), and what remains the deploying
organization's own work (§3).

> **This is not legal advice, and nothing here is a compliance certification.**
> ISO/IEC 42001 certifies organizations, never products. SAFi cannot be
> "42001 certified" and no deployment becomes certified by installing it.
> What SAFi provides is the operational layer of a certifiable AI management
> system: the runtime controls, and the evidence that those controls ran.

---

## 1. How the standard applies

- **What it is.** ISO/IEC 42001:2023 defines an AI management system (AIMS):
  the organizational processes for governing AI responsibly, in the same
  family as ISO 27001 for information security. It is voluntary, certifiable
  by accredited auditors, and increasingly appears as a procurement
  requirement for AI vendors and deployers in regulated industries.
- **Who gets certified.** The deploying organization. The certificate
  attests that the organization's management system meets clauses 4 through
  10 of the standard and that it has selected and implemented controls from
  Annex A with a documented statement of applicability.
- **Where SAFi sits.** An AIMS needs two things a document repository cannot
  supply: controls that operate at runtime, and evidence that they operated
  on every interaction. SAFi is built to be that layer. The per-regime
  readiness documents in this series then slot into the AIMS as the
  regulatory context the standard's clause 4 asks the organization to
  identify.
- **The distinctive claim.** Most 42001 evidence is documentation: policies,
  meeting minutes, training records. SAFi's evidence is operational: every
  governed turn produces a hash-chained audit record that carries the
  policy version that governed it, the per-value evaluation, the
  deterministic decision, and the fingerprint of the verified code that
  produced it. An auditor asking "show me this control operating" gets the
  turn itself, not a description of it.

## 2. What SAFi provides today

Everything in this section is shipped and running, not planned. Mappings
reference Annex A control groups by theme.

- **AI policy that executes (A.2).** Charters, policies, and value rubrics
  are machine-enforced configuration, not prose. Policies are versioned, and
  every governed turn records the `policy_id` and `policy_version` that
  governed it, so the deployer can show which policy was in force for any
  historical interaction and when a policy change took effect.
- **Roles and accountability (A.3).** Role-based access control ships in
  the verified core: the meaning of each role (who may approve, edit,
  audit, operate) is an invariant, while role assignment stays organization
  data. Supervisory dispositions carry the reviewer's identity and a
  mandatory written reason, journaled in the same tamper-evident trail as
  the records they supervise.
- **Lifecycle control and operation logging (A.6).** Every turn passes a
  staged governance sequence with deterministic enforcement, and produces
  both a hash-chained audit trail entry and an encrypted per-turn
  governance record. Deployment integrity is itself attested: the release
  manifest (`scripts/core_integrity_manifest.json`) enumerates the files
  governance depends on, `scripts/verify_integrity.py` verifies any
  deployment against it, the application re-verifies at startup, and each
  governance record is stamped with the resulting fingerprint. The written
  post-deployment monitoring plan is published at `docs/MONITORING_PLAN.md`.
- **Data governance (A.7).** Application-layer encryption at rest covers
  content and governance evidence; the retention engine and legal-hold
  precedence, the right-of-access export, and the written erasure position
  (`docs/DATA_ERASURE_AND_RETENTION.md`) cover records management.
  Knowledge-base documents used for retrieval pass a review workflow that
  records the reviewer, the decision, and the timestamp.
- **Transparency to interested parties (A.8).** A permanent AI-interaction
  disclosure in the interface, machine-readable provenance markers on every
  AI-output surface, per-value written justifications visible to the end
  user on each response, incident notification clocks with examiner-ready
  export, and self-service data export for individuals.
- **Responsible use and human oversight (A.9).** Each agent carries a scope
  statement enforced at runtime, deterministic hard gates that cannot be
  argued past, and a supervisory review queue that samples turns by
  deterministic, recomputable rules: every hard-gate block, gateway
  violations, low-alignment turns, consistency drops, plus a random sample.
- **Third-party relationships (A.10).** A per-org model provider allow-list
  enforced fail-closed at every dispatch point, provider capability badges
  (zero-data-retention, BAA-capable, EU-hostable), and the `/evaluate`
  gateway's `caller_obligations`, which restates downstream duties to every
  external caller in every response.
- **Performance evaluation (clause 9).** The standard requires monitoring,
  measurement, analysis, and evaluation of the AIMS. SAFi's Spirit faculty
  computes per-turn alignment and longitudinal drift against the governing
  values; the Audit Hub aggregates alignment trends, consistency, review
  throughput, and violation patterns; threshold alerts on degradation are
  journaled append-only and optionally delivered to a signed webhook. This
  is continuous, quantitative clause 9 input rather than a periodic manual
  exercise.

## 3. What remains the organization's

A management system is mostly management. SAFi supplies controls and
evidence for the operational clauses; the following are the deploying
organization's own work, and no tool substitutes for them.

- **AI impact assessments (A.5).** SAFi produces the data an assessment
  draws on (audit records, alignment trends, violation history) but has no
  impact-assessment module. The assessment process, its documentation, and
  its review cadence are organizational.
- **Context, leadership, and planning (clauses 4 to 6).** Identifying
  interested parties and applicable regulation, leadership commitment, the
  AI policy document itself (SAFi enforces policy; the organization still
  authors and owns it), risk assessment and treatment, and the statement of
  applicability.
- **Support and competence (clause 7).** Training, awareness, and competence
  records for the people who operate and supervise the system.
- **Internal audit and management review (clauses 9.2, 9.3, 10).** The
  audit program, management review meetings, nonconformity handling, and
  continual improvement. SAFi's exports and metrics are designed to feed
  these processes, not to perform them.
- **Certification itself.** Engaging an accredited certification body,
  scoping the AIMS, and maintaining it between surveillance audits.

## 4. Deployer notes

- If you are building a statement of applicability, this document's §2 is
  organized to map onto it: for each selected Annex A control, cite the
  SAFi mechanism and name the evidence artifact your auditor will see
  (audit records, governance-record exports, review dispositions, integrity
  fingerprints, Audit Hub metrics).
- The integrity check is part of your evidence chain. Run
  `scripts/verify_integrity.py` on your deployment and keep the reported
  fingerprint with your audit records; every governance record you produce
  already carries it.
- If your AIMS scope includes obligations under specific regimes (EU AI
  Act, SEC/FINRA, HIPAA), use the matching readiness document in this
  series for the per-regime detail; this document deliberately stays at the
  management-system level.
