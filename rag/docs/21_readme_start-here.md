---
title: SAFi README: Start Here
slug: readme-start-here
tags: ["safi", "readme", "safi"]
summary: Pick the role that fits — each path starts somewhere different. **You do not have to rebuild your stack.** The [`/evaluate` gateway](docs/DEVELOPER_GUIDE.md#9-the-evaluate-gateway) governs the output of an agent you have already built — your orchestration, prompts and tool layer stay where they are.
version: 1.0
---

# SAFi README: Start Here

Pick the role that fits — each path starts somewhere different.

## If you run the platform

> Add a deterministic governance layer to your AI agents without tying your policies or audit history to a single model provider.

**You do not have to rebuild your stack.** The [`/evaluate` gateway](docs/DEVELOPER_GUIDE.md#9-the-evaluate-gateway) governs the output of an agent you have already built — your orchestration, prompts and tool layer stay where they are.

- [Quick Start](#quick-start) — Docker and a database, nothing else
- [Developer Guide](docs/DEVELOPER_GUIDE.md) — repo layout, architecture, policy authoring, tool authorization, integration surfaces
- [Good first issues](https://github.com/jnamaya/SAFi/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

## If you own the technology strategy

> Keep your organization's values in control of AI behavior, preserve an auditable record of decisions, and hold that governance in place when the underlying models change.

**Portability is the strategic point.** Your charter, your policies and your audit trail live in *your* database. Switching or upgrading a model changes which model drafts and changes nothing about what it is held to, or what you can prove afterward.

- [Regulatory Readiness](#regulatory-readiness) — readiness documents for SEC/FINRA, the EU AI Act, HIPAA and GDPR, each stating what ships today against what is roadmap
- [Live Demo](https://safi.selfalignmentframework.com) — the fastest way to see what a governed turn produces

## If you practice governance

> Turn organizational values into enforceable runtime policy, preserve the evidence behind every decision, and measure behavioral drift against the standard you defined.

- [A worked example](https://selfalignmentframework.com/building-a-mission-aligned-agent-with-safi/) — a real organization's value set, the answer produced, the value-by-value ledger with a confidence on each score, and the audit record for that turn
- [Math Specification](https://selfalignmentframework.com/safi-math-specification/) — the formulas, and what each faculty is denied
- [Benchmarks & Validation](#benchmarks--validation) — with the derivation published, not just the score

---
