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
directly onto the expectations above:

- **Hash-chained audit trail** — every chat-record create/modify/delete is
  journaled in an append-only, SHA-256 hash-chained trail with a timestamp and
  actor identifier (human or automated), and enough state to re-create the
  original record. Designed to support the 17a-4 audit-trail alternative;
  integrity is verifiable per message.
- **Per-turn governance ledger** — every response carries its Conscience
  evaluation, Spirit alignment score, Will decision, governing policy ID and
  version, and the model that produced it.
- **Immutable policy versioning** — policy snapshots survive policy deletion, so
  an auditor can always retrieve the exact policy version that governed a given
  turn.
- **Encryption at rest** — user content and OAuth tokens are encrypted at the
  application layer with key-rotation support.
- **Incident registry** — an org-scoped, append-only incident log with the
  Reg S-P 30-day customer-notification clock computed from firm awareness, the
  72-hour vendor-notice check, documented harm-determination support, and
  examiner export with chain-of-custody logging.
- **Retention engine and legal hold** — per-org retention configuration
  (default: keep forever), legal hold that suspends all destruction, a purge
  engine with safety rails, and a date-range examiner production/export API.
  All retention-config changes and exports are recorded in an append-only
  compliance evidence log.
- **Role-based access control** — including a dedicated auditor role.

## 3. Roadmap

Planned work, in priority order:

1. **Compliance supervision workflow** — sampling, flagging, and sign-off tooling
   for compliance officers over the per-turn governance data, per FINRA's
   human-in-the-loop expectations.
2. **Enterprise identity** — MFA and SAML SSO.
3. **SOC 2 Type II program** and enterprise/zero-data-retention LLM endpoint
   options as per-org policy.
4. **Regulatory tracking** — the pending 17a-4 AI-records clarification and the
   amended paragraph (i) hosting-undertaking question for hosted deployments.

## 4. Key sources

- SEC Release 34-96034 (17a-4 amendments, final rule) — sec.gov/files/rules/final/2022/34-96034.pdf
- SEC staff FAQ on the broker-dealer recordkeeping amendments — sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/rule-amendments-broker
- SEC Release 34-100155 (Reg S-P amendments, final rule) — sec.gov/files/rules/final/2024/34-100155.pdf
- 17 CFR 240.17a-4 and 17 CFR 248.30 via eCFR (2026-07-01 edition)
- SEC Division of Examinations FY2026 Priorities (Nov 17, 2025) — sec.gov/about/reports-publications/2026-examination-priorities
- S7-12-23 withdrawal (June 2025) — sec.gov/rules-regulations/2025/06/s7-12-23; 90 FR 25531
- FINRA Regulatory Notice 24-09; FINRA 2026 Annual Regulatory Oversight Report (Dec 9, 2025)
