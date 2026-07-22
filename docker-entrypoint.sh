#!/bin/bash
set -e

# Wait for MySQL to accept connections before starting the app.
# Uses the python client so no extra tools are required in the image.
if [ -n "$DB_HOST" ] && [ "$DB_HOST" != "localhost" ]; then
    echo "Waiting for MySQL at $DB_HOST..."
    until python - <<EOF
import sys, mysql.connector
try:
    mysql.connector.connect(
        host="$DB_HOST",
        user="${DB_USER:-safi}",
        password="${DB_PASSWORD}",
        database="${DB_NAME:-safi}"
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
EOF
    do
        sleep 2
    done
    echo "MySQL is ready."
fi

# SERVICE env var selects which process to start.
# docker-compose sets SERVICE=purge for the retention-purge scheduler.
if [ "${SERVICE}" = "purge" ]; then
    echo "Retention purge scheduler: first run in 5 minutes, then every 24h."
    sleep 300   # let the app finish first-boot schema migrations
    while true; do
        python scripts/retention_purge.py || echo "retention purge failed; retrying in 24h"
        sleep 86400
    done
else
    # First-boot RAG bootstrap: build the small `safi` knowledge base (used by
    # the SAFi Steward agent) if it's missing. The embedding model download
    # lands in the mounted ./cache volume, so this only costs time once.
    # Set SAFI_SKIP_INDEX_BOOTSTRAP=true to disable.
    if [ "${SAFI_SKIP_INDEX_BOOTSTRAP}" != "true" ] \
        && [ ! -f vector_store/safi.index ] && [ -d rag/docs ]; then
        echo "Building the 'safi' RAG index (first boot only)..."
        SAFI_VECTOR_STORE_PATH=/app/vector_store SAFI_MODEL_CACHE_DIR=/app/cache \
            python rag/build_index_v2.py --name safi --source_dir rag/docs \
            || echo "WARNING: safi index build failed — the SAFi Steward agent will answer without RAG."
    fi

    exec gunicorn wsgi:app \
        --bind 0.0.0.0:5000 \
        --workers 4 \
        --threads 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
