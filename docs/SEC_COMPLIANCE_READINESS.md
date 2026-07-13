# SAFi — SEC Compliance Readiness

**Status of research:** July 13, 2026. Findings below were produced by a multi-agent
deep-research pass (23 sources fetched, 25 claims verified 3–0 against primary sources:
SEC adopting releases, eCFR text current to 2026-07-01, FINRA notices, FY2026 exam
priorities). Zero claims were refuted.

**Scope:** What a broker-dealer (BD) or registered investment adviser (RIA) needs in
order to deploy SAFi, and the platform gaps that must close first.

---

## 1. Regulatory landscape (verified, as of July 2026)

### 1.1 Recordkeeping — SEA Rule 17a-4 (BDs) / Advisers Act Rule 204-2 (RIAs)

- The 2022 amendments to Rule 17a-4 (effective Jan 3, 2023; compliance May 3, 2023;
  unamended since) **ended the exclusive WORM mandate**. Firms may instead use the
  **audit-trail alternative** (17 CFR 240.17a-4(f)(2)(i)(A)): for each record's full
  retention period, keep a complete time-stamped audit trail of all create/modify/delete
  actions — the adopting release states this "encompasses both human-initiated and
  automated actions" — with a unique actor identifier ("if applicable" was added
  precisely because automated systems, not people, are often the actor), and enough
  information to **re-create the original record if it is modified or deleted**.
  Electing the alternative means complying with paragraphs (f)(1)–(3) and (j),
  including prompt production to regulators.
  Sources: SEC Release 34-96034; SEC staff FAQ; eCFR (2026-07-01 edition).
- **D3P alternative:** instead of a traditional designated third party, a BD may
  designate an executive officer (with record access, directly or through a specialist)
  to execute the regulatory-access undertakings, with up to two employee delegates and
  three designated specialists (17a-4(f)(3)(v)).
- **Hosting implication:** cloud/hosting providers may need to file a Traditional or
  Alternative Undertaking with the SEC under amended paragraph (i). This must be
  resolved before SAFi's first hosted BD deployment.
- **Retention periods:** 3–6 years for BD records (communications: 3 years); 5 years
  for RIA books and records under Rule 204-2, first two years easily accessible.
- **Enforcement stakes:** 77 FINRA member firms settled SEC off-channel-communications
  actions 2021–2024 ($2B+ across the broader sweep including RIAs); each was statutorily
  disqualified until the SEC's January 2025 settlements softened the structure. Despite
  Chairman Atkins publicly repudiating the sweep, *SEC v. Arete Wealth* (N.D. Ill.,
  Feb 27, 2026) denied a motion to dismiss and held the recordkeeping rules enforceable
  as written. Chat-record preservation remains the top enforcement exposure.
- **Unsettled:** as of June 2026, neither the SEC nor FINRA has issued dispositive
  guidance on whether AI prompts/responses are themselves required records, or whether
  internal AI reasoning logs (e.g., SAFi's faculty ledger) and agent-to-agent outputs
  are preservable "communications." Firms make risk-based judgments. The conservative
  design — retain everything under the audit-trail standard — is also the cheapest for
  SAFi, since the logging already captures it.
- **Watch item:** the current SEC rulemaking agenda reportedly includes a planned
  Rule 17a-4 clarification for AI-generated records. When proposed, revisit this
  analysis.

### 1.2 Regulation S-P (2024 amendments) — fully in effect

Both compliance tiers have passed: larger entities (RIAs ≥ $1.5B AUM; all non-small
BDs) Dec 3, 2025; smaller entities June 3, 2026. As of June 2026 **every covered
institution** must have:

- A **written incident-response program** reasonably designed to detect, respond to,
  and recover from unauthorized access to customer information (assessment,
  containment, notification).
- **Customer breach notice** as soon as practicable, no later than **30 days** after
  becoming aware unauthorized access has or is reasonably likely to have occurred.
  Only exception: a documented reasonable-investigation determination that sensitive
  customer information is not reasonably likely to be used in a way causing substantial
  harm or inconvenience. Delay only via written Attorney General determination.
- **Service-provider oversight** (17 CFR 248.30(a)(5)): written policies requiring due
  diligence and monitoring of service providers — which includes LLM and cloud vendors
  that receive, maintain, process, or access customer information — with contractual
  vendor-to-firm breach notice **no later than 72 hours** after the vendor becomes
  aware. The customer-notification obligation stays with the covered institution even
  if delegated.
- Nuance: a zero-data-retention LLM configuration *reduces* but does not *eliminate*
  the oversight duty — it attaches whenever the vendor accesses customer information
  at all.
- Exam staff have signaled Reg S-P compliance is an active FY2026 examination focus.

### 1.3 AI-specific rulemaking and exam posture

- The predictive-data-analytics conflicts proposal (S7-12-23) was **formally withdrawn
  June 2025** with an explicit statement that no final rule is coming; nothing has been
  re-proposed as of July 2026. Obligations flow entirely from existing frameworks.
- **FY2026 exam priorities** (published Nov 17, 2025) name two AI targets verbatim:
  examiners "will review for accuracy registrant representations regarding their AI
  capabilities" (**AI-washing**) and "will assess whether firms have implemented
  adequate policies and procedures to monitor and/or supervise their use of AI
  technologies." Third consecutive year AI appears in exam priorities.
- Product implication: quantitative governance claims (e.g., the "99.86% of 1,435+
  jailbreak attempts failed" figure in `rag/docs/26_SAFi_Scope_Compliance_Defense.md`)
  become representations a regulated customer may repeat to examiners. Every such
  number needs a documented, reproducible methodology behind it.

### 1.4 FINRA supervision — Rules 3110/3120

- Regulatory Notice 24-09 (June 2024) applies the existing rulebook to gen-AI on a
  technology-neutral basis: firms should evaluate gen-AI tools **before deployment**,
  and Rule 3110 supervisory procedures should address technology governance including
  model risk management, data privacy and integrity, and model reliability/accuracy.
- FINRA's 2026 Annual Regulatory Oversight Report (Dec 9, 2025) adds concrete
  expectations: governance/model-risk frameworks, **prompt-and-output logging, model
  version tracking, human-in-the-loop review**, and first-time discussion of AI-agent
  risks.
- SAFi already satisfies the logging/versioning expectations (JSONL logs capture
  prompts, drafts, final outputs, Conscience ledgers, `policyId`/`policyVersion`,
  intellect model per turn). The missing piece is a **supervisory review workflow**
  (sampling, flagging, compliance sign-off).

### 1.5 Vendor due diligence

The binding duty is Reg S-P 248.30(a)(5) due diligence + monitoring + 72-hour breach
notice. SOC 2 reports and zero-data-retention clauses are **industry practice layered
on that duty** — no primary source ties them to specific SEC/FINRA exam findings, but
they are what regulated buyers will demand in procurement (DDQs).

---

## 2. Gap analysis — SAFi platform (as of July 2026)

| Area | Current state | Required state |
|------|--------------|----------------|
| Audit record mutability | `chat_history` rows freely UPDATEd (audit results, content edits, cancellations) and hard-DELETEd via cascade; JSONL logs are plain writable files; `audit_snapshots` SHA-256 table exists but has **zero callers** | Audit-trail alternative: version every mutation with timestamp + actor ID; originals re-creatable; soft-delete within retention window |
| Retention | None (only 24h demo-user purge); no legal hold; export only via Streamlit download button | Per-org retention config (3–6 yr BD / 5 yr RIA, 2 yr easily accessible); legal hold; prompt-production export API |
| Encryption at rest | None — content and OAuth access/refresh tokens in plaintext MySQL | Encrypt content + tokens; KMS-backed secrets (currently `.env`) |
| Incident response | None | Written IRP support: detection hooks, 30-day-clock notification workflow, harm-investigation documentation |
| LLM vendor flow | Prompts + faculty evaluations sent to consumer-tier Groq/Gemini/etc. by default | Enterprise/ZDR endpoints as per-org policy; 72-hour breach-notice flow-down contracts; data-flow map for DDQs |
| Access control | OAuth (Google/Microsoft) + local admin; 4-role RBAC; no MFA/SAML/SCIM; no session timeout | MFA, SAML SSO, SCIM, idle timeout |
| Audit-log authorization | Dashboard access decided by substring search of user_id/org_id in raw JSONL text (5 newest files only) — spoofable | Real DB-enforced authorization boundary |
| Supervision workflow | Rich per-turn governance data, no review workflow | Sampling/flag/sign-off workflow for compliance officers |
| Attestation | None | SOC 2 Type II program (organizational, usually the procurement gate) |

**Strengths already in place:** per-turn Conscience ledger / Spirit scores / Will
decisions with policy + model attribution; immutable `policy_versions` snapshots that
survive policy deletion ("so an auditor can always retrieve the exact version that
ran"); auditor role in RBAC. These map point-for-point onto FINRA's 2026 supervision
expectations and are the platform's strongest selling point in this market.

---

## 3. Roadmap (priority order)

1. **Versioned audit trail** (audit-trail alternative, not WORM): wire up the dormant
   `audit_snapshots` mechanism; snapshot prior state on every `chat_history` mutation
   with timestamp + actor identifier; convert cascade hard-deletes to soft deletes
   within the retention window.
2. **Reg S-P package** (fully in effect now): encryption at rest for content and OAuth
   tokens; incident-response tooling with a 30-day-clock workflow; 72-hour
   breach-notice flow-down terms with LLM providers.
3. **Retention engine + export API**: per-org retention config, legal hold, prompt
   production for the executive-officer/D3P pathway.
4. **Supervision**: DB-enforced audit-log authorization (replace substring match);
   MFA/SAML; compliance review workflow over Conscience/Spirit data.
5. **Business side**: SOC 2 program; resolve the paragraph (i) hosting-undertaking
   question; substantiation files for every quantitative governance claim; track the
   pending 17a-4 AI-records proposal.

---

## 4. Open questions

1. Does Advisers Act Rule 204-2 reach internal AI reasoning/governance logs (SAFi's
   faculty audit trail), or only client-facing communications? No 2025–2026 staff
   guidance or deficiency letter found.
2. What will the SEC's planned 17a-4 clarification for AI-generated records propose,
   and does it change the audit-trail vs. WORM analysis?
3. Where do examiners draw the line on agent-to-agent AI outputs as preservable
   "communications"?
4. Which specific AI-washing enforcement actions (beyond Delphia/Global Predictions,
   March 2024) calibrate how SAFi's governance claims should be worded in marketing?

---

## 5. Key sources

- SEC Release 34-96034 (17a-4 amendments, final rule) — sec.gov/files/rules/final/2022/34-96034.pdf
- SEC staff FAQ on the broker-dealer recordkeeping amendments — sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/rule-amendments-broker
- SEC Release 34-100155 (Reg S-P amendments, final rule) — sec.gov/files/rules/final/2024/34-100155.pdf
- 17 CFR 240.17a-4 and 17 CFR 248.30 via eCFR (2026-07-01 edition)
- SEC Division of Examinations FY2026 Priorities (Nov 17, 2025) — sec.gov/about/reports-publications/2026-examination-priorities
- S7-12-23 withdrawal (June 2025) — sec.gov/rules-regulations/2025/06/s7-12-23; 90 FR 25531
- FINRA Regulatory Notice 24-09; FINRA 2026 Annual Regulatory Oversight Report (Dec 9, 2025)
- FINRA blog on off-channel settlements and SRO collateral consequences (May 8, 2025)
- *SEC v. Arete Wealth Management* MTD denial coverage (Harvard Law corpgov, Mar 18, 2026)
- ABA Business Law Today, "AI Prompts and Responses: Records or Not, Here We Come" (June 2026)
