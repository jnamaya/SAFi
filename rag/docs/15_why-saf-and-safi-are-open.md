---
title: Why SAF and SAFi Are Open
slug: why-saf-will-always-be-open
tags: ["safi", "philosophy", "licensing"]
summary: SAF and SAFi are open because a governance system should not ask people to trust reasoning they cannot inspect. The Self-Alignment Framework began as a personal attempt to understand human judgment, responsibility, and the structure of the human experience.
version: 1.0
---

# Why SAF and SAFi Are Open

SAF and SAFi are open because a governance system should not ask people to trust reasoning they cannot inspect.

The Self-Alignment Framework began as a personal attempt to understand human judgment, responsibility, and the structure of the human experience. SAFi applies that work to agentic AI as a runtime governance layer.

The personal origin explains why this project matters to me. It is not, by itself, a reason for anyone else to trust it. The practical reason for openness is simpler: when software evaluates an agent’s decisions, the implementation of that evaluation should be available for inspection, testing, and criticism.

## Ethics cannot be a black box

An AI system can generate text, make decisions, call tools, and take actions on behalf of people and organizations. When that system is governed by policies or values, those policies should not disappear inside an opaque service.

A governance layer that cannot be examined creates a difficult contradiction. It asks people to trust the mechanism checking the AI without giving them enough evidence to understand how that mechanism works.

Open source does not solve every problem. It does not make a framework correct, an agent reliable, or a model honest. It does make the covered implementation available for examination. People can read the code, test its behavior, compare it with its documentation, and challenge claims that the evidence does not support.

That distinction matters:

> Openness does not prove that a system is right. It makes the system checkable.

## Two related projects, two licenses

SAF and SAFi are closely related, but they are not the same thing.

SAF, the Self-Alignment Framework, is the conceptual framework. It describes a way of thinking about understanding, choice, judgment, and coherence. It is the philosophical and cognitive foundation.

SAFi is the software implementation. It is a runtime governance engine for agentic AI. SAFi applies policies while an agent is operating, records governed decisions, and provides an audit trail that can be inspected afterward.

In simple terms:

Because SAF and SAFi are different kinds of work, they are released under different licenses.

## Why SAF uses an attribution license

The SAF framework is released under a permissive attribution license based on the MIT model.

The intention is to let people study the framework, discuss it, teach it, adapt it, and build other work on top of it. That includes academic research, AI alignment work, software projects, and personal use.

The license includes an attribution requirement. If the structure or methodology of SAF appears in another work, the origin should be acknowledged. For example:

> Self-Alignment Framework (SAF), originally structured by Nelson Amaya.

This is a light condition on use, not a prohibition on adaptation or reuse. It asks that the framework’s origin not be quietly erased.

The published SAF license is authoritative. This article describes the intent behind it, but it does not replace the license text.

## Why SAFi uses AGPL-3.0

SAFi, the software, is released under the GNU Affero General Public License version 3, or AGPL-3.0.

The choice is deliberate.

Under a standard GPL license, copyleft obligations are generally triggered when covered software is distributed. If someone modifies the software and runs the modified version only as a hosted service, there may be no distribution to the people using that service.

The AGPL addresses certain network use. If someone modifies covered SAFi software and makes that modified version available for users to interact with over a network, the AGPL requires the operator to provide those users an opportunity to receive the corresponding source code, as defined by the license.

The precise obligations depend on the software, the modifications, the way components are combined, and the deployment structure. The AGPL-3.0 license text remains authoritative, and this article is not legal advice.

The reason for choosing AGPL is straightforward:

> A governance engine should not be easy to turn into a closed service while keeping the governance modifications hidden from the people who depend on it.

The license does not reveal every part of an entire service. It applies to covered software and the obligations defined by the license. But it helps preserve the principle that modifications to the covered governance layer should remain available for inspection when that layer is offered as a network service.

## What openness gives users

Open licensing is not only a statement about the project’s values. It creates practical options for the people evaluating or operating SAFi.

### For platform engineering teams

Openness makes it possible to:

For engineers, the central question is not whether a project describes itself as transparent. It is whether the relevant implementation can actually be examined and tested.

### For IT directors and technology leaders

Open source can reduce dependence on a single governance provider.

It gives your organization the ability to evaluate the system before making a long-term commitment, operate it within your own infrastructure, and retain the option to modify, fork, replace, or discontinue it.

That does not eliminate operational responsibility. Your organization still needs to manage deployment, security, model providers, policies, data, and access controls. Openness simply means those decisions are not forced to depend on an inaccessible governance implementation.

### For AI governance, compliance, and risk practitioners

Open source gives governance and risk teams a more concrete object to examine.

You can review how policies are represented, how decisions are recorded, and how the system describes its own enforcement behavior. You can connect governance claims to source code, runtime tests, and audit records instead of accepting broad assurances without evidence.

The same applies to legal and compliance review. Open implementation does not eliminate contractual, regulatory, or operational risk, but it can improve the evidence available when those risks are assessed.

## What openness does not promise

It is important to be precise about what the licenses do and do not guarantee.

Open licensing does not guarantee that:

SAFi is a governance layer. It does not remove the need for responsible model selection, secure infrastructure, carefully written policies, tool restrictions, human oversight, or ongoing evaluation.

Its purpose is to make governance more explicit and more accountable. SAFi can enforce policies at runtime, record governed decisions, and provide evidence about what happened. Those capabilities are valuable precisely because they can be examined rather than accepted as a black-box promise.

## Open by design

The licenses are part of SAF and SAFi’s design, not an afterthought.

The framework is open so that its ideas can move freely, receive criticism, and develop beyond their original form.

The software is open so that its governance mechanisms can be inspected, tested, operated, and challenged.

This is not a claim that openness is fashionable or automatically superior in every situation. It is a claim about consistency. If a project argues that AI governance should be transparent and accountable, the project’s own core reasoning and implementation should meet that standard as far as its licenses and architecture provide.

Trust should not depend on a marketing promise alone.

## The commitment

The core SAF framework and the core SAFi engine will remain available under their published open licenses.

That commitment does not make SAF correct, and it does not make every governed agent reliable. It means that the framework and covered implementation remain available for examination under the terms of those licenses.

Readers can inspect the source, test runtime behavior, review audit records, and challenge claims that the evidence does not support.

If you want to evaluate the claim, do not take this article on faith:

The license files are authoritative. This article explains the principle behind them.

SAF and SAFi are open because a system that asks to be trusted with questions of value should not keep its own governing logic hidden.
