# The interpreter version, in one place. Defaults to the version the appliance
# image ships (trixie → 3.13), so nothing changes unless a build overrides it:
#   docker build --build-arg PYTHON_VERSION=3.11 .
# The override exists so the test suite can be run against other interpreters
# (a supported-range check) without editing this file.
ARG PYTHON_VERSION=3.13

# ── Stage 1: dependency layer ──────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS deps

WORKDIR /app

# System libraries required for lxml and mysql-connector compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./

# No torch pre-install step any more: embeddings run through ONNX Runtime via
# fastembed, so nothing pulls PyTorch and the CPU-wheel workaround that existed
# to avoid the CUDA build is unnecessary.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock


# ── Stage 2: runtime image ─────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

ENV PATH="/opt/venv/bin:${PATH}"

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

# Copy the version-independent virtualenv from the deps stage. This avoids
# depending on the patch-level directory chosen by the base image (for example
# python3.13.15 rather than python3.13).
COPY --from=deps /opt/venv /opt/venv

# Copy application code
COPY safi_app/ ./safi_app/
COPY public/   ./public/
COPY scripts/  ./scripts/
COPY integrations/ ./integrations/
COPY rag/      ./rag/
COPY wsgi.py   .

# Create persistent data directories and unprivileged application user
RUN useradd -u 10001 -m -d /home/safi -s /bin/bash safi \
    && mkdir -p logs cache vector_store gateway-data /home/safi/.cache \
    && chown -R safi:safi /app /home/safi

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Main app port (Flask/gunicorn)
EXPOSE 5000
# Dashboard port (Streamlit)
EXPOSE 8501

USER safi

ENTRYPOINT ["/entrypoint.sh"]
