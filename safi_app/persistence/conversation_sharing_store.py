from __future__ import annotations

import logging
import re

from . import crypto
from . import database as db

log = logging.getLogger(__name__)

_COLLATION_RE = re.compile(r'^[a-z0-9_]+$')

ROLES = ('viewer', 'contributor')


def _target_collation(cursor) -> str:
    cursor.execute(
        "SELECT TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations'")
    row = cursor.fetchone()
    coll = (row[0] if row else None) or 'utf8mb4_unicode_ci'
    return coll if _COLLATION_RE.match(coll) else 'utf8mb4_unicode_ci'


def init_schema() -> None:
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


def _grant_role_query(table, id_col, resource_id, user_id, org_id):
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


def list_shared_with_me(user_id, org_id):
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


def list_shared_by_me(user_id, org_id):
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


def _still_reaches(table, id_col, resource_id, user_id, org_id) -> str | None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT g.grantee_type, g.grantee_id FROM {table} g
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
        rows = cursor.fetchall()
        for grantee_type, _grantee_id in rows:
            if grantee_type == 'group':
                return 'group'
        return 'direct' if rows else None
    finally:
        cursor.close()
        conn.close()


def remove_conversation_share_with_me(user_id, org_id, conversation_id):
    if not user_id or not org_id:
        return {"removed": False, "still_shared": None}
    removed = _revoke_grant('conversation_visibility_grants', 'conversation_id',
                             conversation_id, 'user', user_id)
    still = _still_reaches('conversation_visibility_grants', 'conversation_id',
                           conversation_id, user_id, org_id)
    if not still:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT project_id FROM conversations WHERE id = %s",
                           (conversation_id,))
            row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()
        if row and row[0]:
            if _still_reaches('project_visibility_grants', 'project_id',
                              row[0], user_id, org_id):
                still = 'project'
    return {"removed": removed, "still_shared": still}


def remove_project_share_with_me(user_id, org_id, project_id):
    if not user_id or not org_id:
        return {"removed": False, "still_shared": None}
    removed = _revoke_grant('project_visibility_grants', 'project_id',
                             project_id, 'user', user_id)
    still = _still_reaches('project_visibility_grants', 'project_id',
                           project_id, user_id, org_id)
    return {"removed": removed, "still_shared": still}


def remove_user_from_org_sharing(user_id, org_id) -> None:
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
