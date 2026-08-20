---
title: SAFi README: Releases and Cadence
slug: readme-releases-and-cadence
tags: ["safi", "readme", "releases", "cadence", "versioning", "fingerprint", "safi"]
summary: SAFi ships on an 8-week release cadence. Production installs should use a tagged release and pin its published TCB Fingerprint, because only a release is verifiable.
version: 1.0
---

# SAFi README: Releases and Cadence

SAFi ships on an **8-week release cadence**, anchored on v1.4.1 (August 2026).
The final week of each cycle is a freeze: a last promotion from the `dev` branch
to `main`, then fixes only until the tag is cut. The target is not a contract. If
a cycle ends with something half-settled, the release waits for it rather than
shipping it.

## The three tiers

- **`dev` branch.** Active development. Changes land here first, tested but still
  settling. For contributors and the curious.
- **`main` branch.** Stable. It advances only by deliberate promotion from `dev`
  after work has soaked. Good for evaluations and for developing against SAFi.
  `git clone` gives you `main`.
- **Official releases.** Tags cut from `main`, each publishing its TCB
  Fingerprint. This is the tier production should use.

## Why production should use a release, not a branch

Only a release is *verifiable*. Its notes publish the TCB Fingerprint of the
exact code it contains, and no branch offers that anchor. A production deployment
should install the latest release and pin its published fingerprint, so the
running Core Loop can be checked against the release it claims to be.

## Versioning

Releases use three-part semantic versions (`vMAJOR.MINOR.PATCH`). The parts carry
governance meaning, so the number answers an operator's real question: do I need
to re-verify and re-pin?

- **PATCH** (for example v1.5.1): fixes only. Normally the TCB Fingerprint is
  unchanged, so a pinned deployment can take the patch without updating its
  expected fingerprint. When a fix must touch the Core Loop, the release notes say
  so and the fingerprint changes.
- **MINOR** (for example v1.5.0): the regular cadence releases. Features and
  reviewed Core Loop changes; expect a new TCB Fingerprint and read the upgrade
  notes.
- **MAJOR** (for example v2.0.0): breaking for operators. Manual migration steps,
  API breaks, or changes to what the Core Loop covers.

## What every release contains

- A tag on `main`, with notes covering what changed and any upgrade steps.
- A `TCB Fingerprint:` line: the SHA-256 root fingerprint over the Core Loop
  files, the Trusted Computing Base, computed from the tagged tree's own integrity
  manifest. That value is what makes the release the production tier.

The full process, including how a deployment verifies and pins the fingerprint,
is documented in the Release Process document in the repository.
