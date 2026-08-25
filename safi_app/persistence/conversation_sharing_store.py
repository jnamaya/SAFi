"""
Org sharing for conversations and folders (backlog 56): grants that let a
conversation or project be seen, and (at 'contributor') continued, by other
members of the same org.

WHY IT IS NOT IN database.py
-----------------------------
Same boundary as sharing_store.py (backlog 55): who may see or continue
someone else's conversation is Section III org configuration, not part of
the hash-chained audit ledger. database.py stays untouched by this feature.

THE RESOLVER
------------
get_conversation_role()/get_project_role() are the single authorization
answer for "can this user see or continue this conversation/project".
Order: owner, then a direct grant, then (conversations only) a grant on the
conversation's current project — checked live against the conversation's
CURRENT project_id, never denormalized onto the conversation itself, so
moving a conversation in or out of a shared folder changes its access
immediately, with no separate grant to maintain. No org-admin bypass:
oversight of every conversation already exists via the Audit Hub, a
separate mechanism for a separate purpose (compliance review, not peer
collaboration).
"""
from __future__ import annotations

import logging
import re

from . import crypto
from . import database as db

log = logging.getLogger(__name__)

_COLLATION_RE = re.compile(r'^[a-z0-9_]+$')

ROLES = ('viewer', 'contributor')


def _target_collation(cursor) -> str:
    """Copies conversations' collation — see sharing_store._target_collation
    for why: CREATE TABLE with only a charset takes the server default,
    which can differ from a table that has lived since MySQL 5.7, and the
    first JOIN then throws 1267 ("illegal mix of collations")."""
    cursor.execute(
        "SELECT TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations'")
    row = cursor.fetchone()
    coll = (row[0] if row else None) or 'utf8mb4_unicode_ci'
    return coll if _COLLATION_RE.match(coll) else 'utf8mb4_unicode_ci'


def init_schema() -> None:
    """Create the sharing tables if absent. Called once at boot, after
    db.init_db(). No foreign keys (house style, matching
    agent_visibility_grants); delete paths clean up dependent rows
    explicitly instead — see delete_grants_for_conversation/_project/_group
    below and their call sites."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        coll = _target_collation(cursor)
        charset = coll.split('_')[0]
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS conversation_visibility_grants (
                conversation_id VARCHAR(36) NOT NULL,
                grantee_type ENUM('user','group') NOT NULL,
                grantee_id VARCHAR(255) NOT NULL,
                role ENUM('viewer','contributor') NOT NULL DEFAULT 'viewer',
                org_id CHAR(36) NOT NULL,
                granted_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (conversation_id, grantee_type, grantee_id),
                INDEX idx_convo_grants_grantee (grantee_id)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS project_visibility_grants (
                project_id VARCHAR(36) NOT NULL,
                grantee_type ENUM('user','group') NOT NULL,
                grantee_id VARCHAR(255) NOT NULL,
                role ENUM('viewer','contributor') NOT NULL DEFAULT 'viewer',
                org_id CHAR(36) NOT NULL,
                granted_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (project_id, grantee_type, grantee_id),
                INDEX idx_project_grants_grantee (grantee_id)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        # Converge tables that already exist at a different collation (same
        # guard as sharing_store.init_schema, for the same reason).
        cursor.execute(
            "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN "
            "('conversation_visibility_grants','project_visibility_grants')")
        for name, table_coll in cursor.fetchall():
            if table_coll and table_coll != coll:
                log.warning("sharing table %s is %s, converting to %s to match conversations",
                            name, table_coll, coll)
                cursor.execute(
                    f"ALTER TABLE {name} CONVERT TO CHARACTER SET {charset} COLLATE {coll}")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def _grant_role_query(table, id_col, resource_id, user_id, org_id):
    """Best role (contributor beats viewer) reaching this user directly or
    via a group they belong to, scoped to org_id on both the grant and the
    group. None when nothing matches."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT g.role FROM {table} g
            WHERE g.{id_col} = %s AND g.org_id = %s
              AND (
                    (g.grantee_type = 'user' AND g.grantee_id = %s)
                 OR (g.grantee_type = 'group' AND g.grantee_id IN (
                        SELECT m.group_id FROM group_memberships m
                        JOIN custom_groups c ON c.id = m.group_id
                        WHERE m.user_id = %s AND c.org_id = %s))
              )
            """,
            (resource_id, org_id, user_id, user_id, org_id),
        )
        roles = {row[0] for row in cursor.fetchall()}
        if 'contributor' in roles:
            return 'contributor'
        if 'viewer' in roles:
            return 'viewer'
        return None
    finally:
        cursor.close()
        conn.close()


def get_conversation_role(user_id, org_id, conversation_id, owner_id, project_id=None):
    """'owner' | 'contributor' | 'viewer' | None.

    owner_id/project_id are the conversation's own current column values —
    this module has no dependency on the conversations table's shape;
    callers pass what they already fetched. Fails CLOSED: a storage error
    denies grant-based access (and is logged loudly) rather than crashing
    the caller; ownership is decided before this is consulted either way."""
    if not user_id or not conversation_id:
        return None
    if str(owner_id) == str(user_id):
        return 'owner'
    if not org_id:
        return None
    try:
        role = _grant_role_query('conversation_visibility_grants', 'conversation_id',
                                  conversation_id, user_id, org_id)
        if role:
            return role
        if project_id:
            return _grant_role_query('project_visibility_grants', 'project_id',
                                      project_id, user_id, org_id)
        return None
    except Exception as e:
        log.error("conversation grant lookup failed for %s: %s — denying grant-based access",
                   conversation_id, e)
        return None


def get_project_role(user_id, org_id, project_id, owner_id):
    """'owner' | 'contributor' | 'viewer' | None, for the folder itself
    (listing/renaming its membership), independent of any one conversation
    inside it. Fails CLOSED, same reasoning as get_conversation_role."""
    if not user_id or not project_id:
        return None
    if str(owner_id) == str(user_id):
        return 'owner'
    if not org_id:
        return None
    try:
        return _grant_role_query('project_visibility_grants', 'project_id',
                                  project_id, user_id, org_id)
    except Exception as e:
        log.error("project grant lookup failed for %s: %s — denying grant-based access",
                   project_id, e)
        return None


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

def _set_grant(table, id_col, resource_id, grantee_type, grantee_id, role, org_id, granted_by):
    if role not in ROLES:
        raise ValueError(f"unsupported role '{role}'")
    if grantee_type not in ('user', 'group'):
        raise ValueError(f"unsupported grantee type '{grantee_type}'")
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            INSERT INTO {table} ({id_col}, grantee_type, grantee_id, role, org_id, granted_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                role = VALUES(role),
                org_id = VALUES(org_id),
                granted_by = VALUES(granted_by)
            """,
            (resource_id, grantee_type, grantee_id, role, org_id, granted_by),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _revoke_grant(table, id_col, resource_id, grantee_type, grantee_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {table} WHERE {id_col}=%s AND grantee_type=%s AND grantee_id=%s",
            (resource_id, grantee_type, grantee_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def _list_grants(table, id_col, resource_id):
    """Grants on one resource, with display names resolved for the dialog."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT g.{id_col} AS resource_id, g.grantee_type, g.grantee_id,
                   g.role, g.granted_by, g.created_at,
                   CASE g.grantee_type
                       WHEN 'user' THEN (SELECT u.name FROM users u WHERE u.id = g.grantee_id)
                       ELSE (SELECT c.name FROM custom_groups c WHERE c.id = g.grantee_id)
                   END AS grantee_name,
                   CASE g.grantee_type
                       WHEN 'user' THEN (SELECT u.email FROM users u WHERE u.id = g.grantee_id)
                       ELSE NULL
                   END AS grantee_email
            FROM {table} g
            WHERE g.{id_col} = %s
            ORDER BY g.grantee_type, grantee_name
            """,
            (resource_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def set_conversation_grant(conversation_id, grantee_type, grantee_id, role, org_id, granted_by) -> None:
    _set_grant('conversation_visibility_grants', 'conversation_id', conversation_id,
               grantee_type, grantee_id, role, org_id, granted_by)


def revoke_conversation_grant(conversation_id, grantee_type, grantee_id) -> bool:
    return _revoke_grant('conversation_visibility_grants', 'conversation_id',
                          conversation_id, grantee_type, grantee_id)


def list_conversation_grants(conversation_id):
    return _list_grants('conversation_visibility_grants', 'conversation_id', conversation_id)


def delete_grants_for_conversation(conversation_id) -> None:
    """Called when a conversation is deleted, so grants cannot outlive it."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM conversation_visibility_grants WHERE conversation_id=%s",
            (conversation_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def set_project_grant(project_id, grantee_type, grantee_id, role, org_id, granted_by) -> None:
    _set_grant('project_visibility_grants', 'project_id', project_id,
               grantee_type, grantee_id, role, org_id, granted_by)


def revoke_project_grant(project_id, grantee_type, grantee_id) -> bool:
    return _revoke_grant('project_visibility_grants', 'project_id',
                          project_id, grantee_type, grantee_id)


def list_project_grants(project_id):
    return _list_grants('project_visibility_grants', 'project_id', project_id)


def delete_grants_for_project(project_id) -> None:
    """Called when a project (folder) is deleted, so grants cannot outlive
    it. Conversations that were inside it are unaffected here: they fall
    back to the loose History list (see database.delete_project), and any
    DIRECT grant on one of them is untouched — only the folder-level grant
    disappears."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM project_visibility_grants WHERE project_id=%s",
            (project_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def delete_grants_for_group(group_id) -> None:
    """Called when a custom_group is deleted (mirrors sharing_store's own
    cleanup of agent_visibility_grants for the same event), so a deleted
    group cannot keep conferring conversation/folder access through an
    orphaned grant row."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM conversation_visibility_grants WHERE grantee_type='group' AND grantee_id=%s",
            (group_id,))
        cursor.execute(
            "DELETE FROM project_visibility_grants WHERE grantee_type='group' AND grantee_id=%s",
            (group_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Shared-with-me listings
# ---------------------------------------------------------------------------
# These JOIN the grant tables directly against `conversations`/`projects`,
# same as sharing_store.granted_agents() JOINs against `agents` — the query
# needs both tiers at once, and only one of them is manifest-covered. Fail
# EMPTY, not loud: a shared-with-me list is additive, never a security
# boundary, so a broken query should read as "nothing shared", not a 500.

def list_shared_with_me(user_id, org_id):
    """Conversations reachable through a direct or folder-level grant (not
    owned), deduplicated to the single best role per conversation."""
    if not user_id or not org_id:
        return []
    try:
        return _list_shared_with_me_query(user_id, org_id)
    except Exception as e:
        log.error("shared-with-me conversation lookup failed for user %s: %s "
                  "— returning empty list", user_id, e)
        return []


def _list_shared_with_me_query(user_id, org_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.id, c.title, c.project_id, c.created_at, c.user_id AS owner_id,
                   u.name AS owner_name,
                   (SELECT ch.profile_name FROM chat_history ch
                      WHERE ch.conversation_id = c.id AND ch.profile_name IS NOT NULL
                      ORDER BY ch.id DESC LIMIT 1) AS profile_name,
                   CASE WHEN MAX(cand.role = 'contributor') = 1
                        THEN 'contributor' ELSE 'viewer' END AS role
            FROM (
                SELECT g.conversation_id AS cid, g.role FROM conversation_visibility_grants g
                WHERE g.org_id = %s AND (
                      (g.grantee_type = 'user' AND g.grantee_id = %s)
                   OR (g.grantee_type = 'group' AND g.grantee_id IN (
                          SELECT m.group_id FROM group_memberships m
                          JOIN custom_groups cg ON cg.id = m.group_id
                          WHERE m.user_id = %s AND cg.org_id = %s)))
                UNION ALL
                SELECT co.id AS cid, g.role FROM project_visibility_grants g
                JOIN conversations co ON co.project_id = g.project_id
                WHERE g.org_id = %s AND (
                      (g.grantee_type = 'user' AND g.grantee_id = %s)
                   OR (g.grantee_type = 'group' AND g.grantee_id IN (
                          SELECT m.group_id FROM group_memberships m
                          JOIN custom_groups cg ON cg.id = m.group_id
                          WHERE m.user_id = %s AND cg.org_id = %s)))
            ) cand
            JOIN conversations c ON c.id = cand.cid
            LEFT JOIN users u ON u.id = c.user_id
            GROUP BY c.id, c.title, c.project_id, c.created_at, c.user_id, u.name
            ORDER BY c.created_at DESC
            """,
            (org_id, user_id, user_id, org_id, org_id, user_id, user_id, org_id),
        )
        rows = cursor.fetchall()
        for r in rows:
            r['title'] = crypto.decrypt_value(r['title'])
        return rows
    finally:
        cursor.close()
        conn.close()


def list_projects_shared_with_me(user_id, org_id):
    """Folders reachable through a direct grant on the folder itself (not
    owned). A grant on a conversation INSIDE a folder does not surface the
    folder here — that access is per-conversation, not per-folder."""
    if not user_id or not org_id:
        return []
    try:
        return _list_projects_shared_with_me_query(user_id, org_id)
    except Exception as e:
        log.error("shared-with-me project lookup failed for user %s: %s "
                  "— returning empty list", user_id, e)
        return []


def _list_projects_shared_with_me_query(user_id, org_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT p.id, p.name, p.created_at, p.user_id AS owner_id, u.name AS owner_name,
                   CASE WHEN MAX(g.role = 'contributor') = 1
                        THEN 'contributor' ELSE 'viewer' END AS role
            FROM project_visibility_grants g
            JOIN projects p ON p.id = g.project_id
            LEFT JOIN users u ON u.id = p.user_id
            WHERE g.org_id = %s AND (
                  (g.grantee_type = 'user' AND g.grantee_id = %s)
               OR (g.grantee_type = 'group' AND g.grantee_id IN (
                      SELECT m.group_id FROM group_memberships m
                      JOIN custom_groups cg ON cg.id = m.group_id
                      WHERE m.user_id = %s AND cg.org_id = %s)))
            GROUP BY p.id, p.name, p.created_at, p.user_id, u.name
            ORDER BY p.created_at DESC
            """,
            (org_id, user_id, user_id, org_id),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Shared-by-me indicator
# ---------------------------------------------------------------------------
# Not a "Shared by me" listing: everything the owner shared already appears
# in their own folders and history, so a second copy would put one
# conversation in the sidebar twice. This returns only the ids that carry a
# grant, so the sidebar can mark the row where it already lives. Fail EMPTY
# for the same reason as the listings above, and more so — a missing mark is
# a missing decoration, never a missing access check.

def list_shared_by_me(user_id, org_id):
    """Ids of conversations and folders THIS user owns that have at least one
    grant on them. {'conversations': [...], 'projects': [...]}."""
    empty = {"conversations": [], "projects": []}
    if not user_id or not org_id:
        return empty
    try:
        return _list_shared_by_me_query(user_id, org_id)
    except Exception as e:
        log.error("shared-by-me lookup failed for user %s: %s "
                  "— returning empty lists", user_id, e)
        return empty


def _list_shared_by_me_query(user_id, org_id):
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT g.conversation_id
            FROM conversation_visibility_grants g
            JOIN conversations c ON c.id = g.conversation_id
            WHERE g.org_id = %s AND c.user_id = %s
            """,
            (org_id, user_id),
        )
        conversations = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT DISTINCT g.project_id
            FROM project_visibility_grants g
            JOIN projects p ON p.id = g.project_id
            WHERE g.org_id = %s AND p.user_id = %s
            """,
            (org_id, user_id),
        )
        projects = [r[0] for r in cursor.fetchall()]
        return {"conversations": conversations, "projects": projects}
    finally:
        cursor.close()
        conn.close()


def remove_user_from_org_sharing(user_id, org_id) -> None:
    """Off-boarding: drop this user's direct grants (both tables) in this
    org. Mirrors sharing_store.remove_user_from_org_sharing; group
    memberships themselves are cleaned up there since groups are shared
    infrastructure, not owned per-feature."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM conversation_visibility_grants "
            "WHERE grantee_type='user' AND grantee_id=%s AND org_id=%s",
            (user_id, org_id))
        cursor.execute(
            "DELETE FROM project_visibility_grants "
            "WHERE grantee_type='user' AND grantee_id=%s AND org_id=%s",
            (user_id, org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
