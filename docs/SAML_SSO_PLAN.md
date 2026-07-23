# SAML SSO — Implementation Plan

Scoped 2026-07-23. Referenced from `SEC_COMPLIANCE_READINESS.md` §3
("SAML SSO and SCIM provisioning — available on enterprise demand").
Not started. This is an engineering checklist, not a readiness claim —
don't treat anything below as shipped until it's checked off and tested.

## Why this is a real subsystem, not a quick add

The existing OIDC SSO (Google Workspace domain pinning, Microsoft Entra
tenant pinning) already provides the *login-completion* plumbing SAML
would reuse. But SAML's *front half* — metadata exchange, per-org IdP
registration, signed-assertion validation — has no OIDC equivalent to
build on, and is where the real security surface lives (XML signature
wrapping is a well-documented, historically exploited SAML vuln class).
**Use a battle-tested library (`python3-saml`) for all signature/assertion
validation — do not hand-roll XML signature checking.**

## Reusable as-is

- [ ] Wire SAML into `_establish_session()` (`safi_app/api/auth.py:83-107`)
      — the shared session-creation/journaling terminus already used by
      Google, Microsoft, local, and demo login.
- [ ] Add an `idp='saml'` branch to `_org_claim_gate()` (135-169) and
      `_sso_evidence()` (115-132), alongside the existing Google/Microsoft
      branches, for per-org enforcement + audit context.
- [ ] Extend the existing `organizations.settings.identity` JSON config
      (`get_org_identity_config`/`set_org_identity_config`,
      `database.py:4594-4711`) with SAML IdP fields — entity ID, SSO URL,
      x509 cert. Note: JSON storage means no uniqueness constraint or
      index for "look up org by IdP entity ID," needed for SP-initiated
      flow routing — promote to real columns/a dedicated table if that
      lookup turns out to be load-bearing.
- [ ] Add SAML's `AuthnContextClassRef` as the MFA-evidence signal in the
      `require_mfa` gate (153-160), the same role OIDC's `amr` plays today
      (mirror `_MFA_AMR_METHODS`, line 112, with known MFA context-class
      URIs).

## New pieces — no existing equivalent

- [ ] SP metadata endpoint (publishes SAFi's SP entity ID, ACS URL,
      signing cert for IdPs to consume).
- [ ] Per-org IdP registration (entity ID, SSO URL, signing cert) — admin
      UI + storage, see above.
- [ ] ACS endpoint (`POST /callback/saml` or per-org variant) that:
  - [ ] Validates the XML signature via `python3-saml` (wraps `xmlsec1`;
        `lxml` is already a dependency).
  - [ ] Checks replay, audience, `NotBefore`/`NotOnOrAfter`.
  - [ ] Correlates `InResponseTo` back to the original `AuthnRequest`.
- [ ] Attribute-to-user mapping (email/name/groups), analogous to the
      `user_info` dict construction at `auth.py:660-666` and `388-394`.

## Testing

- [ ] `tests/test_saml_claims.py`, mirroring `tests/test_oidc_claims.py`
      (`TestOrgClaimConfig` for settings round-trip, `TestClaimGate` for
      direct unit tests of `_org_claim_gate`/`_sso_evidence` against
      synthetic SAML attribute dicts).
- [ ] Negative tests: unsigned assertion, expired assertion, wrong
      audience, replayed assertion, IdP entity ID mismatch — this is the
      area most worth adversarial testing given the vuln history.

## Out of scope for this plan

SCIM provisioning is bundled with SAML in the readiness doc's roadmap
line but is a separate protocol/effort (user/group lifecycle sync, not
authentication) — scope it separately when it's prioritized.
