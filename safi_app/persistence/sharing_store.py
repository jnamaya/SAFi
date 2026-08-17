"""
Scoped agent sharing (backlog 55): custom groups and per-agent grants.

An agent's `visibility` column is a role ladder: it answers "which RANKS in my
org may use this". It cannot answer "these three people and the Finance team".
This module adds that second answer as pure widening: a grant can only ADD
access on top of what the ladder already allows, never remove any.

WHY IT IS NOT IN database.py
----------------------------
database.py is manifest-covered because it creates the hash-chained audit
ledgers. Who may use which agent inside an organization is Section III org
configuration, the same tier as conversation ownership and knowledge-base
visibility, both of which already live outside the manifest. Same boundary
reasoning as mcp_store.py.

THE RESOLVER
------------
can_use_agent() is the single authorization answer for agent USE. Every
entry point that resolves an agent_key from user input must call it: the
profile switch, the chat turn, the schedule validator, the scheduled runner.
The ladder used to be enforced on listing only (backlog 55b), which meant a
private agent was hidden but not protected. Order of checks: owner, then
org admin, then the ladder, then grants; anything else is denied.

Grants are org-scoped at write time (the grant row carries the agent's
org_id) and re-checked org-scoped at read time, so a grant can never leak an
agent across organizations even if rows are tampered with directly.
"""
from __future__ import annotations

import logging
import uuid

from . import database as db

log = logging.getLogger(__name__)

# Mirror of the visibility ladder in db.list_agents. 'private' appears in no
# set on purpose: without a grant, only the owner (and an org admin) clears it.
_LADDER_CLEARS = {
    'admin':   ('member', 'auditor', 'editor', 'admin'),
    'editor':  ('member', 'auditor', 'editor'),
    'auditor': ('member', 'auditor'),
    'member':  ('member',),
}

# v1 grants confer USE only. 'can_edit' is deliberately absent: a grant that
# let a member edit an agent's values or will_rules would override the role
# ladder on governance content, and that is a separate decision (backlog 55).
GRANT_LEVELS = ('can_use',)


def init_schema() -> None:
    """Create the sharing tables if absent. Called once at boot, after
    db.init_db(). No foreign keys (house style); delete paths clean up
    dependent rows explicitly instead."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_groups (
                id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                name VARCHAR(100) NOT NULL,
                owner_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_groups_org (org_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_memberships (
                group_id CHAR(36) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                added_by VARCHAR(255),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id),
                INDEX idx_memberships_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # agent_key matches agents.agent_key (VARCHAR(100) string key, not a
        # UUID). grantee_id is a users.id (VARCHAR(255)) or a custom_groups.id.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_visibility_grants (
                agent_key VARCHAR(100) NOT NULL,
                grantee_type ENUM('user','group') NOT NULL,
                grantee_id VARCHAR(255) NOT NULL,
                permission_level ENUM('can_use') NOT NULL DEFAULT 'can_use',
                org_id CHAR(36) NOT NULL,
                granted_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_key, grantee_type, grantee_id),
                INDEX idx_grants_grantee (grantee_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def can_use_agent(user_id, role, org_id, agent) -> bool:
    """May `user_id` (with `role`, in `org_id`) use this DB agent row?

    Deny by default. Built-in agents never reach this function: they are not
    rows, and callers treat them as platform-wide.
    """
    if not agent or not user_id:
        return False
    if str(agent.get('created_by') or '') == str(user_id):
        return True
    agent_org = agent.get('org_id')
    if not agent_org or not org_id or str(agent_org) != str(org_id):
        return False
    role = role or 'member'
    # Org admins have full authority over the org's agents (rbac.py's role
    # table); they can already edit any of them, so use follows.
    if role == 'admin':
        return True
    if agent.get('visibility') in _LADDER_CLEARS.get(role, ('member',)):
        return True
    key = agent.get('agent_key') or agent.get('key')
    return has_grant(key, user_id, org_id)


def has_grant(agent_key, user_id, org_id) -> bool:
    """True when a can_use grant reaches this user directly or via a group
    they belong to, scoped to `org_id` on both the grant and the group."""
    if not agent_key or not user_id or not org_id:
        return False
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT 1 FROM agent_visibility_grants g
            WHERE g.agent_key = %s AND g.org_id = %s
              AND (
                    (g.grantee_type = 'user' AND g.grantee_id = %s)
                 OR (g.grantee_type = 'group' AND g.grantee_id IN (
                        SELECT m.group_id FROM group_memberships m
                        JOIN custom_groups c ON c.id = m.group_id
                        WHERE m.user_id = %s AND c.org_id = %s))
              )
            LIMIT 1
            """,
            (agent_key, org_id, user_id, user_id, org_id),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def granted_agents(user_id, org_id):
    """Full agent rows this user can use through grants, for the pickers.
    The join re-asserts the org scope so a stray grant row cannot surface a
    foreign org's agent."""
    if not user_id or not org_id:
        return []
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT DISTINCT a.* FROM agents a
            JOIN agent_visibility_grants g
              ON g.agent_key = a.agent_key AND g.org_id = a.org_id
            WHERE a.org_id = %s
              AND (
                    (g.grantee_type = 'user' AND g.grantee_id = %s)
                 OR (g.grantee_type = 'group' AND g.grantee_id IN (
                        SELECT m.group_id FROM group_memberships m
                        JOIN custom_groups c ON c.id = m.group_id
                        WHERE m.user_id = %s AND c.org_id = %s))
              )
            """,
            (org_id, user_id, user_id, org_id),
        )
        rows = cursor.fetchall()
        for row in rows:
            row['key'] = row['agent_key']
        return rows
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

def set_grant(agent_key, grantee_type, grantee_id, org_id, granted_by,
              permission_level='can_use') -> None:
    if permission_level not in GRANT_LEVELS:
        raise ValueError(f"unsupported permission level '{permission_level}'")
    if grantee_type not in ('user', 'group'):
        raise ValueError(f"unsupported grantee type '{grantee_type}'")
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO agent_visibility_grants
                (agent_key, grantee_type, grantee_id, permission_level, org_id, granted_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                permission_level = VALUES(permission_level),
                org_id = VALUES(org_id),
                granted_by = VALUES(granted_by)
            """,
            (agent_key, grantee_type, grantee_id, permission_level, org_id, granted_by),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def revoke_grant(agent_key, grantee_type, grantee_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM agent_visibility_grants "
            "WHERE agent_key=%s AND grantee_type=%s AND grantee_id=%s",
            (agent_key, grantee_type, grantee_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def list_grants(agent_key):
    """Grants on one agent, with display names resolved for the dialog."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT g.agent_key, g.grantee_type, g.grantee_id,
                   g.permission_level, g.granted_by, g.created_at,
                   CASE g.grantee_type
                       WHEN 'user' THEN (SELECT u.name FROM users u WHERE u.id = g.grantee_id)
                       ELSE (SELECT c.name FROM custom_groups c WHERE c.id = g.grantee_id)
                   END AS grantee_name,
                   CASE g.grantee_type
                       WHEN 'user' THEN (SELECT u.email FROM users u WHERE u.id = g.grantee_id)
                       ELSE NULL
                   END AS grantee_email
            FROM agent_visibility_grants g
            WHERE g.agent_key = %s
            ORDER BY g.grantee_type, grantee_name
            """,
            (agent_key,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def delete_grants_for_agent(agent_key) -> None:
    """Called when an agent is deleted, so grants cannot outlive it."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM agent_visibility_grants WHERE agent_key=%s", (agent_key,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def remove_user_from_org_sharing(user_id, org_id) -> None:
    """Off-boarding: drop the user's direct grants in this org and their
    memberships in this org's groups. Groups they created stay: a group is
    an org asset, not a personal one."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM agent_visibility_grants "
            "WHERE grantee_type='user' AND grantee_id=%s AND org_id=%s",
            (user_id, org_id),
        )
        cursor.execute(
            "DELETE m FROM group_memberships m "
            "JOIN custom_groups c ON c.id = m.group_id "
            "WHERE m.user_id=%s AND c.org_id=%s",
            (user_id, org_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def create_group(org_id, name, owner_id) -> str:
    group_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO custom_groups (id, org_id, name, owner_id) "
            "VALUES (%s, %s, %s, %s)",
            (group_id, org_id, name, owner_id),
        )
        conn.commit()
        return group_id
    finally:
        cursor.close()
        conn.close()


def get_group(group_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM custom_groups WHERE id=%s", (group_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def group_name_taken(org_id, name) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM custom_groups WHERE org_id=%s AND name=%s LIMIT 1",
            (org_id, name),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def list_groups(org_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.*, (SELECT COUNT(*) FROM group_memberships m
                         WHERE m.group_id = c.id) AS member_count
            FROM custom_groups c
            WHERE c.org_id = %s
            ORDER BY c.name
            """,
            (org_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def delete_group(group_id) -> None:
    """Delete the group, its memberships, and every grant made to it, so a
    deleted group cannot keep conferring access through orphaned rows."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM custom_groups WHERE id=%s", (group_id,))
        cursor.execute("DELETE FROM group_memberships WHERE group_id=%s", (group_id,))
        cursor.execute(
            "DELETE FROM agent_visibility_grants "
            "WHERE grantee_type='group' AND grantee_id=%s",
            (group_id,),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def add_group_member(group_id, user_id, added_by) -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT IGNORE INTO group_memberships (group_id, user_id, added_by) "
            "VALUES (%s, %s, %s)",
            (group_id, user_id, added_by),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def remove_group_member(group_id, user_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM group_memberships WHERE group_id=%s AND user_id=%s",
            (group_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def list_group_members(group_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT m.user_id, m.added_at, u.name, u.email, u.role
            FROM group_memberships m
            LEFT JOIN users u ON u.id = m.user_id
            WHERE m.group_id = %s
            ORDER BY u.name
            """,
            (group_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
