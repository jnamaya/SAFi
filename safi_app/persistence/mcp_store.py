"""
The MCP reload signal (GOVERNANCE_BACKLOG 48b, reduced by 48d).

WHAT IS LEFT HERE, AND WHAT WENT
--------------------------------
This module used to hold `org_mcp_servers`: per-organization records of servers
installed through the browser, with an approval workflow and a tenancy story.
All of it was removed when installation moved to the CLI. With every server
coming from the operator's file, a server is a property of the deployment again,
exactly like a built-in connector, and the table had nothing left to record.

What remains is one counter, because the problem it solves did not go away: four
gunicorn workers each hold their own MCP sessions, and a CLI edit on the host has
to reach all of them without a restart. Each worker reads this number on its next
request and re-reads the file when it has moved. One indexed row beats any IPC we
would otherwise have to build and then operate.

WHY IT IS NOT IN database.py
----------------------------
Same reasoning as before: `database.py` is manifest-covered because it creates
the hash-chained audit ledgers, and a reload counter is not a record of what the
system decided. It is a scheduling detail.

NOTE ON THE OLD TABLE: `org_mcp_servers` is no longer created or read. Existing
deployments keep an empty table until a migration drops it; nothing writes to it,
and leaving it costs nothing but a line in a schema dump.
"""
from __future__ import annotations

import logging

from . import database as db

log = logging.getLogger(__name__)


def init_schema() -> None:
    """Create the counter if absent. Called once at boot, after db.init_db()."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_runtime_state (
                id TINYINT PRIMARY KEY,
                generation BIGINT NOT NULL DEFAULT 1
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute(
            "INSERT IGNORE INTO mcp_runtime_state (id, generation) VALUES (1, 1)"
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def bump_generation() -> bool:
    """Tell every worker its view of the server file is stale.

    Returns False when the signal could not be sent, so the caller can say a
    restart is needed rather than implying the change is live.
    """
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE mcp_runtime_state SET generation = generation + 1 WHERE id = 1"
            )
            conn.commit()
            return True
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        log.warning("could not bump the MCP generation: %s", e)
        return False


def current_generation() -> int:
    """Cheap enough to call on the request path. Returns 0 on any failure, which
    reads as "do not resync" rather than "resync constantly"."""
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT generation FROM mcp_runtime_state WHERE id = 1")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        log.debug("mcp generation check failed: %s", e)
        return 0
