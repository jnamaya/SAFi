# SAFi v1.5.0 — Release Notes

**Status:** draft — pending tag cut and registry publication
**Date:** 2026-09-30
**Branch at time of writing:** `dev` (344 commits since `v1.4.1`)

**TCB Fingerprint:** `d06087618d265bcc5d2b2cf65603586e9082eeb21def88e636880ea2ac4d62a7`
*(must be recomputed from the tagged tree at release time — see "Before you cut the tag")*

---

## Scope

This is a **MINOR** release: features and reviewed Core Loop changes, so it
carries a new TCB Fingerprint and the upgrade steps below are required. It is
also the first release to fall under the current versioning convention — every
release from here on is three-part (`vMAJOR.MINOR.PATCH`); the two-part series
ended at v1.4.

This release covers the hosted/server product. **Appliance and ISO work is
deliberately excluded** — the local-inference path has not been tested to a
standard we are willing to ship. See "Not in this release" below.

v1.4.1 was a single-commit patch over v1.4 (`guests: never hand a guest a model
this install cannot serve`). Everything below is new relative to it.

---

## Upgrade notice — the fingerprint changed

The Core Loop moved, so this release ships a **new TCB Fingerprint**:

```
v1.4.1   e44db51e48852cd1...
v1.5.0    d06087618d265bcc5d2b2cf65603586e9082eeb21def88e636880ea2ac4d62a7
```

**Operators must update `SAFI_EXPECTED_FINGERPRINT`** to the value above. Any
deployment left pinned to the v1.4.1 value will log a loud mismatch on boot and,
with `SAFI_ENFORCE_INTEGRITY=strict`, refuse to start. That is the check working
as designed — it is not a defect.

The cause is the Jev integration and Core Loop comment pruning. Ordinary
application code (model catalogue, routing, UI) sits *outside* the Core Loop and
did not move the fingerprint on its own.

Per `docs/RELEASE_PROCESS.md`, "Verify this Install" reports one of five
verdicts. Until v1.5.0's fingerprint is appended to the signed registry, this
build correctly reports **`unreleased`** — intact, but not in the list.

### Other upgrade steps

- **MySQL 8.0 → 8.4 LTS.** Backup and restore paths were exercised against 8.4.
- **SCIM requires HTTPS.** The `/scim/v2` endpoint now rejects plaintext.
  Terminate TLS upstream and pass `X-Forwarded-Proto` (see
  `docs/DEPLOY_BAREMETAL.md`).
- **Python 3.11–3.13** supported, tested rather than assumed.

---

## New features

### MCP and tool servers
- OAuth 2.1 per user; tool servers can be installed from an operator **CLI**
  (`--orgs` to scope a shared host, `--cwd`, pinned hostname).
- A **tool registry** with per-service brand marks, and status reporting that
  states what is actually wrong rather than asserting health.
- Google Workspace, GitHub, and mail/calendar tools via the graph gateway. The
  internal `github` and `google_drive` built-ins retire in favour of MCP's own
  servers.
- MCP servers install from the shell, not the browser.
- Fixed a boot deadlock, and raised the tool-call timeout so a slow server no
  longer needs a code edit.
- **Scheduled turns now have tools** — the scheduler boots the MCP runtime.

### Identity and access
- **SCIM 2.0** directory sync: provisioning, deprovisioning, group-to-role.
- **MFA**: TOTP enrolment with QR codes (scannable by Google/Microsoft
  Authenticator); `amr` accepted as an Entra optional claim.
- **Invitations** delivered by SMTP for members who do not use Google or
  Microsoft; a claim-link race is fixed.
- **Single-tenant deployments** via `SAFI_SINGLE_TENANT_ORG_ID`; guest login is
  refused on them.
- Continuous domain-ownership enforcement. A verified domain claims its
  accounts and outranks any outstanding invitation; shadow orgs are gone.

### Governance surface
- An **attention inbox**: one role-aware surface for everything waiting on a
  human — requests, tool grants, and incidents.
- **Approval policies**: IT writes, legal activates. Widening an agent's tool
  list requires a second person (separation-of-duties kernel, now inside the
  Core Loop manifest).
- Policies and tool grants can be approved directly from the inbox.
- Requesters see their own submission, not just the outcome. Self-approvals are
  no longer surfaced as news.

### Sensitive data
- **Deterministic blocking of sensitive identifiers**, off by default.
- The enforcement floor follows **the person typing**, not the agent.
- **Legal hold** suspends all destruction.
- A PII refusal now names the real reason.

### Sharing
- Org members can share **conversations and folders**.
- Groups and per-agent grants, and use is now **enforced** rather than advisory.
- "Shared with me" collapses to a single row at the top.

### Models, providers and usage
- **GPT-6** (`gpt-6-luna`) routed through the gpt-5 parameter contract, which is
  what makes it dispatch correctly at all.
- **Catalogue refreshed**: `gemini-3.8-flash` and `qwen-3.8-27b` join;
  `gemini-3.6` retired. Model labels are now **versionless** so a model upgrade
  does not churn saved UI state — the id is the version signal.
- **Qwen routing fixed.** `qwen-*` previously fell through to the Groq default
  and was published with a false HIPAA/ZDR badge, because Groq *is* a valid
  provider and the existing test still passed. Pinned by a regression test
  across three future Qwen ids.
- Org-supplied **provider keys** layered over `.env`; deployment-wide keys can
  be stored in the database and managed by an operator.
- Provider calls are **bounded**, so one stalled provider cannot take down the
  host. Model refusals are reported as refusals, not as empty responses.
- **Per-org token tracking**, a deployment-wide spend rollup, and
  operator-added models.

### Jev
- **Typed Conscience audits** integrated via Jev, with an explicit user/agent
  Conscience choice always taking precedence over the automatic selection.
- Spirit reports an undefined drift as *undefined* rather than `0.00`.

### Backup and restore
- **New `safi restore [file]` CLI** — restores a backup into the live database.
- The safety snapshot is gzipped and the journal status column widened.
- Three verification bugs fixed: `gunzip`'s SIGPIPE masking the real restore
  error; verify failing when a table gained its first rows after the dump; and
  small-but-real dumps being distrusted on empty fresh schemas. Restore-verify
  now works with the minimal database account.

### Certificates
- The ACME challenge is served **from disk** instead of through the
  redirect/proxy chain; certbot uses `--webroot`; key permissions fixed so
  Apache can actually serve the resulting TLS.

### Exports
- A governed answer exports as **DOCX, PDF, xlsx, or Markdown**.

### Scheduler
- Governed agent digests replace the `/opt` timers. Editable in the UI, branded
  HTML email, markdown rendering, and a daily guard that re-arms on edit.

### TCB and verification
- **"Verify this Install"** button in Org settings reads the signed registry and
  reports one of five verdicts (`authentic`, `unreleased`, `modified`,
  `unverifiable`, `offline`).
- The registry is now **minisign-signed**; the public key is pinned in-repo and
  compared byte-for-byte.
- The last verdict is persisted to the compliance log, and the verifier reports
  which git branch an instance is on.
- An optional **fingerprint pin** in the setup wizard.
- Core Loop grew from 17 to **19 files** — the sharing resolver and the
  tool-approval SoD kernel joined it.

### Clients
- **PWA replaces Capacitor** as the official mobile client.
- OpenCode integration gateway.

---

## Security fixes

- **Cross-org IDOR** closed in the policy API and `GET /agents/<key>`.
- **Stored XSS** via model labels in the composer picker — labels are now
  escaped.
- Model catalogue scoped per org; a verified domain has a single owner.
- Guest login refused on single-tenant deployments.
- SCIM refuses plaintext HTTP.

---

## Not in this release

**Appliance and ISO work is excluded.** It has not been tested to a standard we
are willing to ship, and no part of it should be relied on:

- Bundled local Qwen3 model, llama runtime libraries, and serving/selecting/
  installing a local model from the UI
- Laya answering typed audits locally
- Local-inference and TLS work on the appliance
- ISO work: the Debian 13 (trixie) re-base, squashfs xz in place of zstd, the
  slimmed image, and the unattended netinst installer

These remain on `dev` and will be considered for a later release once tested.

---

## Before you cut the tag

1. **Promote `dev` to `main` without the appliance commits.** Eight appliance
   commits are `dev`-only, but eleven ISO commits are *already on `main`* and
   would otherwise ship regardless of what these notes say. Decide whether to
   revert them from the release line or correct this document.
2. **Leave the orphaned `v1.4.2` tag alone, or delete it.** It exists at
   `ae55fe1` (2026-09-24) as an unpublished appliance snapshot — no GitHub
   release, no registry entry — so it does not collide with this release. Decide
   whether to keep it as a build reference or remove it; do not move it.
   Note that `main` carries `build(iso): pin release v1.4.3` commits, which name
   a version that will now never exist. Those are ISO build refs and fall under
   the appliance exclusion below.
3. **Recompute the TCB Fingerprint from the tagged tree** and replace the value
   at the top of this file.
4. **Append to the signed registry** and republish `releases.json` with
   `releases.json.minisig`. Until then the Verify button says `unreleased`.
5. Publish the GitHub release with these notes.

Items 3–5 need the owner's offline signing key at `~/.safi/tcb-sign.key` and
cannot be done from CI.
