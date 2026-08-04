---
title: SAFi README: Roles & Permissions
slug: readme-roles-permissions
tags: ["safi", "readme", "safi"]
summary: SAFi has **four roles**, scoped to an organization. Institutions author governed
agents; the people who use them do so under least privilege.
version: 1.0
---

# SAFi README: Roles & Permissions

SAFi has **four roles**, scoped to an organization. Institutions author governed
agents; the people who use them do so under least privilege.

| | `member` | `auditor` | `editor` | `admin` |
|---|---|---|---|---|
| Chat with the org's agents | ✅ | ✅ | ✅ | ✅ |
| Own conversations, projects, saved content | ✅ | ✅ | ✅ | ✅ |
| Own account, sessions, MFA, data export | ✅ | ✅ | ✅ | ✅ |
| See the governance verdict on **their own** turns | ✅ | ✅ | ✅ | ✅ |
| See which agents exist, and each one's **governing values and standards** | ✅ | ✅ | ✅ | ✅ |
| See which Charter and Policy govern the agent they are using | ✅ | ✅ | ✅ | ✅ |
| **Audit Hub** — KPIs, trends, log explorer, export | — | ✅ | ✅ | ✅ |
| **Supervisory review** — queue, dispositions, reports | — | ✅ | **—** | ✅ |
| **Author agents** — create, edit, delete, assign tools | — | — | ✅ | ✅ |
| **Author policies** — create, edit, version, API keys | — | — | ✅ | ✅ |
| Org settings, members, invitations, role changes | — | — | — | ✅ |
| Retention, legal hold, provider allowlist, offline policy | — | — | — | ✅ |
| Incident register, examiner export, compliance log | — | — | — | ✅ |

Roles are ranked (`admin` 4 > `editor` 3 > `auditor` 2 > `member` 1) and a check
passes at the required rank **or above** — with **one deliberate exception**.

## The exception: editors cannot review

`editor` outranks `auditor`, but supervisory review is restricted to
`("admin", "auditor")` — **editors are excluded**. Editors are the people who
author agents and policies, and FINRA 3110/3120 supervision means someone other
than the author signs off. An editor reviewing turns produced by an agent they
wrote is self-supervision, which is the first thing an examiner tests.

So the model is a hierarchy for *reading* and *authoring*, and a deliberate
non-hierarchy for *supervising*.

## What each role means in practice

**`member`** — consumes agents. Full use of chat, their own conversation
history, projects, saved content, and document upload.

Members are not governed in the dark. Without any elevated role they can see:

- **which rules apply to them** — the agent list, and for any agent its
  compiled Values & Standards. Under the two-tier model those are assembled
  from the organization's Charter and the governing Policy, weighted (Charter
  share defaults to 40%), so what a member sees is the operative standard their
  turns are actually scored against — not a summary of it.
- **who constrains the agent they are using** — rendered as
  `Governed by <Org> Charter → <Policy>`, plus the agent's scope statement and
  the fact that out-of-scope requests are redirected.
- **how their own turn was judged** — the alignment score, every value that was
  upheld or conflicted, each with a confidence and a written reason, and whether
  the answer was approved or redirected.

What a member cannot reach: other people's conversations, the Audit Hub, the
review queue, and any authoring or configuration surface.

**`auditor`** — oversight without authorship. Everything a member has, plus the
full Audit Hub across the org (alignment and consistency analytics, per-turn
drill-down with hash-chain verification, custody-logged exports) and the
supervisory review workflow: the sampled queue, per-item evidence, approve and
override with a written rationale, coverage reports, and both exports. Cannot
create or change agents, policies or org settings — by design, so oversight
stays independent of authorship.

**`editor`** — builds governed agents. Everything a member has, plus the Audit
Hub, plus authorship: create and edit agents (including which tools they may
call), create and edit policies, restore policy versions, and mint or rotate
policy API keys for external integrations. **Cannot perform supervisory
review.** Cannot change org settings or compliance configuration.

**`admin`** — accountable for the organization. Everything above, including
review, plus org identity and domain verification, invitations, membership and
role changes, forced session revocation, review configuration, retention and
legal hold, the provider allowlist, the offline/device-caching policy, the
incident register, the compliance evidence log, and examiner production exports.

## How an organization gets its first admin

Onboarding is self-service, and the role a person lands on depends on whether
their organization already exists:

1. **First person in** — a user who signs in with no organization gets one
   created for them automatically, seeded with a complete default policy, and is
   promoted to **`admin`** of it. They are its owner.
2. **Verify the domain** — that admin verifies ownership of their email domain.
   Verification is `admin`-only, so it can only ever be performed by someone who
   already administers the organization.
3. **Everyone after that** — a user signing in with an email on a **verified**
   domain is matched to that organization and joined as a **`member`**, never an
   admin. Whether that happens at all is controlled by the org's `join_policy`:

   | `join_policy` | effect |
   |---|---|
   | `invite_only` | no automatic joining; the login is refused and journaled |
   | `domain_auto_join` | same-domain users join as `member` |
   | `both` | invitations and domain joining |

   Promotion beyond `member` is a deliberate act by an existing admin.

Ownership is also self-healing: if the recorded owner of an organization is
somehow not an admin of it, the next `/api/me` promotes them back and logs it —
so an organization cannot end up with no one able to administer it.

## Guarantees that hold across all roles

- **Organization scoping.** Every org-scoped route rejects a mismatch between
  the path's organization and the caller's own with `403`, and the scoping is
  applied again in SQL. An admin of one organization has no reach into another.
- **Role changes take effect immediately.** Changing a member's role revokes
  their sessions and journals the change in the same transaction, so a
  downgrade cannot be outlived by an open tab.
- **MFA can be mandated org-wide**, not left to individual choice.
- **Supervisory separation of duties.** A reviewer cannot dispose of a turn from
  their own conversation, enforced in the data layer so every caller inherits
  it — not only the API.
- **Dispositions are tamper-evident.** Each approval or override is appended to
  the message's hash-chained audit trail, so a sign-off carries the same
  integrity evidence as the record it supervises.

## Current limitations

Stated plainly, because knowing the edges matters more than the summary:

- **Four fixed roles, no delegation.** There is no per-agent or per-policy
  scoping, so "this team administers only these agents" cannot be expressed. An
  editor can edit every agent in the organization.
- **No approval workflow for capability changes.** An editor granting an agent a
  new tool takes effect immediately; there is no request-and-approve step.
- **Agent and policy changes are not yet written to the compliance evidence
  log.** That log currently records organization-level changes (retention, legal
  hold, provider allowlist, offline policy, review configuration) and every
  export. The hash-chained trail covers *turn* decisions, not permission or
  capability changes.
- **Policy-authorship separation of duties is incomplete.** A reviewer cannot
  dispose of a turn from their own conversation, but an admin may author a policy
  and then review turns governed by it.
- **No SCIM or automated deprovisioning.** Off-boarding is manual today;
  `remove_member_from_org` revokes sessions correctly, but nothing is driven from
  an identity provider. See [`docs/SAML_SSO_PLAN.md`](docs/SAML_SSO_PLAN.md).

Enforcement lives in [`safi_app/core/rbac.py`](safi_app/core/rbac.py) (roles and
`check_permission`), with per-surface role sets in `audit_api.py`
(`OBSERVER_ROLES`) and `review_api.py` (`REVIEWER_ROLES`).

---
