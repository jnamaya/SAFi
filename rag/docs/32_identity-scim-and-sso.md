---
title: SAFi Identity: SSO and SCIM Directory Sync
slug: identity-scim-and-sso
tags: ["safi", "identity", "scim", "sso", "provisioning", "okta", "entra", "safi"]
summary: SAFi authenticates people through the organization's identity provider and can accept SCIM 2.0 provisioning, so joiners, leavers and role changes flow from the directory instead of being managed by hand.
version: 1.0
---

# SAFi Identity: SSO and SCIM Directory Sync

SAFi authenticates people through the organization's own identity provider rather
than holding a separate password. Google and Microsoft sign-in are supported, and
an organization can require that its members arrive through its own tenant.

Availability: SCIM landed after the v1.4.1 release. Check the release notes of
the version you install.

## How membership is decided at login

When someone signs in, SAFi resolves which organization they belong to:

- **A live invitation wins**, except against the organization that has verified
  the email's domain. A verified domain is authoritative over its own people, so
  an invitation from a different organization cannot place someone into the wrong
  tenant.
- **Otherwise, domain auto-join**, subject to the organization's join policy. An
  organization set to invite-only does not absorb people by domain; they
  authenticate but stay unaffiliated until invited.

Invitations may be sent to any address, which is deliberate so that contractors
can be brought in. An invitation outside the organization's own verified domain
is flagged as external in the evidence record.

## SCIM 2.0 provisioning

For organizations that manage identity centrally, SAFi exposes SCIM 2.0 endpoints
at `/scim/v2`. The identity provider (Okta, Microsoft Entra, and others)
authenticates with a per-organization bearer token and pushes Users and Groups.
SCIM requires HTTPS.

What the directory can drive:

- **Provisioning an existing SAFi user** adds them to the organization and sets
  their role.
- **Provisioning someone who has never signed in** creates a long-lived
  invitation, which the normal SSO login path accepts by email. No separate
  activation step is needed.
- **Deprovisioning** (setting a user inactive, or deleting them) performs the same
  off-boarding as a manual member removal: MCP tool tokens are revoked, OAuth
  tokens dropped, membership removed, sharing stripped, any pending invitation
  revoked, and evidence logged.
- **Group membership maps to a SAFi role** through a group-to-role map the
  administrator configures.

The SCIM layer translates directory operations into the same membership and
invitation functions the rest of SAFi uses, so the governance-bearing logic stays
in one place rather than being duplicated for the directory path.

Deliberately not implemented yet: bulk operations, complex PATCH filter paths,
and ETag concurrency.

## Why this matters for governance

Off-boarding is the case that tends to fail quietly in AI deployments: an account
keeps working after someone leaves, and their access to agents and tools with it.
Driving membership from the directory means a leaver's SAFi access ends when
their directory account does, and the removal is recorded as evidence rather than
being an undocumented manual step.
