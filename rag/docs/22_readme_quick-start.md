---
title: SAFi README: Quick Start
slug: readme-quick-start
tags: ["safi", "readme", "safi"]
summary: The fastest way to run SAFi locally. Includes MySQL.
version: 1.0
---

# SAFi README: Quick Start

The fastest way to run SAFi locally. Includes MySQL. No external database needed.

```bash
# 1. Clone and enter the repo
git clone https://github.com/jnamaya/SAFi.git
cd SAFi

# 2. Configure your environment
cp .env.example .env
# Open .env and set:
#   DB_PASSWORD + MYSQL_ROOT_PASSWORD  (choose anything)
#   At least one LLM API key (GROQ_API_KEY is free and fast to get)

# 3. Start everything
docker compose up

# Open http://localhost:5000
```

> **Requirements:** Docker, and roughly **8 GB of free disk** — about 3 GB for
> the images (SAFi ~1.3 GB, MySQL ~1.1 GB) and the rest as headroom for the
> build, the database, and Docker's layer cache. On a fresh VM, check
> `df -h` first: Ubuntu Server's installer often allocates only part of the
> disk to the root volume, and `sudo vgs` will show whether there is
> unallocated space you can claim with `lvextend`.
>
> **Reaching it from another machine?** Set `WEB_BASE_URL` in `.env` to the
> address you'll actually browse to — for example
> `WEB_BASE_URL=http://192.168.1.50:5000`. It defaults to a localhost URL, and
> leaving it wrong breaks OAuth callbacks and cross-origin requests.

#### Prefer a prebuilt image?

`docker compose up` builds from source, which is the default and stays
supported. Released versions are also published to GitHub Container Registry:

```bash
docker pull ghcr.io/jnamaya/safi:latest      # newest release
docker pull ghcr.io/jnamaya/safi:0.1.0       # a specific version
```

Note the image tag has no `v` prefix — the git tag `v0.1.0` publishes as
`0.1.0`, following container convention.

#### Not using containers?

See **[Bare-metal deployment](docs/DEPLOY_BAREMETAL.md)** for systemd, a system
MySQL, a virtualenv and a reverse proxy — the way the public demo runs. It also
covers the things Docker handles for you that bare metal does not, including
warming the embedding model and running the retention-purge timer.

Every release carries **SLSA provenance, an SBOM, and a keyless cosign
signature**, so you can verify the image was built from the tagged source
rather than taking our word for it:

```bash
cosign verify ghcr.io/jnamaya/safi:latest \
  --certificate-identity-regexp 'https://github.com/jnamaya/SAFi/.github/workflows/release.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

For production, pin by digest (`ghcr.io/jnamaya/safi@sha256:…`) rather than by
tag — that is what makes "which version is running?" answerable during an
audit.

> **Tip:** [Groq](https://console.groq.com) offers a generous free tier -- it's the easiest way to get a working API key in under 2 minutes. SAFi also supports `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`, and `ZHIPU_API_KEY` — whichever key you set, SAFi automatically selects working default models for that provider. Once you're familiar with the system, pin specific models with the `SAFI_*_MODEL` variables in [`.env.example`](.env.example).

A fresh install starts with three built-in agents, all of which run with no extra setup:

- **The Fiduciary** (the default) — a regulated-domain agent that answers general financial questions but declines to give personalised advice. Ask it *"I earn $75,000 a year, how much house can I afford?"* and watch the Will redirect it, then open the conscience ledger to see why. This is the agent the [domain compliance benchmark](#2-domain-compliance-benchmark) below measures.
- **The Socratic Tutor** — never gives a direct answer, so the policy is visible in every response, not only in violations.
- **The SAFi Steward** — answers questions about SAFi itself from a small knowledge base that builds automatically on first boot.

Two more demo agents ship in the codebase: **Health Navigator** (no knowledge base — enable and use immediately) and **Bible Scholar**, the only one that needs a RAG index built first (see `rag/build_index_v2.py`). Enable either with `SAFI_BUILTIN_AGENTS` in `.env`, or `=all` for the full suite.

#### Local Admin Account (No OAuth Required)

For private or self-hosted instances, you can skip Google/Microsoft OAuth entirely by creating a persistent local admin account. Add these two lines to your `.env` before starting:

```env
SAFI_LOCAL_ADMIN_EMAIL=admin@localhost
SAFI_LOCAL_ADMIN_PASSWORD=yourpassword
```

SAFi will create the account automatically on first startup. The login form appears on the login page alongside the OAuth buttons.

---
