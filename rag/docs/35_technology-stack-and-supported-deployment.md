---
title: SAFi Technology Stack and Supported Deployment
slug: technology-stack-and-supported-deployment
tags: ["safi", "tech-stack", "architecture", "deployment", "tcb", "usb"]
summary: SAFi runs on Python, Flask and MySQL, supports Linux only, and is split into a Trusted Computing Base (the Core Loop, which needs maintainer approval to change) and a User Space Base (everything else, which is free to customize). A supported production deployment never exposes the application directly to the internet; a reverse proxy terminates TLS on port 443 in front of it.
version: 1.0
---

# SAFi Technology Stack and Supported Deployment

SAFi's technology stack is fixed, not a menu of options, chosen for security,
reliability and nimbleness. Every file in the Trusted Computing Base is
Python, which is the practical reason the stack does not flex: the governance
engine is not portable across runtimes without becoming a different program.

## The core stack

- **Python** 3.11 through 3.13. A range, because the operating system provides
  it and SAFi will not require an interpreter version the distribution does
  not ship. The Docker image pins one exact version for a reproducible build.
- **Flask** 3.x, pinned in `requirements.txt`, not a deployment choice.
- **MySQL** 8.0 or later, run from a package, a container, or a managed
  service.

## Supported platform

SAFi is supported on Linux only. It may well run on Windows, macOS, or
whatever else is popular this year, but an installation on any other
operating system is unsupported: if something is slow or broken there, that
is left for the operator to debug.

## The TCB/USB boundary: what can change, and what needs approval

SAFi is divided into two tiers, and the boundary decides both what is safe to
modify and what a deployment is allowed to call itself.

**The User Space Base (USB)** is everything outside the Core Loop: the API
surface, the front end, persistence wiring, plugins, agents, policies, and
deployment tooling. This is most of what an organization touches to fit SAFi
to its own needs, and it is free to change.

**The Trusted Computing Base (TCB)** is the Core Loop: the files implementing
the five faculties, the orchestrator, and the components that enforce policy
and produce the audit record. A change here alters governance behavior for
every agent, every organization and every turn at once, so it requires
maintainer review and approval. The covered file set is fixed and checked
against a signed manifest.

Two consequences follow from that boundary:

- **Support.** An installation running a different stack, or a modified TCB,
  is not supported by the maintainers until the differences are reconciled.
- **The name.** Whether a deployment may call itself SAFi is governed by the
  License and Governance Agreement's trademark policy, and turns on
  integrity: a deployment can claim to be authentic SAFi only when its TCB
  Fingerprint matches an official release. A modified TCB fails that check
  by construction, which is a mechanism, not a judgment call anyone makes by
  hand.

## Production deployment architecture

A supported production deployment rests on one non-negotiable rule and four
pieces of infrastructure around it.

**Never expose the application directly to the internet.** The application
process must not be reachable from the public internet on any port. It binds
to localhost, and a reverse proxy is the only route in. All external traffic
terminates at port 443 over TLS.

The four pieces: a WSGI server (SAFi ships with gunicorn), a process
supervisor (systemd, with unit files provided for the app itself and for
optional companion services like the scheduler, the knowledge-base indexer,
backups and retention), a reverse proxy (Apache or nginx) terminating TLS and
forwarding to the application's local port, and correctly configured proxy
routes for everything a deployment uses beyond the core app, including
authentication callbacks and, for directory provisioning, the SCIM endpoint
(which requires HTTPS and reads the `X-Forwarded-Proto` header). Most
authentication, SSO, and SCIM problems in production trace back to the
reverse proxy's routes or headers, not the application itself.

## If an organization would rather not run it themselves

SAFi is open source and self-hostable, and that is a real option, not a
formality. For organizations that would rather not operate a governance
engine themselves, there is also a managed option: a dedicated SAFi instance
deployed and operated inside the customer's own environment while the
customer keeps the infrastructure, the model keys, the data and the
governance records. See the Managed Operator service for details.
