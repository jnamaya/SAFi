---
title: License and Governance
slug: license
tags: ["safi", "licensing", "governance", "trademark", "integrity"]
summary: SAF the framework is free to use with attribution. SAFi the software is licensed under AGPL-3.0, copyright (c) 2025 Nelson Amaya, with an organization exception that keeps a deployer's own policies, tools, and data private. The Core Loop is verifiable by fingerprint, and the SAFi name requires an intact Core Loop or upstream review.
version: 2.0
---

# License and Governance

Two different things carry licenses here, and they are licensed differently.

## SAF, the framework

The Self-Alignment Framework (SAF) is the philosophical and design vocabulary
behind the software: the five faculties and the reasoning about how values
become action. SAF is licensed separately and is free to use with attribution.
The framework license is published at
[selfalignmentframework.com/license](https://selfalignmentframework.com/license/).

## SAFi, the software

SAFi, the software implementation, is licensed under the GNU Affero General
Public License, version 3.0 (AGPL-3.0), copyright (c) 2025 Nelson Amaya. Under
the AGPL, anyone who modifies SAFi and offers it over a network must make their
modified source code available under the same license.

The full terms live in the repository: the `LICENSE` file and the SAFi License
and Governance Agreement under `docs/`.

## What stays yours: the organization exception

The copyright holder grants an exception under Section 7 of the AGPL-3.0.
Organizations deploying SAFi keep the following fully private, with no
obligation to publish them:

- Charters, policies, values, and rubrics (configuration data)
- Custom tools, knowledge bases, plugins, and extension agents
- Branding, interface customization, and help files
- Authentication and identity infrastructure
- All database content, including audit trails and user data

In short: the engine is open, and what you configure on top of it is yours.

## The Core Loop, and how to verify it

The copyleft core is called the Core Loop: the orchestrator, the five
faculties, the audit schema, the enforcement content that feeds them, and the
verification machinery itself. In security terms this set is SAFi's Trusted
Computing Base, and it is enumerated file by file in a signed manifest.

Any deployment can verify its own Core Loop:

    python scripts/verify_integrity.py

The check recomputes a cryptographic hash of every Core Loop file, compares
the result against the release manifest, and reports a single fingerprint.
SAFi also runs this check on itself at startup, logs the result, and stamps
the fingerprint into every governance record it produces, so each audit
record names the verified code that made it.

## The SAFi name

Anyone may fork and modify SAFi; the AGPL guarantees it. Representing a
modified deployment as SAFi is a separate question, governed by trademark
policy: a deployment may call itself SAFi if its Core Loop verifies intact,
or if its modifications were submitted upstream and accepted. Deployments
that modify the Core Loop without review must use a different name.

## Where to read more

- The `LICENSE` file in the repository root (AGPL-3.0)
- The SAFi License and Governance Agreement in `docs/`, which defines the
  Core Loop, the organization exception, and the trademark policy in full
- The framework license at selfalignmentframework.com/license
