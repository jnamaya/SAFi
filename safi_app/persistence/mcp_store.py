from __future__ import annotations

import logging

from . import database as db

log = logging.getLogger(__name__)


def init_schema() -> None:
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
                server_key VARCHAR(64) PRIMARY KEY,
                issuer VARCHAR(512) NOT NULL,
                client_id VARCHAR(512) NOT NULL,
                client_secret TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
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


def replace_cached_tools(server_key: str, tools) -> None:
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
