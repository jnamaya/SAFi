# Contributing to SAFi

Thank you for your interest in SAFi, an open-source runtime governance engine for agentic AI.

Contributions of all kinds are welcome, including bug reports, documentation improvements, faculty-module improvements, MCP tool integrations, policy examples, tests, and governance documentation.

## Before You Start

- Read the [README](README.md) for an overview of SAFi’s architecture and evaluation path.
- Review the project’s license and attribution notices.
- Review the [faculty table in the README](README.md#the-five-faculties) to understand how the runtime components are organized.
- Browse [open issues](https://github.com/jnamaya/SAFi/issues). Issues labeled [`good first issue`](https://github.com/jnamaya/SAFi/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) are the best starting points.
- For substantial changes, open a discussion before beginning implementation.

## Ways to Contribute

### Bug Reports

Open a [GitHub Issue](https://github.com/jnamaya/SAFi/issues/new) with:

- What you expected to happen
- What actually happened
- Steps to reproduce the issue
- The affected SAFi version or commit
- Your environment, including operating system and Python version
- Relevant configuration, policy, or deployment details
- Redacted logs or audit records, where useful

Do not include secrets, credentials, personal data, or other sensitive information.

### Feature Requests

Open a [GitHub Discussion](https://github.com/jnamaya/SAFi/discussions) in the *Ideas* category.

Describe:

- The operational problem or use case
- Who is affected
- The proposed behavior
- Alternatives you considered
- Any policy, audit, security, or maintenance implications

Describe the use case rather than only requesting a feature.

### Code Contributions

1. Fork the repository and create a branch from `dev`, not `main`:

   ```bash
   git checkout dev
   git checkout -b feature/your-feature-name   ```

2. Make your changes. Common areas:

   - New MCP tool: `safi_app/core/mcp_servers/`, registered in `mcp_manager.py`
   - New agent: use the agent wizard, or the extension seam described in the
     [Developer Guide, section 18](docs/DEVELOPER_GUIDE.md#18-extending-safi-agents-and-plugins-without-core-changes).
     Neither requires touching core files.
   - Front-end: `public/` (rebuild the Tailwind CSS after class changes; see the README)

3. Test your changes with the disposable test stack before submitting:

   ```bash
   docker compose -f docker-compose.test.yml run --rm --build tests
   ```

4. Open a Pull Request against `dev` with a clear description of what changed and why.

### Documentation

Documentation improvements are always welcome. The `docs/` directory holds the developer guide, the mathematical specification, and the License and Governance Agreement. The main `README.md` is the public face of the project.

## Branching and Releases

SAFi uses a dev-first flow with three stability tiers. Knowing it tells you where to send a change and when it will ship.

- **`dev`** is the active development branch. Every contribution lands here first. Branch from `dev` and open your pull request against `dev`, never against `main`.
- **`main`** is release-staging. It holds only tested, soaked, release-ready code, and it advances only at a release, so it deliberately lags `dev` for most of a cycle. Do not open pull requests against it.
- **Tags** are the official releases, cut from `main`. Production installs run these, because only a tagged release publishes the Core Loop fingerprint used to verify authenticity.

Releases are cut on a fixed cadence of every 8 weeks. After your pull request is merged to `dev`, it soaks there until the next release, when the accumulated work is promoted to `main` in one move and tagged. That gap between merge and release is deliberate: it is how regressions surface before they reach a release.

Maintainers promote `dev` to `main` only when all of the following hold, so keeping your pull request green is what keeps that path clear:

- The full test suite passes on the disposable stack.
- The Core Loop integrity manifest verifies INTACT (see below).
- The change has soaked on `dev` without regressions.
- It is release time (the freeze week, or the week before). Urgent security fixes are the only exception, and they still must pass the tests.

## Architecture Principles to Respect

All contributions must preserve:

- **The air gap.** The Intellect never executes tools directly. All execution goes through the Will gate.
- **Zero-LLM enforcement.** The Will, Phase Zero, Spirit, and Synderesis are pure deterministic Python. No model calls in those files, ever. Only the Intellect and the Conscience may call a model.
- **Faculty separation.** Each faculty has a single, well-defined role. Do not add governance logic to the Intellect or generative logic to the Conscience.

## The Core Loop manifest

The files that SAFi's governance claims depend on are enumerated in `scripts/core_integrity_manifest.json` and verified by `scripts/verify_integrity.py`, both in CI and at application startup. If your change touches one of these files, regenerate the manifest in the same commit:

```bash
python scripts/verify_integrity.py --update
```

CI fails any push that edits a covered file without updating the manifest. Because these files define the governance behavior of every deployment, changes to them get closer review; open a discussion first for anything beyond a clear bug fix.

## Code Style

- Python: follow the existing conventions in the codebase (PEP 8, async/await for I/O)
- No new dependencies without discussion in an Issue first
- Keep faculty modules focused. If a change touches more than two faculties, open a discussion first.

## Questions

Open a [GitHub Discussion](https://github.com/jnamaya/SAFi/discussions) or reach out to the author via the links in the README.
