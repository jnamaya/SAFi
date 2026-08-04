---
title: SAFi README: For Developers
slug: readme-for-developers
tags: ["safi", "readme", "safi"]
summary: Working on the code? Start with the **[Developer Guide](docs/DEVELOPER_GUIDE.md)** — it covers:
version: 1.0
---

# SAFi README: For Developers

Working on the code? Start with the **[Developer Guide](docs/DEVELOPER_GUIDE.md)** — it covers:

- **Repo structure & local setup** — how the front-end (`public/`), back-end (`safi_app/`), and mobile (`mobile/`) trees are laid out, the Docker quick start, and the two no-SSO login paths (local admin, demo).
- **The architecture** — the five-faculty separation of powers (Synderesis, Intellect, Will, Conscience, Spirit), the Air Gap containment principle, and a condensed math primer linking to the full [Math Specification](https://selfalignmentframework.com/safi-math-specification/).
- **Multi-agent design & policy authoring** — how an org runs multiple agents side by side, the agent/policy two-tier binding, how Synderesis compiles a governance profile fresh on every turn, policy versioning, and what the agent- and policy-wizards can (and can't) build.
- **Integration surfaces** — the `/evaluate` gateway for governing an external agent's output, the internal Flask blueprint + two-check RBAC pattern for adding API routes, and SSO (Google Workspace, Microsoft Entra) with the org-join behavior worth knowing before configuring it for a customer.
- **Compliance internals** — the hash-chained audit trail, encryption at rest and key rotation, and retention purging with legal hold (including its honestly-documented gaps).
- **RAG & tool integrations** — FAISS-backed retrieval, the plugin-vs-tool distinction, the two-layer tool authorization (advertised schemas + the Will's per-intent allow-list gate), and the recipe for adding a new tool.
- **The Audit Hub metrics & testing** — what Alignment, Consistency, and the Beta retention setting actually measure, why scores stabilize only after a policy is finished being tested, and how to run the test suite.

---
