# The interpreter version, in one place. Defaults to the version the image has
# always shipped, so nothing changes unless a build overrides it:
#   docker build --build-arg PYTHON_VERSION=3.13 .
# The override exists so the test suite can be run against other interpreters
# (a supported-range check) without editing this file.
ARG PYTHON_VERSION=3.11

# ── Stage 1: dependency layer ──────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS deps

WORKDIR /app

# System libraries required for lxml and mysql-connector compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# No torch pre-install step any more: embeddings run through ONNX Runtime via
# fastembed, so nothing pulls PyTorch and the CPU-wheel workaround that existed
# to avoid the CUDA build is unnecessary.
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ─────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# OCR for image attachments and scanned PDFs. Must be in the RUNTIME stage, not
# the deps stage: pytesseract is only a wrapper that shells out to the tesseract
# binary, so the wheel installs cleanly and then fails at call time if the binary
# is absent. `--no-install-recommends` keeps this to ~45 MB; without it apt pulls
# in every language pack.
#
# tesseract-ocr-eng is explicit rather than implied — the base package ships no
# language data, and tesseract exits with "Failed loading language 'eng'" when it
# is missing, which reads like a code bug rather than a packaging one.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Node, so `npx` MCP tool servers can run (GOVERNANCE_BACKLOG 48b). Most of the
# MCP ecosystem ships as npm packages; without a Node runtime the CLI has to
# refuse them, which left the reliable majority of servers unusable.
#
# Copied from the official image rather than installed with apt. Debian's
# `nodejs` is 18.x and pulls a long recommends chain, while node:22-slim is
# built on the same bookworm base as python:3.11-slim, so the binary and its
# glibc match and this is a file copy with no package manager involved. npm
# itself is plain JavaScript under node_modules; the two shims are the entry
# points npm's own installer would create.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    # npm's own docs and man pages, and corepack (the yarn/pnpm shim), are not
    # reachable from anything this image does. Small next to the 120 MB node
    # binary, which is the real and irreducible cost of running npm servers.
    && rm -rf /usr/local/lib/node_modules/npm/docs \
              /usr/local/lib/node_modules/npm/man \
              /usr/local/lib/node_modules/corepack \
    && node --version && npx --version

# NOTE: npm's cache location is NOT set here, and cannot usefully be. The MCP
# SDK gives a stdio server only an allow-list of environment variables
# (get_default_environment), so NPM_CONFIG_CACHE set on this image never reaches
# npx. HOME is on that list, so the cache lands in /root/.npm, which
# docker-compose persists as a named volume. Without that volume every container
# start re-downloads every npm tool server before it can answer.

# Copy installed packages from the deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY safi_app/ ./safi_app/
COPY public/   ./public/
COPY scripts/  ./scripts/
COPY rag/      ./rag/
COPY wsgi.py   .

# Create persistent data directories (overridden by docker-compose volumes)
RUN mkdir -p logs cache vector_store

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Main app port (Flask/gunicorn)
EXPOSE 5000
# Dashboard port (Streamlit)
EXPOSE 8501

ENTRYPOINT ["/entrypoint.sh"]
