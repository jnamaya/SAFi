"""
Scoped agent sharing (backlog 55): custom groups and per-agent grants.

An agent's visibility data and the host's role policy determine baseline
organization access. This module adds per-user and per-group grants as pure
widening: a grant can add access but cannot remove baseline access.

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
Visibility used to be enforced on listing only, which meant a private agent
was hidden but not protected. Order of checks: owner, configured authority,
configured visibility, then grants; anything else is denied.

Grants are org-scoped at write time (the grant row carries the agent's
org_id) and re-checked org-scoped at read time, so a grant can never leak an
agent across organizations even if rows are tampered with directly.
"""
from __future__ import annotations

import logging
import re
import uuid

from . import database as db

log = logging.getLogger(__name__)

_COLLATION_RE = re.compile(r'^[a-z0-9_]+$')


def _target_collation(cursor) -> str:
    """The collation of the tables these tables JOIN against.

    Learned the hard way (demo outage 2026-08-17): CREATE TABLE with only a
    charset takes the server's default collation, which on MySQL 8 is
    utf8mb4_0900_ai_ci, while a database that has lived since 5.7 holds its
    tables at utf8mb4_unicode_ci. The first join then throws 1267 ("illegal
    mix of collations") and every caller that unions grants into a listing
    loses the whole listing. So the new tables copy the collation of
    `agents`, whatever it is on this deployment, instead of trusting the
    server default to match."""
    cursor.execute(
        "SELECT TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents'")
    row = cursor.fetchone()
    coll = (row[0] if row else None) or 'utf8mb4_unicode_ci'
    return coll if _COLLATION_RE.match(coll) else 'utf8mb4_unicode_ci'

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
        coll = _target_collation(cursor)
        charset = coll.split('_')[0]
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS custom_groups (
                id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                name VARCHAR(100) NOT NULL,
                owner_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_groups_org (org_id)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS group_memberships (
                group_id CHAR(36) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                added_by VARCHAR(255),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id),
                INDEX idx_memberships_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS group_nested_groups (
                parent_group_id CHAR(36) NOT NULL,
                child_group_id CHAR(36) NOT NULL,
                added_by VARCHAR(255),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (parent_group_id, child_group_id),
                INDEX idx_nested_child (child_group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        # agent_key matches agents.agent_key (VARCHAR(100) string key, not a
        # UUID). grantee_id is a users.id (VARCHAR(255)) or a custom_groups.id.
        cursor.execute(f"""
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
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        # Converge tables that already exist at a different collation (the
        # 2026-08-17 rollout created them at the server default before this
        # guard existed). CONVERT rewrites the rows, but these tables are
        # small by construction.
        cursor.execute(
            "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN "
            "('custom_groups','group_memberships','group_nested_groups','agent_visibility_grants')")
        for name, table_coll in cursor.fetchall():
            if table_coll and table_coll != coll:
                log.warning("sharing table %s is %s, converting to %s to match agents",
                            name, table_coll, coll)
                cursor.execute(
                    f"ALTER TABLE {name} CONVERT TO CHARACTER SET {charset} COLLATE {coll}")

        cursor.execute("SHOW COLUMNS FROM custom_groups LIKE 'model_policy'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE custom_groups ADD COLUMN model_policy VARCHAR(50) DEFAULT 'default'")

        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def can_use_agent(user_id, role, org_id, agent, role_config=None) -> bool:
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
    role_config = role_config or {}
    role = role or role_config.get('default_role')
    if role in (role_config.get('organization_admin_roles') or []):
        return True
    visibility_roles = role_config.get('visibility_roles') or {}
    if role in (visibility_roles.get(agent.get('visibility')) or []):
        return True
    key = agent.get('agent_key') or agent.get('key')
    return has_grant(key, user_id, org_id)


def get_user_group_names(user_id, org_id) -> set:
    """Return lowercase names of all custom groups this user belongs to in org_id (direct or nested)."""
    if not user_id or not org_id:
        return set()
    conn = None
    cursor = None
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT LOWER(c.name) FROM custom_groups c
            JOIN group_memberships m ON m.group_id = c.id
            WHERE m.user_id = %s AND c.org_id = %s
            UNION
            SELECT LOWER(p.name) FROM custom_groups p
            JOIN group_nested_groups ng ON ng.parent_group_id = p.id
            JOIN group_memberships m ON m.group_id = ng.child_group_id
            WHERE m.user_id = %s AND p.org_id = %s
            """,
            (user_id, org_id, user_id, org_id),
        )
        return {row[0] for row in cursor.fetchall() if row[0]}
    except Exception as e:
        log.warning("get_user_group_names failed for %s: %s", user_id, e)
        return set()
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_user_group_details(user_id, org_id) -> list:
    """Return full custom_groups rows this user belongs to in org_id (direct or nested)."""
    if not user_id or not org_id:
        return []
    conn = None
    cursor = None
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT c.* FROM custom_groups c
            JOIN group_memberships m ON m.group_id = c.id
            WHERE m.user_id = %s AND c.org_id = %s
            UNION
            SELECT p.* FROM custom_groups p
            JOIN group_nested_groups ng ON ng.parent_group_id = p.id
            JOIN group_memberships m ON m.group_id = ng.child_group_id
            WHERE m.user_id = %s AND p.org_id = %s
            """,
            (user_id, org_id, user_id, org_id),
        )
        return cursor.fetchall() or []
    except Exception as e:
        log.warning("get_user_group_details failed for %s: %s", user_id, e)
        return []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def can_use_built_in_or_custom_agent(user_id, role, org_id, agent_key, role_config=None) -> bool:
    """Authorize access to either a built-in agent (sysadmin, security_engineer,
    software_engineer) or a custom DB agent.

    Admins always have full access across all agents.
    
    Built-in agents:
    - sysadmin: requires role 'admin' OR membership in a group named/granted 'sysadmin',
      'sysadmins', 'it-admins', 'it-infrastructure', 'infrastructure'.
    - security_engineer: requires role 'admin' OR membership in a group
      named/granted 'secops', 'security', 'security_engineer', 'infosec'.
    - software_engineer: requires role 'admin' OR membership in a group
      named/granted 'developers', 'developer', 'software_engineer', 'engineering', 'devs'.

    Custom DB agents:
    - Resolved via can_use_agent().
    """
    if not user_id or not agent_key:
        return False

    role_config = role_config or {}
    role = role or role_config.get('default_role') or 'member'
    admin_roles = set(role_config.get('organization_admin_roles') or ['admin'])
    if role in admin_roles:
        return True

    key = str(agent_key).lower().strip()

    # Check built-in agents
    if key == "sysadmin":
        if has_grant("sysadmin", user_id, org_id):
            return True
        user_groups = get_user_group_names(user_id, org_id)
        allowed_group_names = {
            "sysadmin", "sysadmins", "it-admins", "it-infrastructure",
            "infrastructure", "it", "ops", "operations", "devops", "sre",
            "admin", "admins"
        }
        return bool(user_groups & allowed_group_names)

    if key == "security_engineer":
        if has_grant("security_engineer", user_id, org_id):
            return True
        user_groups = get_user_group_names(user_id, org_id)
        allowed_group_names = {
            "secops", "security", "security_engineer", "security-operations",
            "infosec", "cybersecurity", "sec"
        }
        return bool(user_groups & allowed_group_names)

    if key in ("software_engineer", "developer"):
        if has_grant("software_engineer", user_id, org_id) or has_grant("developer", user_id, org_id):
            return True
        user_groups = get_user_group_names(user_id, org_id)
        allowed_group_names = {
            "dev", "devs", "developers", "developer", "software_engineer",
            "software_engineering", "engineering", "engineer", "engineers",
            "development", "devops"
        }
        return bool(user_groups & allowed_group_names)

    if key == "safi":
        # General conversational assistant available to all authenticated org members
        return True

    # Check custom DB agent
    raw_agent = db.get_agent(agent_key)
    if raw_agent:
        return can_use_agent(user_id, role, org_id, raw_agent, role_config)

    # Unrecognized agent fails closed
    return False


def get_first_usable_agent(user_id, role, org_id, role_config=None):
    """Return the key of the first agent this user is authorized to use,
    or None if the user has access to no agents."""
    if not user_id:
        return None
    from ..profile_resolver import AGENTS
    for k in AGENTS.keys():
        if can_use_built_in_or_custom_agent(user_id, role, org_id, k, role_config):
            return k
    if user_id or org_id:
        try:
            raw_list = db.list_agents(
                user_id, org_id, role or (role_config.get("default_role") if role_config else "member"),
                role_config.get("visibility_roles") if role_config else {},
            )
            for a in raw_list:
                key = a.get("agent_key") or a.get("key")
                if key and can_use_built_in_or_custom_agent(user_id, role, org_id, key, role_config):
                    return key
            for granted in granted_agents(user_id, org_id):
                key = granted.get("key") or granted.get("agent_key")
                if key:
                    return key
        except Exception:
            pass
    return None


def has_grant(agent_key, user_id, org_id) -> bool:
    """True when a can_use grant reaches this user directly or via a group
    they belong to, scoped to `org_id` on both the grant and the group.

    Fails CLOSED: a storage error here denies grant-based access (and is
    logged loudly) rather than crashing the caller. Owner and configured
    visibility access are decided before this is consulted, so they are unaffected."""
    if not agent_key or not user_id or not org_id:
        return False
    try:
        return _has_grant_query(agent_key, user_id, org_id)
    except Exception as e:
        log.error("grant lookup failed for agent %s: %s: denying grant-based access",
                  agent_key, e)
        return False


def _has_grant_query(agent_key, user_id, org_id) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT 1 FROM agent_visibility_grants g
            WHERE g.agent_key = %s AND g.org_id = %s
              AND (
                    (g.grantee_type = 'user' AND g.grantee_id = %s)
                 OR (g.grantee_type = 'group' AND (
                        g.grantee_id IN (
                            SELECT m.group_id FROM group_memberships m
                            JOIN custom_groups c ON c.id = m.group_id
                            WHERE m.user_id = %s AND c.org_id = %s
                        )
                        OR g.grantee_id IN (
                            SELECT ng.parent_group_id FROM group_nested_groups ng
                            JOIN group_memberships m ON m.group_id = ng.child_group_id
                            JOIN custom_groups p ON p.id = ng.parent_group_id
                            WHERE m.user_id = %s AND p.org_id = %s
                        )
                    ))
              )
            LIMIT 1
            """,
            (agent_key, org_id, user_id, user_id, org_id, user_id, org_id),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def granted_agents(user_id, org_id):
    """Full agent rows this user can use through grants, for the pickers.
    The join re-asserts the org scope so a stray grant row cannot surface a
    foreign org's agent.

    Fails EMPTY: grants only widen a listing, so when this query breaks the
    caller must still get its base list. The 2026-08-17 demo outage was this
    exact failure unguarded: a collation mismatch threw inside the caller's
    try-block and took the user's own agents down with it."""
    if not user_id or not org_id:
        return []
    try:
        return _granted_agents_query(user_id, org_id)
    except Exception as e:
        log.error("granted-agents lookup failed for user %s: %s: omitting "
                  "shared agents from the listing", user_id, e)
        return []


def _granted_agents_query(user_id, org_id):
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
                 OR (g.grantee_type = 'group' AND (
                        g.grantee_id IN (
                            SELECT m.group_id FROM group_memberships m
                            JOIN custom_groups c ON c.id = m.group_id
                            WHERE m.user_id = %s AND c.org_id = %s
                        )
                        OR g.grantee_id IN (
                            SELECT ng.parent_group_id FROM group_nested_groups ng
                            JOIN group_memberships m ON m.group_id = ng.child_group_id
                            JOIN custom_groups p ON p.id = ng.parent_group_id
                            WHERE m.user_id = %s AND p.org_id = %s
                        )
                    ))
              )
            """,
            (org_id, user_id, user_id, org_id, user_id, org_id),
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

def create_group(org_id, name, owner_id, model_policy='default') -> str:
    group_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO custom_groups (id, org_id, name, owner_id, model_policy) "
            "VALUES (%s, %s, %s, %s, %s)",
            (group_id, org_id, name, owner_id, model_policy or 'default'),
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


def get_group_by_name(org_id, name):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM custom_groups WHERE org_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1", (org_id, (name or "").strip()))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def update_group_model_policy(group_id, model_policy) -> bool:
    if model_policy not in ('default', 'local', 'cloud'):
        raise ValueError("Invalid model_policy: must be 'default', 'local', or 'cloud'")
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE custom_groups SET model_policy = %s WHERE id = %s",
            (model_policy, group_id),
        )
        conn.commit()
        return cursor.rowcount > 0
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
    """Delete the group, its memberships, its nested relationships, and every grant made to it,
    so a deleted group cannot keep conferring access through orphaned rows."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM custom_groups WHERE id=%s", (group_id,))
        cursor.execute("DELETE FROM group_memberships WHERE group_id=%s", (group_id,))
        cursor.execute("DELETE FROM group_nested_groups WHERE parent_group_id=%s OR child_group_id=%s", (group_id, group_id))
        cursor.execute(
            "DELETE FROM agent_visibility_grants "
            "WHERE grantee_type='group' AND grantee_id=%s",
            (group_id,),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def add_nested_group(parent_group_id: str, child_group_id: str, added_by: str = "") -> bool:
    """Include a child group inside a parent group (nested group membership)."""
    if not parent_group_id or not child_group_id or str(parent_group_id) == str(child_group_id):
        return False
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        # Check reverse link to prevent direct cyclic loop
        cursor.execute(
            "SELECT 1 FROM group_nested_groups WHERE parent_group_id=%s AND child_group_id=%s",
            (child_group_id, parent_group_id),
        )
        if cursor.fetchone():
            return False
        cursor.execute(
            "INSERT IGNORE INTO group_nested_groups (parent_group_id, child_group_id, added_by) "
            "VALUES (%s, %s, %s)",
            (parent_group_id, child_group_id, added_by or None),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def remove_nested_group(parent_group_id: str, child_group_id: str) -> bool:
    """Remove a child group from a parent group."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM group_nested_groups WHERE parent_group_id=%s AND child_group_id=%s",
            (parent_group_id, child_group_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def list_nested_groups(parent_group_id: str) -> list:
    """Return all child groups included in parent_group_id."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.id, c.name, c.model_policy, c.created_at, ng.added_at,
                   (SELECT COUNT(*) FROM group_memberships m WHERE m.group_id = c.id) AS member_count
            FROM custom_groups c
            JOIN group_nested_groups ng ON ng.child_group_id = c.id
            WHERE ng.parent_group_id = %s
            ORDER BY c.name
            """,
            (parent_group_id,),
        )
        return cursor.fetchall() or []
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
