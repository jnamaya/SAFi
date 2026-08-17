# SAFi Release Process

> **Last updated:** 2026-08-16

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

## What every release contains

- A tag on `main`, with notes covering what changed and any upgrade steps.
- A **`TCB Fingerprint:`** line: the SHA-256 root fingerprint over the Core
  Loop files (the Trusted Computing Base), computed from the tagged tree's
  own integrity manifest. This value is what makes the release the
  production tier.

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
  (License & Governance Agreement, Section IV).

No local command crosses that line. Regenerating a manifest
(`verify_integrity.py --update`) only makes a tree consistent with itself.

## Security fixes

Fixes land on `dev` like everything else and are promoted to `main`
immediately when urgent, followed by a point release when the fix touches
anything a production install runs. Point releases publish their own TCB
Fingerprint like any other release.
