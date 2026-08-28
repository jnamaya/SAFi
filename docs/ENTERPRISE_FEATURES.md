# SAFi Enterprise Features

**Last updated:** August 2026. Verified against the code on 2026-08-28.

The per-regime readiness documents (`SEC_COMPLIANCE_READINESS.md`,
`HIPAA_READINESS.md`, `EU_AI_ACT_READINESS.md`, `ISO_42001_READINESS.md`,
`DATA_ERASURE_AND_RETENTION.md`) each answer "how does SAFi map onto this
regulation". This page answers the other question: what does an organization
actually get. Every capability below is shipped and cited to the file that
implements it. What is not built has its own section at the end.

Nothing here is a compliance certification. These are platform controls
intended to support a compliance program, not to replace one.

---

## Identity and access

| Capability | What it does | Where it lives |
| :--- | :--- | :--- |
| **OIDC single sign-on** | Google Workspace and Microsoft Entra, with per-org domain and tenant pinning enforced at the claim gate on every login. | `api/auth.py:171`, `:222` |
| **SCIM 2.0 provisioning** | An IdP (Okta, Entra) pushes Users and Groups over a per-org bearer token. Deprovisioning revokes MCP tool tokens, drops OAuth tokens, removes membership, and strips sharing. | `api/scim.py` |
| **Group to role mapping** | IdP group membership resolves to a SAFi role through an admin-configured map. | `api/organizations.py:480` |
| **Domain verification** | An organization claims its email domain, which then outranks invitations from any other org. | `api/organizations.py:63`, `:116` |
| **TOTP multi-factor** | Rate-limited TOTP enrollment and verification, with an org-level require-MFA setting. | `api/auth.py:46`, `:1283`, `database.py:6459` |
| **Session control** | Users list and revoke their own sessions. Admins list and revoke any member's. | `api/auth.py:1242`, `api/organizations.py:816` |
| **Four-role RBAC** | `admin` > `editor` > `auditor` > `member`, scoped to the organization, enforced at 60+ points. | `core/rbac.py` |
| **Groups and per-agent grants** | Named member sets and per-agent access grants that widen the role ladder and can never narrow it. | `persistence/sharing_store.py`, `api/groups_api.py` |

**One deliberate exception to the hierarchy.** Supervisory review is restricted
to `admin` and `auditor`, so `editor` is excluded despite outranking `auditor`.
Editors author the agents and policies, and FINRA 3110/3120 supervision means
the author does not sign off on their own work.

## Compliance and records

| Capability | What it does | Where it lives |
| :--- | :--- | :--- |
| **Hash-chained audit trail** | Each entry hashes its payload plus the previous entry's hash. Editing or removing any past record breaks every record after it. | `database.py:2033-2099` |
| **Audit Hub** | KPIs, alignment and consistency trends, filters, a log explorer, per-turn drill-down, and export carrying integrity evidence. | `api/audit_api.py` |
| **Supervisory review** | A sampling queue with dispositions, configurable rates, reports, per-item export, and alerts. | `api/review_api.py` |
| **Incident register** | Incidents with configurable notification regimes, an event timeline, and per-incident export for regulator notification clocks. | `api/incidents_api.py` |
| **Retention and legal hold** | Per-org retention periods with a legal hold that blocks deletion while active, and fails closed when hold state is unreadable. | `database.py:2673`, `:4768-4853` |
| **Examiner production export** | Date-ranged, decrypted message records with trail metadata as integrity evidence, capped by volume, and itself logged. | `api/records_api.py:238` |
| **Compliance log** | An append-only evidence record of every admin configuration change, written in the same transaction as the change. | `api/records_api.py:225` |
| **Subject access and deletion** | Self-service data export and account deletion, for GDPR Art. 15 and HIPAA §164.524. | `api/records_api.py:43`, `api/auth.py:1224` |

## Data and provider controls

| Capability | What it does | Where it lives |
| :--- | :--- | :--- |
| **Provider allow-list** | Each org restricts which LLM providers may receive its content. Enforcement is fail-closed at every dispatch point: a disallowed provider raises, and there is never a silent fallback. Providers carry BAA-capable and zero-data-retention metadata. | `core/services/provider_governance.py` |
| **Bring your own keys** | Per-org provider API keys, Fernet-encrypted, layered over the deployment defaults so billing separates cleanly. | `core/services/org_keys.py` |
| **Encryption at rest** | Application-layer Fernet encryption on sensitive columns, with MultiFernet key rotation and a dual-read contract for rows written before it was enabled. | `persistence/crypto.py` |
| **Sensitive data controls** | Deterministic detection of payment cards (Luhn), IBAN (mod-97), ABA routing numbers, and formatted US SSNs. Off by default. What the org enables is a floor a policy can raise but not lower. | `core/pii_validators.py` |
| **Offline kill switch** | Disabling offline mode makes member devices purge locally cached org content on their next bootstrap. | `api/records_api.py:110` |
| **Usage and cost** | Per-org and per-agent token accounting, deliberately kept out of the governance record. | `core/services/usage_tracking.py` |

## Governance runtime

- **Charter plus policy, two tiers.** An org-wide charter and a business-unit
  policy compile into one weighted value set per agent, charter share
  defaulting to 40%. Policies are versioned, and the version in force is
  stamped on every record.
- **Governed tool calls.** Installing an MCP server grants nothing. A policy
  enables specific tools, an agent is assigned what its policy allows, and the
  Will checks every individual call before it runs. Tools acting as a person
  require that person to sign in once. See `api/mcp_api.py`,
  `core/services/mcp_oauth.py`, `core/services/connector_governance.py`.
- **The `/evaluate` gateway.** Govern the output of an agent you have already
  built, leaving your orchestration, prompts, and tool layer where they are.
  See `api/evaluate_api.py`.
- **Deployment integrity attestation.** The trusted computing base is hashed
  against the release manifest at boot and the fingerprint is stamped into
  every governance record. `SAFI_ENFORCE_INTEGRITY=strict` refuses to start on
  anything but a verified-intact tree. See `core/integrity.py`.
- **Supply chain.** Every release image carries SLSA provenance, an SBOM, and a
  keyless cosign signature, so a deployment can prove which source built it.

## Deployment

Self-hosted by design, with Docker or bare metal (`DEPLOY_BAREMETAL.md`).
Production installs should run a tagged release and pin its published TCB
fingerprint, because a release is the only tier whose exact code is verifiable.
Organizations that want operational help without a new vendor data boundary can
use the managed operator arrangement, which runs a dedicated instance inside
the customer's own environment (`MANAGED_OPERATOR.md`).

## What does not ship

Stated plainly, because a buyer finding these out later is worse than reading
them here.

- **SAML SSO is not built.** It is scoped in `SAML_SSO_PLAN.md` and offered on
  enterprise demand. The shipped path is OIDC with per-tenant enforcement.
- **SCIM omits bulk operations, complex PATCH filter paths, and ETag
  concurrency.** This is deliberate and documented in the module.
- **The default text-to-speech engine sits outside provider governance.**
  Healthcare deployments should disable it or route to OpenAI or Gemini TTS,
  which the allow-list does cover.
- **Sensitive data detection covers four identifier types only**, does not
  match unformatted SSNs, and offers no custom pattern field. The value also
  existed in the stored message row before the check ran.
- **Permissions are role-scoped, not resource-scoped.** Per-resource scoping
  and separation of duties for policy authors are not implemented.
- **Self-hosted deployments own their infrastructure safeguards.** Server
  access, backups, and disposal sit outside the application boundary.

## Where to go next

- [Developer Guide](DEVELOPER_GUIDE.md) for architecture, policy authoring, and
  integration surfaces.
- [Governance Artifact Specification](GOVERNANCE_ARTIFACT_SPECIFICATION.md) for
  the field-by-field contract behind every record, if you are building a
  dashboard, examiner tool, or SIEM feed.
- [Knowledge Bases & Tools](KNOWLEDGE_AND_TOOLS.md) and
  [MCP Tools](MCP_TOOLS.md) for the tool lifecycle and operator steps.
- The readiness series for regime-by-regime mapping: [SEC / FINRA](SEC_COMPLIANCE_READINESS.md),
  [HIPAA](HIPAA_READINESS.md), [EU AI Act](EU_AI_ACT_READINESS.md),
  [ISO/IEC 42001](ISO_42001_READINESS.md),
  [Data Erasure & Retention](DATA_ERASURE_AND_RETENTION.md).
