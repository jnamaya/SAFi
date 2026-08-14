"""
Storage for MCP servers installed through the GUI (GOVERNANCE_BACKLOG 48).

WHY THIS IS NOT IN database.py
------------------------------
`database.py` is in the integrity manifest, and the comment in
verify_integrity.py says exactly why: it creates the hash-chained audit ledgers
and the temporal logs, so "modifying how the system records its actions is a
Core Loop change even though the CONTENT of the database belongs to the
organization (Section III)".

A list of which tool servers an organization installed is that content. It is
configuration an org owns, not a record of what the system decided, and adding
it to the covered file would put an ordinary product feature behind Section IV
review for no governance gain. This module therefore owns its own two tables and
borrows nothing from database.py except the connection pool and the compliance
log, both of which it CALLS and neither of which it changes.

That reasoning is the same line item 41 draws for engine adapters. If the repo
owner disagrees, the fix is to move these two DDL blocks into database.py and
regenerate the manifest; nothing else here changes.

WHAT IS AND IS NOT STORED HERE
------------------------------
Stored: the endpoint, the registry identity it came from, the exact pinned
version, who installed it, who approved it. All of it inspectable, none of it
secret.

Not stored: credentials. A GUI-installed server is remote and its URL is the
whole address. Anything needing a secret belongs in the operator's file, where
`${VAR}` reads it from the environment.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from . import database as db

log = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
STATUS_DISABLED = "disabled"


def init_schema() -> None:
    """Create the tables if absent. Called once at boot, after db.init_db()."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS org_mcp_servers (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL,
                connector_key VARCHAR(64) NOT NULL,
                registry_name VARCHAR(255) NOT NULL,
                registry_version VARCHAR(64) DEFAULT NULL,
                title VARCHAR(255) DEFAULT NULL,
                description TEXT DEFAULT NULL,
                transport VARCHAR(32) NOT NULL DEFAULT 'http',
                url TEXT NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                installed_by VARCHAR(36) DEFAULT NULL,
                installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by VARCHAR(36) DEFAULT NULL,
                reviewed_at TIMESTAMP NULL DEFAULT NULL,
                review_note TEXT DEFAULT NULL,
                independent_review TINYINT(1) NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                -- Deployment-wide, not per org: a connector name is a global
                -- string in every agent's tools_json, so two orgs pointing the
                -- same name at different endpoints would make one agent's
                -- authorized tool mean two different servers.
                UNIQUE KEY uniq_connector_key (connector_key),
                KEY idx_org_status (org_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
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


def _bump_generation(cursor) -> None:
    """Tell every worker its view is stale.

    Four gunicorn workers each hold their own MCP sessions, and an install has
    to reach all of them without a restart. A counter they can read for the cost
    of one indexed row beats any IPC we would otherwise invent.
    """
    cursor.execute("UPDATE mcp_runtime_state SET generation = generation + 1 WHERE id = 1")


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


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("installed_at", "reviewed_at", "updated_at"):
        if out.get(key) is not None:
            out[key] = db.utc_isoformat(out[key]) if hasattr(db, "utc_isoformat") else str(out[key])
    out["independent_review"] = bool(out.get("independent_review", 1))
    return out


def list_servers(org_id: str, statuses: Optional[tuple] = None) -> List[Dict[str, Any]]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM org_mcp_servers WHERE org_id = %s"
        params: List[Any] = [org_id]
        if statuses:
            sql += f" AND status IN ({','.join(['%s'] * len(statuses))})"
            params.extend(statuses)
        sql += " ORDER BY installed_at DESC"
        cursor.execute(sql, tuple(params))
        return [_row_to_dict(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def list_active_everywhere() -> List[Dict[str, Any]]:
    """Every approved server across all orgs.

    The runtime is process-wide and holds one session per endpoint, so it
    connects the union. Which ORG may use a connector is decided a rung up, by
    the connector allow-list, exactly as it is for the built-ins.
    """
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM org_mcp_servers WHERE status = %s ORDER BY connector_key",
            (STATUS_ACTIVE,),
        )
        return [_row_to_dict(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def get_server(server_id: str) -> Optional[Dict[str, Any]]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM org_mcp_servers WHERE id = %s", (server_id,))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        cursor.close()
        conn.close()


def connector_key_taken(connector_key: str) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM org_mcp_servers WHERE connector_key = %s LIMIT 1", (connector_key,)
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def install(org_id: str, actor_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Record a pending install. Never activates: approval is a separate act."""
    server_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO org_mcp_servers
               (id, org_id, connector_key, registry_name, registry_version, title,
                description, transport, url, status, installed_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                server_id, org_id, entry["connector_key"], entry["registry_name"],
                entry.get("registry_version"), entry.get("title"),
                entry.get("description"), entry.get("transport", "http"),
                entry["url"], STATUS_PENDING, actor_id,
            ),
        )
        db.append_compliance_log(
            org_id, "mcp_server_installed", f"user:{actor_id}",
            {
                "connector_key": entry["connector_key"],
                "registry_name": entry["registry_name"],
                "registry_version": entry.get("registry_version"),
                "url": entry["url"],
                "status": STATUS_PENDING,
            },
            cursor=cursor,
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_server(server_id)


def set_status(
    server_id: str,
    status: str,
    actor_id: str,
    org_id: str,
    note: str = "",
    independent: bool = True,
) -> Optional[Dict[str, Any]]:
    """Approve, reject, disable or re-enable. Bumps the generation."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """UPDATE org_mcp_servers
               SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                   review_note = %s, independent_review = %s
               WHERE id = %s AND org_id = %s""",
            (status, actor_id, note or None, 1 if independent else 0, server_id, org_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return None
        _bump_generation(cursor)
        db.append_compliance_log(
            org_id,
            f"mcp_server_{status}",
            f"user:{actor_id}",
            {"server_id": server_id, "note": note or None, "independent_review": independent},
            cursor=cursor,
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_server(server_id)


def delete(server_id: str, org_id: str, actor_id: str) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM org_mcp_servers WHERE id = %s AND org_id = %s", (server_id, org_id)
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return False
        _bump_generation(cursor)
        db.append_compliance_log(
            org_id, "mcp_server_removed", f"user:{actor_id}", {"server_id": server_id},
            cursor=cursor,
        )
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()
