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
    # First-boot RAG bootstrap for the SAFi Steward's knowledge base.
    #
    # Guards on BOTH artifacts, not just the index. They live in different
    # places with different lifetimes: the index is in the `vector_store` NAMED
    # VOLUME (survives `compose down`, image rebuilds, even deleting the repo)
    # while the embedding model is in ./cache, a BIND MOUNT that only survives
    # if the host directory does. Rebuild a host and the index persists while
    # the model vanishes — the old index-only check then skipped this block,
    # and the model got downloaded inside the first user request instead:
    # under a lock, behind gunicorn's --timeout, with the browser spinning and
    # nothing in the logs to explain it.
    if [ "${SAFI_SKIP_INDEX_BOOTSTRAP}" != "true" ] && [ -d rag/docs ]; then
        export SAFI_VECTOR_STORE_PATH=/app/vector_store SAFI_MODEL_CACHE_DIR=/app/cache

        if [ ! -f vector_store/safi.index ]; then
            echo "Building the 'safi' RAG index (first boot only)..."
            python rag/build_index_v2.py --name safi --source_dir rag/docs \
                || echo "WARNING: safi index build failed — the SAFi Steward agent will answer without RAG."
        fi

        # Warm the embedding model even when the index already exists. Cheap and
        # idempotent once cached; the alternative is paying for it in a request.
        python - <<'WARM' || echo "WARNING: embedding model warm-up failed — the first Steward query will be slow."
import os
from safi_app.core.services.retriever import get_shared_embedding_model, EMBEDDING_MODEL
get_shared_embedding_model()
print(f"Embedding model ready: {EMBEDDING_MODEL}")
WARM
    fi

    exec gunicorn wsgi:app \
        --bind 0.0.0.0:5000 \
        --workers 4 \
        --threads 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
