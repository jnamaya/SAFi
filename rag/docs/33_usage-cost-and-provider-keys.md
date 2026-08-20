---
title: SAFi Usage, Cost and Provider Keys
slug: usage-cost-and-provider-keys
tags: ["safi", "usage", "cost", "billing", "api keys", "byok", "models", "safi"]
summary: SAFi records token usage per organization and shows estimated spend by model, faculty, agent and day. An organization can also bring its own provider API keys, so its model usage bills to its own account.
version: 1.0
---

# SAFi Usage, Cost and Provider Keys

Every model call in SAFi passes through one provider layer, and every provider
response already carries token counts. SAFi records those counts so an
organization can see what its AI usage costs.

Availability: this landed after the v1.4.1 release. Check the release notes of
the version you install.

## What the Usage and Cost view shows

Token consumption for the organization, aggregated four ways:

- **By model**, with estimated cost, which is where the money goes.
- **By faculty**, which shows what governance itself costs: every governed turn
  pays for a Conscience audit on top of the Intellect's draft.
- **By agent**, which shows which agents drive consumption.
- **By day**.

Token counts are real, taken from the provider's own response. Dollar figures are
**estimates**, computed at display time from a configurable price map, not
invoices. They track current list prices and will not match a provider bill
exactly, because list prices change and things like cached input, batch pricing
and negotiated discounts are not reflected.

## Cost stays out of the governance record

Cost is recorded in a separate usage table, never in the governance record. That
is deliberate: an examiner adjudicates what the model saw and what it said, not
what it cost. Mixing spend into the audit trail would put commercial data into an
evidentiary artifact that does not need it.

## Bring your own provider keys

The deployment's keys, set in its environment, remain the default. An
organization may additionally store its own API key per provider from the
interface. When it does, that key replaces the deployment key for that
organization's calls, including background work, so its model usage bills to its
own provider account.

How the keys are handled:

- Stored encrypted, and never displayed again after saving. Only the last four
  characters are shown, so an administrator can tell which key is in place.
- Never written to logs.
- Changes take effect within about a minute.
- An organization with no stored key simply uses the deployment default. That
  layering is the intended behavior, not an error.
- If the key store cannot be read, the last known key is kept rather than
  silently falling back to the deployment key, because that fallback would break
  the billing separation the feature exists for.

Storing an organization key also makes a provider usable for that organization
even when the deployment itself has no key for it.

## Operator views

A deployment operator can also add models to the composer's picker from the
interface, each with an explicit provider so dispatch never has to guess from the
model name, and can see usage rolled up across every organization on the install
plus public traffic. That whole-deployment view is restricted to named super
administrators, so an operator can separate their own spend from everyone using
shared deployment keys.
