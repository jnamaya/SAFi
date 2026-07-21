# Data Erasure and Retention — SAFi's Written Position

*Last updated: July 21, 2026. Companion to the readiness series
(`SEC_COMPLIANCE_READINESS.md`, `EU_AI_ACT_READINESS.md`, `HIPAA_READINESS.md`).
Vocabulary note: this document describes data lifecycle mechanics; it makes
no claims about AI capability or compliance outcomes.*

SAFi serves two obligations that can point in opposite directions: data
subjects' rights to access and erasure (GDPR Arts. 15 and 17; HIPAA
§164.524), and record-keeping duties that **require** retention (SEA Rule
17a-4, Advisers Act Rule 204-2, FINRA supervision rules, HIPAA's six-year
documentation rule). This is the position of record on how the platform
reconciles them.

## 1. Access comes first, and is unconditional

Any authenticated user may download everything the platform stores about
them — account data, conversations with their per-turn governance results,
projects, saved items, and memory — via the self-service export
(`GET /api/me/export`, or **My Profile → My Data**). Access requests never
conflict with retention, so no carve-out applies. Every export is recorded
in the compliance evidence log.

## 2. Erasure by default, for unregulated data

Users can delete their conversations at any time. For personal
(no-organization) users, deletion removes the live records immediately: the
conversation, its messages, and the associated encrypted governance records
are destroyed together.

Two nuances are stated plainly rather than hidden:

1. SAFi's audit trail is append-only and tamper-evident, and a deletion is
   itself an auditable event. Deleting a conversation journals a snapshot of
   the deleted rows into the audit trail before the live data is destroyed.
   Those journal entries are not served by any product surface; they persist
   only until the retention sweep reclaims orphaned trail chains, at which
   point the content is gone entirely. All stored copies — live and
   journaled — are encrypted at rest throughout.
2. For **organization-governed** conversations, the member's deletion
   removes the conversation from their own account, but the organization's
   per-turn governance record survives: it is the firm's supervisory
   evidence (the same Art. 17(3)(b) legal-obligation ground as §3, and the
   supervision surface would otherwise be erasable by the person under
   supervision). Those records remain visible to the organization's
   admins and auditors in the Audit Hub, marked as belonging to a deleted
   conversation, and are destroyed by the organization's retention policy —
   never earlier, never selectively.

## 3. The legal-obligation carve-out (GDPR Art. 17(3)(b))

For organizations subject to record-keeping law, erasure on demand would
itself be a violation — a broker-dealer that deleted client communications
inside the 17a-4 window would be destroying required books and records.
GDPR anticipates exactly this: **Art. 17(3)(b)** disapplies the right to
erasure where processing is necessary "for compliance with a legal
obligation."

SAFi's implementation of that carve-out is the org retention engine:

- Each organization configures a retention period matching its regulatory
  regime (or keep-forever). Records inside the window are not erasable by
  anyone — including admins and the platform operator.
- When the window expires, the daily purge destroys the records
  automatically — conversations, messages, governance records, and their
  orphaned audit-trail chains — with blast-radius safety rails, and logs
  the destruction to the append-only evidence log. **Scheduled destruction
  at retention expiry is the erasure path for regulated data.**
- An erasure request against in-retention records is therefore answered:
  acknowledged, recorded, and fulfilled by the retention clock rather than
  on demand. The requester can be told the exact date their data dies.

## 4. Legal hold takes precedence over everything

An active legal hold suspends **all** destruction — retention purges,
user-initiated deletion sweeps, and log-file expiry — for the organization,
until the hold is lifted. Placing and lifting a hold requires a written
reason and is evidence-logged. This ordering (hold > retention > erasure) is
deliberate: spoliation exposure outranks storage hygiene, and a data
subject's erasure interest is preserved, not extinguished — it resumes the
moment the hold clears.

## 5. Who answers a data-subject request

For organizational deployments, the organization is the data controller and
SAFi is tooling: the org's admin fulfills access requests (the user can
self-serve regardless) and applies its retention policy. For personal
(no-organization) users, no retention law attaches; deletion is immediate as
described in §2, and the self-service export covers access.

## Summary table

| Request | Unregulated / personal data | Data under a retention obligation |
|---|---|---|
| Access (Art. 15 / §164.524) | Self-service export, immediate | Self-service export, immediate |
| Erasure (Art. 17) | Immediate cascade deletion | Art. 17(3)(b) carve-out: destroyed automatically at retention expiry; date is knowable |
| Either, under legal hold | Hold suspends destruction until lifted | Hold suspends destruction until lifted |
