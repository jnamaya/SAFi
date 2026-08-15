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
        # OAuth clients this deployment registered with an IdP (RFC 7591), one
        # per server. Deployment configuration, not audit: same boundary
        # reasoning as the rest of this module. The secret is encrypted with
        # the application key like every other stored credential.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
                server_key VARCHAR(64) PRIMARY KEY,
                issuer VARCHAR(512) NOT NULL,
                client_id VARCHAR(512) NOT NULL,
                client_secret TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Tool catalogs for OAuth-protected servers. Discovery needs a token,
        # so the list is captured when a user first connects and served from
        # here after that: without this cache an authed server would show an
        # empty catalog to every admin who had not personally signed in.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_cached_tools (
                server_key VARCHAR(64) NOT NULL,
                tool_name VARCHAR(255) NOT NULL,
                description TEXT,
                input_schema JSON,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_key, tool_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
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


# ── OAuth client registrations (mcp_oauth.py) ─────────────────────────────────

def save_oauth_client(server_key: str, issuer: str, client_id: str,
                      client_secret: str = "") -> None:
    from . import crypto
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO mcp_oauth_clients (server_key, issuer, client_id, client_secret)
               VALUES (%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE issuer=VALUES(issuer),
                   client_id=VALUES(client_id), client_secret=VALUES(client_secret)""",
            (server_key, issuer, client_id,
             crypto.encrypt_value(client_secret) if client_secret else None),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_oauth_client(server_key: str):
    from . import crypto
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM mcp_oauth_clients WHERE server_key=%s", (server_key,))
        row = cursor.fetchone()
        if row and row.get("client_secret"):
            try:
                row["client_secret"] = crypto.decrypt_value(row["client_secret"])
            except Exception:
                row["client_secret"] = ""
        return row
    finally:
        cursor.close()
        conn.close()


# ── Cached tool catalogs for OAuth-protected servers ─────────────────────────

def replace_cached_tools(server_key: str, tools) -> None:
    """`tools` is [{name, description, input_schema}]. Full replacement: the
    catalog is whatever the server said last time someone connected."""
    import json as _json
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM mcp_cached_tools WHERE server_key=%s", (server_key,))
        for tool in tools:
            cursor.execute(
                """INSERT INTO mcp_cached_tools (server_key, tool_name, description, input_schema)
                   VALUES (%s,%s,%s,%s)""",
                (server_key, tool["name"], tool.get("description") or "",
                 _json.dumps(tool.get("input_schema") or {})),
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def list_cached_tools(server_key: str):
    import json as _json
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT tool_name, description, input_schema FROM mcp_cached_tools "
            "WHERE server_key=%s ORDER BY tool_name", (server_key,))
        out = []
        for row in cursor.fetchall():
            schema = row.get("input_schema")
            if isinstance(schema, str):
                try:
                    schema = _json.loads(schema)
                except ValueError:
                    schema = {}
            out.append({"name": row["tool_name"],
                        "description": row.get("description") or "",
                        "input_schema": schema or {}})
        return out
    finally:
        cursor.close()
        conn.close()
