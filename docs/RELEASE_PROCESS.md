# SAFi Release Process

> **Last updated:** 2026-09-05

How SAFi's code moves from development to something a production deployment
can verify. This is the operator- and contributor-facing description of the
process; the developer-side boundary rules live in the
[Developer Guide, section 19](DEVELOPER_GUIDE.md#19-the-tcb-user-space-and-how-they-talk).

## The three tiers

| Tier | What it is | Who should use it |
|---|---|---|
| `dev` branch | Active development. Changes land here first, tested but still settling. | Contributors and the curious. |
| `main` branch | Stable. Advances only by deliberate promotion from `dev` after work has soaked. | Evaluations, development against SAFi. |
| **Official releases** | Tags cut from `main`, each publishing its **TCB Fingerprint**. | **Production.** |

`git clone` gives you `main`, which is kept stable and is fine for trying
SAFi out. Production installs should use the latest release instead, because
only a release is *verifiable*: its notes publish the TCB Fingerprint of the
exact code it contains, and no branch offers that anchor.

## Cadence

Releases target an **8-week cadence** (anchored on v1.4.1, August 2026). The
final week of each cycle is a freeze: a last promotion from `dev` to `main`,
then fixes only until the tag is cut. A target is not a contract; if a cycle
ends with something half-settled, the release waits for it rather than
shipping it.

## Versioning

Releases use three-part semantic versions (`vMAJOR.MINOR.PATCH`, e.g.
`v1.5.0`), tags lowercase, release titles matching their tags. The parts
carry governance meaning, so the number answers the operator's real
question: do I need to re-verify and re-pin?

- **PATCH** (`v1.5.1`): fixes only. Normally the TCB Fingerprint is
  unchanged, so a pinned deployment can take the patch without updating
  `SAFI_EXPECTED_FINGERPRINT`. When a fix must touch the Core Loop, the
  release notes say so loudly and the fingerprint changes.
- **MINOR** (`v1.5.0`): the regular cadence releases. Features and reviewed
  Core Loop changes; expect a new TCB Fingerprint and read the upgrade
  notes.
- **MAJOR** (`v2.0.0`): breaking for operators. Manual migration steps, API
  breaks, or changes to what the Core Loop covers.

Releases before this convention used two-part versions (`v1.4`); from
`v1.5.0` on, versions are always three parts.

## What every release contains

- A tag on `main`, with notes covering what changed and any upgrade steps.
- A **`TCB Fingerprint:`** line: the SHA-256 root fingerprint over the Core
  Loop files (the Trusted Computing Base), computed from the tagged tree's
  own integrity manifest. This value is what makes the release the
  production tier.
- A registry entry: the same fingerprint appended to the official release
  list at `https://selfalignmentframework.com/tcb/releases.json`, the
  machine-readable source of truth for the "Verify this Install" button.

## Verifying and pinning a deployment

Anyone can check what a deployment is running, without the vendor's help:

```bash
python scripts/verify_integrity.py
```

The script hashes the Core Loop against the shipped manifest, checks the
structural invariants (no model call inside a deterministic faculty, phase
order intact), and prints the tree's TCB Fingerprint. Compare that value
against the `TCB Fingerprint:` line on an official release: a match means
the deployment runs that release's Core Loop, byte for byte. The same
fingerprint is stamped into every governance record the deployment
produces, so the comparison also works retroactively, from the audit trail
alone.

Operators can additionally pin their deployment: set
`SAFI_EXPECTED_FINGERPRINT` in `.env` to the fingerprint copied from the
release you installed. Every boot then re-checks the running code against
the value you verified, a mismatch is logged loudly, and
`SAFI_ENFORCE_INTEGRITY=strict` refuses to start on one. Update the pin
when you upgrade; that update is you re-performing the check against the
new release's published value.

## The official release registry

The site at <https://selfalignmentframework.com/tcb/> publishes the
append-only list of official release fingerprints. Each new release adds
one entry; no entry is ever removed, so an old install remains
recognisable as authentic for as long as it runs.

The list is signed. The whole file is signed with the project's registry
signing key (minisign, legacy raw-message format), and the signature is
published next to it as `releases.json.minisig`. The public half of the key
is published on the site as `TCB_KEY.pub` and committed to the repository
at `safi_app/api/tcb_key.pub`; the two copies are byte-identical (compare
SHA-256). The git history is the anchor outside the website: someone who
controls only the site cannot mint a new list, because they do not hold the
secret key, and a deployment whose pinned key differs from the publisher's
rejects the list instead of trusting it.

The product's **Verify this Install** button (Org settings, org admin role)
reads this registry directly. It hashes the deployment's Core Loop, fetches
the list, and checks the signature against the pinned key before trusting a
single fingerprint. It then reports one of five verdicts: `authentic`
(signature verified and fingerprint in the list), `unreleased` (intact but
not in the list, i.e. a dev snapshot or a fork), `modified`,
`unverifiable` (no verdict is possible: the local check failed, or the list
was reachable but did not authenticate), or `offline` (the list could not
be fetched; never a pass). Every check is written to the compliance log.
A reachable site serving a list that does not authenticate is always
`unverifiable`, never `offline` and never a pass.

Adding the entry is part of the release, not a follow-up. On the site
repository:

1. Append `{"tag", "date", "fingerprint"}` to `static_site/tcb/releases.json`.
2. Sign the result with the owner's secret key:
   `python scripts/tcb_sign.py static_site/tcb/releases.json \
   ~/.safi/tcb-sign.key ~/.safi/TCB_KEY.pub`
   The script bumps the `sequence` field, signs, and verifies before
   finishing. A release is a new sequence, never an edit of an old entry.
3. Publish `releases.json` and `releases.json.minisig` together, then
   rebuild and deploy the static site.

The secret signing key lives offline (default `~/.safi/tcb-sign.key`,
`chmod 600`), never in the repository and never on the web host.

Anyone can re-verify a published list without the product:

```bash
curl -O https://selfalignmentframework.com/tcb/releases.json \
     -O https://selfalignmentframework.com/tcb/releases.json.minisig \
     -O https://selfalignmentframework.com/tcb/TCB_KEY.pub
minisign -Vm releases.json -p TCB_KEY.pub
```

That performs the same authenticity check the button performs locally:
file bytes, not a view of them.

## Modified deployments and forks

The AGPL permits running modified SAFi, including modified Core Loop code,
with no functional restriction. What modification changes is certification,
and there are exactly two states:

- **Authentic**: the deployment's TCB Fingerprint matches an official
  published release. Modified Core Loop changes reach this state one way:
  submitted upstream as a pull request, reviewed, accepted, and shipped in
  a release.
- **Not authentic**: everything else. A fork that keeps Core Loop changes
  private runs fully and governs fully, and its own records still attest
  to its own build, but it cannot use the SAFi name or claim authenticity
  ([License & Governance Agreement](SAFi%20License%20%26%20Governance%20Agreement.md),
  Section IV).

No local command crosses that line. Regenerating a manifest
(`verify_integrity.py --update`) only makes a tree consistent with itself.

## Security fixes

Fixes land on `dev` like everything else and are promoted to `main`
immediately when urgent, followed by a point release when the fix touches
anything a production install runs. Point releases publish their own TCB
Fingerprint like any other release.
