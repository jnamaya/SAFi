"""
SCIM 2.0 directory-sync state (backlog 68).

Userland persistence for automated provisioning/deprovisioning. It holds the
IdP-facing resource state (the /Users and /Groups an identity provider pushes),
the per-org bearer token, and the group->role map. It does NOT change SAFi
membership itself: the API layer applies changes by calling the existing
member/invitation functions, so this module stays pure persistence and the
governance-bearing membership logic keeps living where it already does.

Deliberately outside the manifest-covered database.py: who is provisioned from
a directory is Section III org configuration, the same class as sharing_store
and tool_approval_store, not the governance ledger.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from typing import Any, Dict, List, Optional

from . import database as db
from .sharing_store import _target_collation

# Role precedence for resolving a user's effective role from mapped groups.
# admin outranks all; member is the floor.
ROLE_RANK = {"member": 0, "auditor": 1, "editor": 2, "admin": 3}
VALID_ROLES = set(ROLE_RANK)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_schema() -> None:
    """Create the SCIM tables if absent, collation-matched to the legacy schema
    (same lesson as the other userland stores: a bare charset takes the server
    default and breaks joins/uniqueness against existing tables)."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        coll = _target_collation(cursor)
        charset = coll.split("_")[0]
        opts = f"ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}"

        # Per-org SCIM config: the bearer token (hashed) and an enable flag.
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS scim_config (
                org_id CHAR(36) PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                token_hash CHAR(64) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_scim_token (token_hash)
            ) {opts}
        """)

        # IdP-facing user resources. email is the reconciliation key with SSO
        # (login accepts invitations by email); scim_id is what the IdP sees.
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS scim_resources (
                scim_id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                external_id VARCHAR(255) NULL,
                email VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                base_role VARCHAR(20) NOT NULL DEFAULT 'member',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_scim_res_email (org_id, email),
                INDEX idx_scim_res_org (org_id)
            ) {opts}
        """)

        # IdP-facing groups. members is a JSON array of scim resource ids.
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS scim_groups (
                scim_id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                external_id VARCHAR(255) NULL,
                display_name VARCHAR(255) NOT NULL,
                members JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_scim_grp_org (org_id)
            ) {opts}
        """)

        # Admin-configured: SCIM group displayName -> SAFi role.
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS scim_group_role_map (
                org_id CHAR(36) NOT NULL,
                group_name VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL,
                PRIMARY KEY (org_id, group_name)
            ) {opts}
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# --- config / token ----------------------------------------------------------

def get_config(org_id) -> Dict[str, Any]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT org_id, enabled, token_hash, updated_at FROM scim_config WHERE org_id=%s", (org_id,))
        row = cursor.fetchone()
        if not row:
            return {"org_id": org_id, "enabled": False, "has_token": False, "updated_at": None}
        return {
            "org_id": row["org_id"],
            "enabled": bool(row["enabled"]),
            "has_token": bool(row["token_hash"]),
            "updated_at": row["updated_at"],
        }
    finally:
        cursor.close()
        conn.close()


def set_enabled(org_id, enabled: bool) -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scim_config (org_id, enabled) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)",
            (org_id, bool(enabled)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def rotate_token(org_id) -> str:
    """Generate a new bearer token, store only its hash, enable SCIM, and
    return the plaintext ONCE. Any previous token stops working immediately."""
    token = "scim_" + secrets.token_urlsafe(32)
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scim_config (org_id, enabled, token_hash) VALUES (%s, TRUE, %s) "
            "ON DUPLICATE KEY UPDATE token_hash=VALUES(token_hash), enabled=TRUE",
            (org_id, _hash_token(token)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return token


def resolve_org_by_token(token: str) -> Optional[str]:
    """The org a bearer token authenticates, or None. Only enabled configs
    match, so disabling SCIM instantly closes the endpoint."""
    if not token:
        return None
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT org_id FROM scim_config WHERE token_hash=%s AND enabled=TRUE",
            (_hash_token(token),),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        conn.close()


# --- user resources ----------------------------------------------------------

def _res_row(cursor) -> Optional[dict]:
    row = cursor.fetchone()
    return row


def create_resource(org_id, email, external_id, display_name, active, base_role) -> dict:
    scim_id = str(uuid.uuid4())
    email = (email or "").strip().lower()
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scim_resources (scim_id, org_id, external_id, email, display_name, active, base_role) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (scim_id, org_id, external_id, email, display_name, bool(active), base_role),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_resource(org_id, scim_id)


def get_resource(org_id, scim_id) -> Optional[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM scim_resources WHERE org_id=%s AND scim_id=%s", (org_id, scim_id))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def get_resource_by_email(org_id, email) -> Optional[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM scim_resources WHERE org_id=%s AND email=%s",
                       (org_id, (email or "").strip().lower()))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def list_resources(org_id, email_filter=None) -> List[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if email_filter:
            cursor.execute(
                "SELECT * FROM scim_resources WHERE org_id=%s AND email=%s ORDER BY created_at",
                (org_id, email_filter.strip().lower()))
        else:
            cursor.execute("SELECT * FROM scim_resources WHERE org_id=%s ORDER BY created_at", (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def update_resource(org_id, scim_id, *, active=None, display_name=None,
                    base_role=None, external_id=None) -> Optional[dict]:
    sets, params = [], []
    if active is not None:
        sets.append("active=%s"); params.append(bool(active))
    if display_name is not None:
        sets.append("display_name=%s"); params.append(display_name)
    if base_role is not None:
        sets.append("base_role=%s"); params.append(base_role)
    if external_id is not None:
        sets.append("external_id=%s"); params.append(external_id)
    if not sets:
        return get_resource(org_id, scim_id)
    params += [org_id, scim_id]
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE scim_resources SET {', '.join(sets)} WHERE org_id=%s AND scim_id=%s", params)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_resource(org_id, scim_id)


def delete_resource(org_id, scim_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM scim_resources WHERE org_id=%s AND scim_id=%s", (org_id, scim_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


# --- groups ------------------------------------------------------------------

def create_group(org_id, display_name, external_id, member_ids) -> dict:
    scim_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scim_groups (scim_id, org_id, external_id, display_name, members) "
            "VALUES (%s, %s, %s, %s, %s)",
            (scim_id, org_id, external_id, display_name, json.dumps(list(member_ids or []))),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_group(org_id, scim_id)


def get_group(org_id, scim_id) -> Optional[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM scim_groups WHERE org_id=%s AND scim_id=%s", (org_id, scim_id))
        row = cursor.fetchone()
        if row:
            row["members"] = json.loads(row["members"]) if isinstance(row["members"], str) else (row["members"] or [])
        return row
    finally:
        cursor.close()
        conn.close()


def list_groups(org_id) -> List[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM scim_groups WHERE org_id=%s ORDER BY created_at", (org_id,))
        rows = cursor.fetchall()
        for r in rows:
            r["members"] = json.loads(r["members"]) if isinstance(r["members"], str) else (r["members"] or [])
        return rows
    finally:
        cursor.close()
        conn.close()


def set_group_members(org_id, scim_id, member_ids, display_name=None) -> Optional[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        if display_name is not None:
            cursor.execute(
                "UPDATE scim_groups SET members=%s, display_name=%s WHERE org_id=%s AND scim_id=%s",
                (json.dumps(list(member_ids)), display_name, org_id, scim_id))
        else:
            cursor.execute(
                "UPDATE scim_groups SET members=%s WHERE org_id=%s AND scim_id=%s",
                (json.dumps(list(member_ids)), org_id, scim_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_group(org_id, scim_id)


def delete_group(org_id, scim_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM scim_groups WHERE org_id=%s AND scim_id=%s", (org_id, scim_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


# --- group -> role map + effective role --------------------------------------

def list_group_role_map(org_id) -> List[dict]:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT group_name, role FROM scim_group_role_map WHERE org_id=%s ORDER BY group_name", (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def set_group_role(org_id, group_name, role) -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scim_group_role_map (org_id, group_name, role) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE role=VALUES(role)",
            (org_id, group_name, role))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def delete_group_role(org_id, group_name) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM scim_group_role_map WHERE org_id=%s AND group_name=%s", (org_id, group_name))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def effective_role(org_id, scim_id, base_role="member") -> str:
    """Highest-privilege role among the mapped groups this resource belongs to,
    falling back to its base role. Pure computation over stored state."""
    mapping = {m["group_name"]: m["role"] for m in list_group_role_map(org_id)}
    best = base_role if base_role in ROLE_RANK else "member"
    for g in list_groups(org_id):
        if scim_id in (g.get("members") or []):
            role = mapping.get(g["display_name"])
            if role and ROLE_RANK.get(role, 0) > ROLE_RANK.get(best, 0):
                best = role
    return best
