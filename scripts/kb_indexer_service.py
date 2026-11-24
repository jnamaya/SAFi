#!/usr/bin/env python3
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
