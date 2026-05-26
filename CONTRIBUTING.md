# Contributing to SAFi

Thank you for your interest in SAFi. Contributions of all kinds are welcome -- bug reports, documentation improvements, new faculty modules, MCP tool integrations, and governance policy examples.

## Before You Start

- Read the [README](README.md) for an overview of the architecture.
- Read [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) to understand the design principles behind the five faculties.
- Browse [open issues](https://github.com/jnamaya/SAFi/issues) -- issues labeled [`good first issue`](https://github.com/jnamaya/SAFi/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) are the best starting point.

## Ways to Contribute

### Bug Reports
Open a [GitHub Issue](https://github.com/jnamaya/SAFi/issues/new) with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Python version, LLM provider)

### Feature Requests
Open a [GitHub Discussion](https://github.com/jnamaya/SAFi/discussions) in the *Ideas* category. Describe the use case, not just the feature.

### Code Contributions

1. **Fork** the repo and create a branch from `dev` (not `main`):
   ```bash
   git checkout dev
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes.** Key areas:
   - **New MCP tool:** `safi_app/core/mcp_servers/` + register in `mcp_manager.py`
   - **New faculty behavior:** `safi_app/core/faculties/`
   - **New agent persona:** `safi_app/core/synderesis.py`
   - **Frontend:** `public/` (rebuild CSS after Tailwind changes: see README)

3. **Test your changes** against the live app before submitting.

4. **Open a Pull Request** against `dev` with a clear description of what changed and why.

### Documentation
Documentation improvements are always welcome. The `docs/` directory holds architecture specs and philosophy notes. The main `README.md` is the public face of the project.

## Architecture Principles to Respect

All contributions should preserve:

- **The Air Gap:** The Intellect must never directly execute tools. All execution goes through the Will gate.
- **Zero-LLM Will:** The `will.py` gatekeeper must remain pure deterministic Python. No LLM calls, ever.
- **Faculty Separation:** Each faculty has a single, well-defined role. Don't add governance logic to the Intellect or generative logic to the Conscience.

## Code Style

- Python: follow existing conventions in the codebase (PEP 8, async/await for I/O)
- No new dependencies without discussion in an Issue first
- Keep faculty modules focused -- if a change touches more than two faculties, open a discussion first

## Questions

Open a [GitHub Discussion](https://github.com/jnamaya/SAFi/discussions) or reach out to the author via the links in the README.
