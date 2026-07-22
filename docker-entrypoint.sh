#!/bin/bash
set -e

# Wait for MySQL to accept connections before starting the app.
# Uses the python client so no extra tools are required in the image.
# Prints the real connection error and fails fast instead of retrying
# forever, so credential problems (e.g. a db volume initialized with an
# older DB_PASSWORD) are visible instead of hanging the install.
if [ -n "$DB_HOST" ] && [ "$DB_HOST" != "localhost" ]; then
    echo "Waiting for MySQL at $DB_HOST..."
    attempts=0
    max_attempts=30
    until error=$(python - <<EOF 2>&1
import sys, mysql.connector
try:
    mysql.connector.connect(
        host="$DB_HOST",
        user="${DB_USER:-safi}",
        password="${DB_PASSWORD}",
        database="${DB_NAME:-safi}"
    )
    sys.exit(0)
except Exception as e:
    print(f"{type(e).__name__}: {e}")
    sys.exit(1)
EOF
    )
    do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge "$max_attempts" ]; then
            echo "ERROR: could not connect to MySQL at $DB_HOST after $attempts attempts."
            echo "Last error: $error"
            case "$error" in
                *"Access denied"*|*"Unknown database"*)
                    echo ""
                    echo "This usually means the database volume was initialized with"
                    echo "different credentials than the current .env. MySQL only applies"
                    echo "DB_PASSWORD/DB_NAME on the volume's FIRST boot. To start fresh:"
                    echo ""
                    echo "    docker compose down -v"
                    echo ""
                    echo "(This deletes the local database volume.)"
                    ;;
            esac
            exit 1
        fi
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
