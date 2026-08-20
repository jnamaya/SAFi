---
title: SAFi Managed Operator
slug: managed-operator
tags: ["safi", "managed", "hosting", "operator", "pricing", "safi"]
summary: SAFi is open source and self-hostable, and there is also a managed option: we operate a dedicated SAFi instance inside the customer's own environment while they keep the infrastructure, the AI model keys, the data and the governance records.
version: 1.0
---

# SAFi Managed Operator

SAFi is open source and designed to be self-hosted. Anyone can run it. There is
also a managed option for organizations that want to use SAFi without carrying
the operational burden on day one.

**We bring our talent. You bring your resources.** We operate a dedicated SAFi
instance in the customer's own environment while the customer retains ownership
of the infrastructure, the data, the AI model keys and the governance records.

## The managed path

The customer does not have to change their infrastructure. SAFi can run wherever
they already run: in-house servers, or a cloud account on Azure, AWS, GCP or
another provider that meets their requirements. They provide the environment and
their own AI model provider keys. We deploy and operate SAFi on their behalf
inside that boundary.

Because SAFi is open source, this is not a proprietary hosted service. The
customer can inspect the software, verify the running release, restrict our
access, revoke it, and take over operations whenever they choose.

## Why organizations choose it

- **The deployment stays inside the boundary they already trust.** No new vendor
  cloud to vet, no data-residency negotiation, no unfamiliar hosting to procure.
- **Expert operational support from the start.** Deployment, updates, monitoring,
  backups, restore testing and routine health work are handled.
- **Ownership of the critical assets stays with the customer:** infrastructure,
  AI model keys, data, policies and governance records.
- **Reduced lock-in.** The software can be inspected, the deployment verified,
  access revoked, and operations transitioned to the customer's own team.
- **A path to self-operation.** We can train the customer's IT team to take on
  the operator role when they are ready.

## What each side does

We provision and deploy SAFi on the customer's Linux machine from a published,
integrity-verified release; set up secure access at their own domain; apply
release-cadence updates and security hotfixes; run monitoring, backups and
tested restores; attest that the running Core Loop matches an official release by
its TCB Fingerprint; and handle incidents and routine health work.

The customer provides the environment, their own AI model provider API keys
(entered in the app, stored under the deployment's security controls), and their
policies, agents and users. All governance records and conversation data remain
at rest on their machine.

## Environment

The operating system is Linux, which all of SAFi's tooling and the reference
deployment assume. SAFi can be deployed either as a Docker stack or as a
bare-metal installation with system services, a Python virtual environment and a
reverse proxy, so the deployment path can match the customer's own standards.

## Access

Operating SAFi requires administrative access to the SAFi host, because
installing MCP tool servers, system packages and updates all need it. That access
is limited to the SAFi machine and does not extend to the rest of the customer's
environment unless they separately authorize integrations. The customer grants
the access with credentials their organization issues and governs, and retains
the ability to audit, rotate, restrict and revoke it at any time. Session-logged
bastion access is available so every administrative action is reviewable.

## Pricing structure

Pricing and service levels are scoped per deployment and finalized in a written
statement of work and service agreement. The structure:

- The customer pays their hosting provider for the machine at cost, with no
  markup.
- Model usage is billed by the customer's AI provider directly, because the keys
  are theirs. We never front, mark up or pool model spend.
- Setup is billed as time and materials, with an estimate and a not-to-exceed cap
  agreed up front. Installing SAFi is quick; getting an organization live involves
  their security review, access provisioning, environment setup and policy design,
  which move at the organization's pace.
- Once live, a flat monthly fee covers operating the instance: updates,
  monitoring, backups, incident response and integrity attestation, with SLA
  tiers for teams and enterprises.

## What it is not

- Not a reseller of model access. Customers bring their own keys and pay their
  provider directly.
- Not custom engineering. The service is operating stock SAFi; bespoke features
  or plugins are a separate engagement.
- Not a replacement for the customer's compliance function. SAFi produces the
  evidence; deciding policy and reading the audit trail stays with the customer,
  though we can advise.
- Not an end-user help desk for the customer's staff.

To discuss a managed deployment, use the form on the Get Involved page at
https://selfalignmentframework.com/get-involved/ and mention managed hosting.
