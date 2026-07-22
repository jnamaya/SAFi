# ── Stage 1: dependency layer ──────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# System libraries required for lxml and mysql-connector compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install torch CPU-only first (avoids pulling the full CUDA build via sentence-transformers)
RUN pip install --no-cache-dir \
        torch \
        --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ─────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

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
