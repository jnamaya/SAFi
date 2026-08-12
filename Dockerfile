# ── Stage 1: dependency layer ──────────────────────────────────────────────────
FROM python:3.11-slim AS deps

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
FROM python:3.11-slim

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
