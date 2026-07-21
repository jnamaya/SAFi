# SAFi and SEC/FINRA-Regulated Deployments

**Last updated:** July 2026.

This document describes the regulatory landscape that applies when a broker-dealer
(BD) or registered investment adviser (RIA) deploys AI systems, and the SAFi
platform capabilities designed to support firms operating under those rules.

> **This is not legal advice, and nothing here is a compliance certification.**
> SAFi is a governance platform; regulatory compliance is always the deploying
> firm's responsibility, made with its own counsel and compliance officers. The
> capabilities below are design features intended to *support* a firm's
> compliance program, not substitutes for one.

---

## 1. Regulatory landscape (as of July 2026)

### 1.1 Recordkeeping — SEA Rule 17a-4 (BDs) / Advisers Act Rule 204-2 (RIAs)

- The 2022 amendments to Rule 17a-4 (compliance date May 3, 2023) ended the
  exclusive WORM mandate. Firms may instead use the **audit-trail alternative**
  (17 CFR 240.17a-4(f)(2)(i)(A)): for each record's full retention period, keep a
  complete time-stamped audit trail of all create/modify/delete actions — the
  adopting release states this covers "both human-initiated and automated
  actions" — with an actor identifier and enough information to re-create the
  original record if it is modified or deleted.
- **Retention periods:** 3–6 years for BD records (communications: 3 years);
  5 years for RIA books and records under Rule 204-2, first two years easily
  accessible.
- **Enforcement stakes:** the 2021–2024 off-channel-communications sweep produced
  $2B+ in settlements across BDs and RIAs. *SEC v. Arete Wealth* (N.D. Ill.,
  Feb 27, 2026) held the recordkeeping rules enforceable as written.
  Chat-record preservation remains a top enforcement exposure.
- **Unsettled:** as of mid-2026, neither the SEC nor FINRA has issued dispositive
  guidance on whether AI prompts/responses are themselves required records, or
  whether internal AI reasoning logs and agent-to-agent outputs are preservable
  "communications." The conservative posture — retain everything under the
  audit-trail standard — is the one SAFi's design assumes.
- **Watch item:** the SEC's rulemaking agenda reportedly includes a planned
  Rule 17a-4 clarification for AI-generated records.

### 1.2 Regulation S-P (2024 amendments) — fully in effect

Both compliance tiers have passed (Dec 3, 2025 and June 3, 2026). Every covered
institution must have:

- A **written incident-response program** (detection, assessment, containment,
  notification).
- **Customer breach notice** no later than **30 days** after becoming aware that
  unauthorized access has or is reasonably likely to have occurred, absent a
  documented harm determination.
- **Service-provider oversight** (17 CFR 248.30(a)(5)): due diligence and
  monitoring of service providers — including LLM and cloud vendors that access
  customer information — with contractual vendor-to-firm breach notice no later
  than **72 hours** after the vendor becomes aware.
- Exam staff have signaled Reg S-P compliance is an active FY2026 examination
  focus.

### 1.3 AI-specific exam posture

- The predictive-data-analytics conflicts proposal (S7-12-23) was formally
  withdrawn in June 2025; obligations flow entirely from existing frameworks.
- **FY2026 exam priorities** name two AI targets: accuracy of registrant
  representations about AI capabilities (**AI-washing**), and adequacy of
  policies and procedures to monitor and supervise AI use.

### 1.4 FINRA supervision — Rules 3110/3120

- Regulatory Notice 24-09 applies the existing rulebook to gen-AI on a
  technology-neutral basis: evaluate gen-AI tools before deployment; supervisory
  procedures should address model risk management, data privacy and integrity,
  and model reliability.
- FINRA's 2026 Annual Regulatory Oversight Report adds concrete expectations:
  governance and model-risk frameworks, **prompt-and-output logging, model
  version tracking, human-in-the-loop review**, and first-time discussion of
  AI-agent risks.

---

## 2. Platform capabilities

SAFi's governance architecture was designed for auditability first, which maps
directly onto the expectations above.

*A note on terminology:* SAFi's internal architecture names its pipeline stages
after classical faculties (Intellect, Will, Conscience, Spirit), and audit
records and export fields carry those names. This document uses the product's
user-facing vocabulary, with the internal field names noted in parentheses
where an examiner would encounter them in exported records.

- **Hash-chained audit trail** — every chat-record create/modify/delete is
  journaled in an append-only, SHA-256 hash-chained trail with a timestamp and
  actor identifier (human or automated), and enough state to re-create the
  original record. Designed to support the 17a-4 audit-trail alternative;
  integrity is verifiable per message.
- **Per-turn governance record** — every response carries an itemized
  evaluation against each value in the governing policy (recorded as the
  conscience ledger), an Alignment Score from 0–10 produced by an independent
  evaluation model (recorded as `spirit_score`), the enforcement decision that
  approved, blocked, or redirected the response (recorded as the will
  decision), the governing policy ID and version, and the model that produced
  the response.
- **Immutable policy versioning** — policy snapshots survive policy deletion, so
  an auditor can always retrieve the exact policy version that governed a given
  turn.
- **Encryption at rest** — user content, OAuth tokens, and the full per-turn
  governance record (drafts, evaluations, context snapshots) are encrypted at
  the application layer with key-rotation support. Governance detail is
  written only to the encrypted database, where the retention engine and
  legal hold govern its lifecycle.
- **Incident registry** — an org-scoped, append-only incident log with the
  Reg S-P 30-day customer-notification clock computed from firm awareness, the
  72-hour vendor-notice check, documented harm-determination support, and
  examiner export with chain-of-custody logging.
- **Retention engine and legal hold** — per-org retention configuration
  (default: keep forever), legal hold that suspends all destruction, a purge
  engine with safety rails, and a date-range examiner production/export API.
  All retention-config changes and exports are recorded in an append-only
  compliance evidence log. The written position reconciling GDPR erasure
  with retention obligations (Art. 17(3)(b) legal-obligation carve-out,
  legal-hold precedence) is published at `docs/DATA_ERASURE_AND_RETENTION.md`.
- **Per-org LLM provider allow-list** — each organization can restrict which
  LLM providers may receive its content. Enforcement is fail-closed across
  every model call in the pipeline (including internal evaluation stages), a
  disallowed provider is rejected at request time rather than rerouted, and
  every allow-list change is recorded in the append-only compliance evidence
  log. Each turn's audit record attributes the specific provider and model
  that produced and evaluated the response. Designed to support Reg S-P
  service-provider oversight (17 CFR 248.30(a)(5)).
- **Enterprise identity and MFA** — server-side revocable sessions with
  org-configurable idle and absolute timeouts, TOTP multi-factor
  authentication for local accounts, per-tenant SSO enforcement (Microsoft
  Entra tenant and Google Workspace domain pinning) with MFA evidence checks
  at sign-in, an org-level require-MFA setting, and an append-only
  authentication event journal (sign-ins, denials, session revocations).
- **Role-based access control** — including a dedicated auditor role.
- **Supervisory review queue** — org-configurable sampling of governed turns
  into a human review queue: a deterministic random sample (a published hash
  rule, so an examiner can recompute exactly which turns were due — sampling
  cannot be cherry-picked) plus rule triggers covering every hard-gate block,
  gateway violations, low-Alignment turns, and Consistency drops. Reviewers
  (admin and auditor roles only) approve or override each item; overrides
  require a written reason. Every disposition is appended to the same
  hash-chained audit trail as the record under review, attributed to the
  authenticated reviewer. Coverage reporting (turns, sampled, dispositions,
  review latency) exports to CSV with chain-of-custody logging, and all
  sampling-rule changes are recorded in the compliance evidence log.
  Supports FINRA 3110/3120 supervisory review; review is post-hoc
  supervision — an override documents the firm's determination about a
  delivered response, it does not retract it.
- **Post-market monitoring alerts** — threshold alerts for rolling Alignment
  degradation per agent, per-turn Consistency drops, and review-queue
  backlog, journaled to an append-only alert log, surfaced in-app, and
  optionally pushed to a firm webhook signed with HMAC-SHA256 (delivery
  outcomes journaled). Thresholds are org-configurable and evidence-logged.
  The written monitoring plan is published at `docs/MONITORING_PLAN.md`.
- **Right of access** — any user can self-service download everything the
  platform stores about them (account, conversations with their governance
  results, projects, saved items, memory), decrypted and strictly
  self-scoped. Every download is recorded in the compliance evidence log.
  Supports GDPR Art. 15 and HIPAA §164.524 access requests without operator
  involvement.
- **Audit Hub** — an org-scoped analytics surface over the encrypted
  governance records: alignment/consistency KPIs and trends, a filterable
  log explorer, and a per-turn drill-down showing the full evidence behind
  each enforcement decision, with the record's hash-chain verification
  displayed inline. Access uses the same server-side revocable sessions and
  role checks as the rest of the product, and every download of decrypted
  governance data is recorded in the append-only compliance evidence log
  (chain of custody), mirroring the examiner export.

- **Provider data-retention posture (ZDR)** — each LLM provider in the
  allow-list carries its verified zero-data-retention posture (retained by
  default / ZDR available on an enterprise basis / no ZDR option), surfaced
  next to the BAA and EU-hosting badges so an org can compose its provider
  set against its retention obligations. Verified against official provider
  documentation (July 2026); contractual ZDR agreements with providers remain
  the customer's to execute.

## 3. Roadmap

Planned work, in priority order:

1. **SOC 2 Type II program.**
2. **SAML SSO and SCIM provisioning** — available on enterprise demand,
   building on the shipped OIDC per-tenant enforcement.
3. **Regulatory tracking** — the pending 17a-4 AI-records clarification and the
   amended paragraph (i) hosting-undertaking question for hosted deployments.

## 4. Key sources

- SEC Release 34-96034 (17a-4 amendments, final rule) — sec.gov/files/rules/final/2022/34-96034.pdf
- SEC staff FAQ on the broker-dealer recordkeeping amendments — sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/rule-amendments-broker
- SEC Release 34-100155 (Reg S-P amendments, final rule) — sec.gov/files/rules/final/2024/34-100155.pdf
- 17 CFR 240.17a-4 and 17 CFR 248.30 via eCFR (2026-07-01 edition)
- SEC Division of Examinations FY2026 Priorities (Nov 17, 2025) — sec.gov/about/reports-publications/2026-examination-priorities
- S7-12-23 withdrawal (June 2025) — sec.gov/rules-regulations/2025/06/s7-12-23; 90 FR 25531
- FINRA Regulatory Notice 24-09; FINRA 2026 Annual Regulatory Oversight Report (Dec 9, 2025)
