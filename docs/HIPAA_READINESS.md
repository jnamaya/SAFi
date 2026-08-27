# HIPAA Compliance Readiness

**Last updated:** July 2026. Part of SAFi's per-regime readiness series, with
`SEC_COMPLIANCE_READINESS.md` and `EU_AI_ACT_READINESS.md`.

This document describes how HIPAA applies to a SAFi deployment handling
protected health information (PHI), the platform capabilities that ship
today (§2), and what remains pending (§3).

> **This is not legal advice, and nothing here is a compliance certification.**
> HIPAA has no certification regime — compliance is self-attested and
> OCR-enforced. The capabilities below are design features intended to
> *support* a covered entity's or business associate's compliance program,
> not substitutes for one. **No PHI should be processed on a SAFi deployment
> until the paperwork in §3 is executed.**

---

## 1. How HIPAA applies (as of July 2026)

- **Roles.** When SAFi is operated as a hosted service for a healthcare
  customer, the operator is a **business associate** of that covered entity
  and needs a BAA with the customer *and* with every subcontractor that
  touches PHI — which includes the LLM providers that process prompts. When
  a covered entity self-hosts SAFi, the software is tooling inside its own
  compliance boundary and the BAA chain is the deployer's to build.
- **The LLM BAA chain is the structural issue** for any AI deployment:
  most fast/cheap inference providers do not sign BAAs. As of July 2026,
  OpenAI, Anthropic, Google (via Vertex), and Mistral (enterprise) offer
  BAA-capable tiers; Groq, Cerebras, DeepSeek, and Zhipu do not.
- **Security Rule update pending.** The December 2024 NPRM (which would make
  MFA and encryption explicitly mandatory) remains unfinalized as of July
  2026. SAFi's posture assumes it lands.

## 2. What SAFi provides today

Everything in this section is shipped and running, not planned.

- **Provider allow-list (the keystone).** Each organization restricts which
  LLM providers may receive its content. Enforcement is fail-closed at every
  model dispatch point in the pipeline — including background and evaluation
  calls — a disallowed provider is rejected, never silently substituted.
  Providers carry verified **BAA-capable** and **zero-data-retention**
  badges so a healthcare org can compose an allow-list matching its BAA
  chain. Every allow-list change is evidence-logged, and every turn records
  which provider/model actually touched the content.
- **Encryption at rest and in transit.** Message content, titles, follow-up
  suggestions, memory, OAuth tokens, and the full per-turn governance
  record are encrypted at the application layer (key rotation supported);
  transport is TLS. This meets the *proposed* Security Rule's explicit
  encryption mandate, not just the current addressable standard.
- **Access controls.** Role-based access control with a dedicated auditor
  role; server-side revocable sessions with org-configurable idle and
  absolute timeouts; **TOTP multi-factor authentication** for local
  accounts, per-tenant SSO enforcement (Entra tenant / Workspace domain
  pinning) with MFA evidence checks at sign-in, and an org-level
  require-MFA setting; an append-only authentication event journal.
- **Delegated access to source systems (§164.308(a)(3)-(a)(4)).** External
  systems are reached with per-member credentials, never an org-wide service
  principal. Each member authorizes their own account once, and every tool call
  their agents make runs as them: it inherits their existing permissions in the
  source system, appears under their name in that system's audit log, and stops
  working when they are offboarded, because offboarding revokes every stored
  authorization. SAFi never holds a credential that can read more than the
  member who granted it.
- **Minimum necessary (§164.502(b)).** Tool integrations request the narrowest
  authorization that does the job, and the narrowing is enforced by the identity
  provider rather than by SAFi's own restraint. The Microsoft 365 integration
  holds `Mail.ReadBasic`, not `Mail.Read`, so message bodies are withheld at the
  consent screen and never reach a model; it returns sender, subject and date.
  Calendar returns titles and times, never attendee lists. Every integration is
  read-only: nothing sends, moves, uploads or deletes.
- **Sensitive-identifier blocking.** Deterministic checks for payment card
  numbers, IBANs, bank routing numbers and formatted US social security numbers,
  three of the four confirmed by checksum. A message containing one is refused
  before a model is called; a response containing one is refused before it is
  sent; and the value is redacted from the governance record. Off by default,
  enabled per identifier. See [Sensitive Data Controls](SENSITIVE_DATA_CONTROLS.md).
- **Audit controls (§164.312(b)).** The hash-chained, tamper-evident audit
  trail exceeds the requirement: every create/modify/delete on a record is
  journaled with actor and timestamp, and integrity is verifiable per
  message. Tool calls enter the same chain, recording the tool, the decision,
  the reason and capped parameters, written from a single code path so the
  chain and the Audit Hub cannot disagree. A blocked call is recorded as
  blocked, so a refusal is evidence rather than an absence.
- **Integrity of the governing code (§164.312(c)(1)).** The faculties that make
  every governance decision are covered by a manifest. `verify_integrity`
  recomputes a root hash over that set and reports INTACT or names the files
  that changed; each release publishes the expected fingerprint, and every
  governance record carries it. This is code integrity, distinct from the
  per-record integrity above.
- **Verified backups.** A weekly job restores the most recent backup and
  re-verifies the hash chains inside the restored copy, reporting the table and
  chain counts it checked. Backup integrity is demonstrated rather than
  assumed.
- **Breach notification clocks (§164.404–.410).** The incident registry
  computes HIPAA's deadlines from firm awareness: 60 days to individuals;
  ≥500-record breaches add media and contemporaneous HHS notice; <500 go to
  the annual log (due 60 days after year end); business-associate role
  switches to the single BA→CE 60-day clock. Incidents are append-only with
  examiner-ready, custody-logged export.
- **Right of access (§164.524).** Any user can self-service download
  everything the platform stores about them, decrypted and strictly
  self-scoped; every export is custody-logged. This also serves GDPR
  Art. 15 for EU deployments.
- **Retention and legal hold.** Per-org retention configuration (HIPAA's
  six-year documentation horizon fits the standard options), legal hold
  that suspends all destruction, an evidence-logged purge engine, and the
  written erasure position (`docs/DATA_ERASURE_AND_RETENTION.md`). A hold
  stops destruction everywhere, not only in the scheduled purge: every phase
  re-checks it between batches, member-initiated deletion is refused while a
  hold is active, and an unreadable hold state prevents destruction rather
  than permitting it.
- **Device-copy control.** A per-org offline/PWA kill switch (default OFF
  for organizations) keeps member devices from retaining local copies of
  conversations — no offline cache, no queued messages — with client-side
  purge on sign-in.

## 3. Pending / roadmap

- **Voice synthesis residual.** The default TTS engine (edge-tts) sits
  outside the provider-governance registry. Healthcare deployments should
  disable TTS or route it to a governed provider (OpenAI/Gemini TTS are
  enforced through the allow-list); cached audio is TTL-bounded either way.
- **Security Rule NPRM watch.** If the update finalizes as proposed, SAFi's
  MFA and encryption posture already matches it; this line item is
  tracking, not build work.

## 4. Deployer notes

- Configure the provider allow-list to BAA-capable providers **before**
  any PHI flows; the default (unrestricted) is not a HIPAA posture.
- Set the org's retention to at least six years for HIPAA-required
  documentation, enable require-MFA, and leave the offline kill switch off.
- Self-hosted deployments own the physical/infrastructure safeguards
  (§164.310) — server access, backups, and disposal are outside the
  application's boundary.
