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
# docker-compose sets SERVICE=dashboard for the dashboard container.
if [ "${SERVICE}" = "dashboard" ]; then
    exec streamlit run safi_app/dashboard/safi_dashboard.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true \
        --browser.gatherUsageStats=false
else
    exec gunicorn wsgi:app \
        --bind 0.0.0.0:5000 \
        --workers 4 \
        --threads 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
