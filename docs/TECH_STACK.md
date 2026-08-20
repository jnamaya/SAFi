# SAFi Technology Stack and Supported Deployment

## Purpose

This document defines the technology stack SAFi runs on, and what the
maintainers support. The stack was chosen deliberately for three reasons:
security, reliability, and nimbleness. It is not an accident of history, and it
is not a menu of options.

Every file in the Trusted Computing Base is Python. That is the practical reason
the stack is fixed rather than advisory: the governance engine is not portable
across runtimes without becoming a different program.

## The core stack

| Component | Supported |
|---|---|
| Python | 3.11 through 3.13 |
| Flask | 3.x |
| MySQL | 8.0 or later |

Python is a range because your operating system provides it, and SAFi will not
ask you to install an interpreter your distribution does not ship. Flask arrives
pinned in `requirements.txt` and is not a deployment choice. MySQL is yours to
run, from a package, a container, or a managed service.

The Docker image pins one exact Python, because a reproducible image should be
deterministic. The range is for installs that bring their own interpreter.

Those components ship in the Docker image. For development and testing, the
[Quick Start](../README.md#quick-start) should have you running in under ten
minutes on a decent connection.

## Supported platform

**SAFi is supported on Linux only.**

You may well get it running on Windows, macOS, or whatever else is popular this
year. Nothing stops you. But an installation on any other operating system is
unsupported: if it is slow, or something does not work, that is yours to debug.
Maintainer time does not go there.

## What you may change, and what you may not

SAFi is divided into two tiers. The boundary decides both what you can safely
modify and what the name means. The full treatment is in the Developer Guide,
[section 19: The TCB, User Space, and how they talk](DEVELOPER_GUIDE.md#19-the-tcb-user-space-and-how-they-talk).

**The User Space Base (USB)** is everything outside the TCB: the API surface, the
front end, persistence wiring, plugins, agents, policies, and deployment
tooling. This is most of what a developer touches to fit SAFi to an
organization, and you are free to change it. That freedom is the point, and
[section 18](DEVELOPER_GUIDE.md#18-extending-safi-agents-and-plugins-without-core-changes)
covers how to extend SAFi without going near the core.

**The Trusted Computing Base (TCB)** is the Core Loop: the files covering the five
faculties, the orchestrator, and the components that enforce policy and produce
the audit record. A change here alters governance behaviour for every agent,
every organization, and every turn at once, so it requires review and approval by
the maintainers. The covered set is listed in
[`scripts/core_integrity_manifest.json`](../scripts/core_integrity_manifest.json)
and enforced by [`scripts/verify_integrity.py`](../scripts/verify_integrity.py).

Two separate consequences follow, and they should not be confused:

- **Support.** An installation running a different stack, or a modified TCB, is
  not supported by the maintainers until the differences are reconciled.
- **The name.** Whether a deployment may call itself SAFi is governed by the
  [License and Governance Agreement, Section IV](SAFi%20License%20%26%20Governance%20Agreement.md#iv-trademark-policy),
  and it turns on integrity: a deployment can claim to be authentic SAFi only
  when its TCB Fingerprint matches an official release. A modified TCB fails that
  check by construction. That is a mechanism, not anyone's discretion.

Which release a deployment should install, and how to pin and verify its
fingerprint, is covered in the [Release Process](RELEASE_PROCESS.md).

## Production deployment

The step-by-step build of a bare-metal host is in
[Deploying SAFi on bare metal](DEPLOY_BAREMETAL.md). This section states the
architecture that deployment has to satisfy, and why.

### Never expose the application directly to the internet

The application process must not be reachable from the public internet. Not on
port 5000, not on 5001, not on anything. Bind it to `127.0.0.1` and let the
reverse proxy be the only route in. If a deployment is compromised because the
application was exposed directly, that is a configuration failure and not a
defect in SAFi.

All external traffic terminates at **port 443**. You will need a TLS
certificate; obtaining one is out of scope here.

### The four pieces

1. **A WSGI server.** SAFi ships with **gunicorn**, and the entry point,
   [`wsgi.py`](../wsgi.py), is in the repository root.
2. **A systemd service** to run and supervise it. A unit file is provided at
   [`deploy/systemd/safi.service`](../deploy/systemd/safi.service); adjust the
   paths, user, worker count and bind address for your environment. Units for the
   scheduler, the knowledge-base indexer, backups and retention live in the same
   directory, and the ones you need depend on which features you run.
   ([Deploy guide, systemd](DEPLOY_BAREMETAL.md#7-systemd).)
3. **A reverse proxy**, Apache or nginx, terminating TLS on 443 and forwarding to
   the local port the application is bound to (5001 in the shipped unit, 5000 in
   the Docker image, configurable via `APP_PORT`).
   ([Deploy guide, reverse proxy](DEPLOY_BAREMETAL.md#8-reverse-proxy).)
4. **Proxy routes for everything else.** A real deployment usually needs more
   than one path proxied: the application, the authentication callbacks, and, if
   you use directory provisioning, `/scim/v2`. Headers matter as much as routes.
   SCIM requires HTTPS and reads `X-Forwarded-Proto`, so a proxy that does not set
   it produces authentication and provisioning failures that look like application
   bugs.

### Before reporting a problem

If authentication, single sign-on, or SCIM misbehaves in production, check the
reverse proxy first: its routes, and the headers it forwards. That is where these
failures usually live, and "it works on my machine" is more often a proxy
difference than an application difference.

## If you would rather not run it yourself

SAFi is open source and self-hostable, and that is a real option, not a
formality. For organizations that would rather not operate a governance engine,
there is a managed option: we deploy and operate a dedicated instance inside your
own environment while you keep the infrastructure, the model keys, the data and
the governance records. See [SAFi Managed Operator](MANAGED_OPERATOR.md).

---
