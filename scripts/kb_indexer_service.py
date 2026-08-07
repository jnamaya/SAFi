#!/usr/bin/env python3
"""Knowledge-base indexer service (SERVICE=indexer).

Polls for knowledge bases queued for rebuild and builds their FAISS index from
the APPROVED document subset. Runs as its own container from the same image as
`app`, exactly as the retention purge scheduler does.

Why a service and not a request handler: embedding a large corpus takes tens
of seconds, gunicorn runs `--timeout 120`, and a rebuild triggered by an
approval must not block the approver's HTTP response.

Bare-metal deployments should run this under a systemd unit alongside the
retention timer in deploy/systemd/.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - kb-indexer - %(message)s",
)


def main():
    from safi_app.core.services.kb_indexer import run_indexer_loop

    poll = int(os.environ.get("SAFI_KB_INDEXER_POLL_SECONDS", "5"))
    run_indexer_loop(poll_seconds=poll)


if __name__ == "__main__":
    main()
