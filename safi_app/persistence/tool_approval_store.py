from __future__ import annotations

import json
import logging
import uuid

from . import database as db
from .sharing_store import _target_collation

log = logging.getLogger(__name__)


def init_schema() -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        coll = _target_collation(cursor)
        charset = coll.split('_')[0]
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS agent_tool_requests (
                id CHAR(36) PRIMARY KEY,
                agent_key VARCHAR(100) NOT NULL,
                org_id CHAR(36) NOT NULL,
                requested_by VARCHAR(255) NOT NULL,
                added JSON NOT NULL,
                requested_tools JSON,
                status ENUM('pending','approved','rejected','superseded')
                    NOT NULL DEFAULT 'pending',
                reviewed_by VARCHAR(255) NULL,
                reviewer_email VARCHAR(255) NULL,
                reviewed_at TIMESTAMP NULL,
                self_approved BOOLEAN DEFAULT FALSE,
                reason TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_toolreq_org (org_id, status, created_at),
                INDEX idx_toolreq_agent (agent_key, status)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        cursor.execute(
            "SELECT TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_tool_requests'")
        row = cursor.fetchone()
        if row and row[0] and row[0] != coll:
            log.warning("agent_tool_requests is %s, converting to %s to match agents",
                        row[0], coll)
            cursor.execute(
                f"ALTER TABLE agent_tool_requests CONVERT TO CHARACTER SET {charset} COLLATE {coll}")
        cursor.execute("SHOW COLUMNS FROM agent_tool_requests LIKE 'acknowledged_at'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE agent_tool_requests ADD COLUMN acknowledged_at TIMESTAMP NULL")
        cursor.execute("SHOW COLUMNS FROM agent_tool_requests LIKE 'request_type'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agent_tool_requests MODIFY agent_key VARCHAR(100) NULL")
            cursor.execute("ALTER TABLE agent_tool_requests "
                           "ADD COLUMN request_type ENUM('agent','policy') NOT NULL DEFAULT 'agent'")
            cursor.execute("ALTER TABLE agent_tool_requests ADD COLUMN policy_id VARCHAR(255) NULL")
            cursor.execute("ALTER TABLE agent_tool_requests ADD COLUMN target_tools JSON NULL")
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS approval_settings (
                org_id CHAR(36) PRIMARY KEY,
                approver_group_id CHAR(36) NULL,
                updated_by VARCHAR(255),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        cursor.execute("SHOW COLUMNS FROM approval_settings LIKE 'policy_approver_group_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE approval_settings "
                           "ADD COLUMN policy_approver_group_id CHAR(36) NULL")
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS policy_change_requests (
                id CHAR(36) PRIMARY KEY,
                policy_id VARCHAR(255) NOT NULL,
                org_id CHAR(36) NOT NULL,
                requested_by VARCHAR(255) NOT NULL,
                payload JSON NOT NULL,
                changed JSON,
                status ENUM('pending','approved','rejected','superseded')
                    NOT NULL DEFAULT 'pending',
                reviewed_by VARCHAR(255) NULL,
                reviewer_email VARCHAR(255) NULL,
                reviewed_at TIMESTAMP NULL,
                self_approved BOOLEAN DEFAULT FALSE,
                reason TEXT NULL,
                acknowledged_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_polreq_org (org_id, status, created_at),
                INDEX idx_polreq_policy (policy_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET={charset} COLLATE={coll}
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def create_request(agent_key, org_id, requested_by, added, requested_tools) -> str:
    request_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agent_tool_requests SET status='superseded' "
            "WHERE agent_key=%s AND status='pending'", (agent_key,))
        cursor.execute(
            "INSERT INTO agent_tool_requests "
            "(id, agent_key, org_id, requested_by, added, requested_tools) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (request_id, agent_key, org_id, requested_by,
             json.dumps(sorted(added)), json.dumps(sorted(requested_tools))))
        conn.commit()
        return request_id
    finally:
        cursor.close()
        conn.close()


def create_policy_request(policy_id, org_id, requested_by, added, target_tools) -> str:
    request_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agent_tool_requests SET status='superseded' "
            "WHERE policy_id=%s AND request_type='policy' AND status='pending'",
            (policy_id,))
        cursor.execute(
            "INSERT INTO agent_tool_requests "
            "(id, request_type, policy_id, org_id, requested_by, added, target_tools) "
            "VALUES (%s, 'policy', %s, %s, %s, %s, %s)",
            (request_id, policy_id, org_id, requested_by,
             json.dumps(sorted(added)), json.dumps(sorted(target_tools))))
        conn.commit()
        return request_id
    finally:
        cursor.close()
        conn.close()


def _load(row):
    if not row:
        return None
    for col in ('added', 'requested_tools', 'target_tools'):
        if isinstance(row.get(col), str):
            try:
                row[col] = json.loads(row[col])
            except ValueError:
                row[col] = []
    return row


def get_request(request_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM agent_tool_requests WHERE id=%s", (request_id,))
        return _load(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()


def list_requests(org_id, status='pending'):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT u.name FROM users u WHERE u.id = r.requested_by) AS requester_name,
                   (SELECT a.name FROM agents a WHERE a.agent_key = r.agent_key) AS agent_name,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM agent_tool_requests r
            WHERE r.org_id = %s AND r.status = %s
            ORDER BY r.created_at ASC
            """, (org_id, status))
        return [_load(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def resolve_request(request_id, status, reviewer_id, reviewer_email,
                    self_approved=False, reason=None) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agent_tool_requests SET status=%s, reviewed_by=%s, "
            "reviewer_email=%s, reviewed_at=UTC_TIMESTAMP(), self_approved=%s, "
            "reason=%s WHERE id=%s AND status='pending'",
            (status, reviewer_id, reviewer_email, bool(self_approved),
             reason, request_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def apply_tools(agent_key, tools) -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE agents SET tools_json=%s WHERE agent_key=%s",
                       (json.dumps(sorted(tools)), agent_key))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def apply_policy_tools(policy_id, target_tools) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT will_rules FROM policies WHERE id=%s FOR UPDATE", (policy_id,))
        row = cursor.fetchone()
        if not row:
            return False
        rules = row.get('will_rules')
        if isinstance(rules, str):
            try:
                rules = json.loads(rules)
            except ValueError:
                return False
        if rules is None:
            rules = {}
        if not isinstance(rules, dict):
            return False
        rules['allowed_tools'] = sorted(target_tools)
        cursor.execute("UPDATE policies SET will_rules=%s WHERE id=%s",
                       (json.dumps(rules), policy_id))
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()


_APPROVER_COLS = {'tools': 'approver_group_id', 'policy': 'policy_approver_group_id'}


def get_approver_group(org_id, kind='tools'):
    col = _APPROVER_COLS[kind]
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT s.{col} FROM approval_settings s "
            f"JOIN custom_groups c ON c.id = s.{col} AND c.org_id = s.org_id "
            f"WHERE s.org_id = %s AND EXISTS "
            f"(SELECT 1 FROM group_memberships m WHERE m.group_id = s.{col})",
            (org_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        conn.close()


def get_approver_setting(org_id, kind='tools'):
    col = _APPROVER_COLS[kind]
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT {col} FROM approval_settings WHERE org_id=%s", (org_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        conn.close()


def set_approver_group(org_id, group_id, actor, kind='tools') -> None:
    col = _APPROVER_COLS[kind]
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"INSERT INTO approval_settings (org_id, {col}, updated_by) "
            f"VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE "
            f"{col} = VALUES({col}), updated_by = VALUES(updated_by)",
            (org_id, group_id, actor))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def is_reviewer(org_id, user_id, role, kind='tools', reviewer_roles=None) -> bool:
    if not org_id or not user_id:
        return False
    group_id = get_approver_group(org_id, kind)
    if group_id:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM group_memberships WHERE group_id=%s AND user_id=%s LIMIT 1",
                (group_id, user_id))
            return cursor.fetchone() is not None
        finally:
            cursor.close()
            conn.close()
    return role in (reviewer_roles or [])


def other_reviewer_exists(org_id, exclude_user_id, kind='tools', reviewer_roles=None) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        group_id = get_approver_group(org_id, kind)
        if group_id:
            cursor.execute(
                "SELECT 1 FROM group_memberships WHERE group_id=%s AND user_id != %s LIMIT 1",
                (group_id, exclude_user_id))
        else:
            reviewer_roles = list(reviewer_roles or [])
            if not reviewer_roles:
                return False
            placeholders = ",".join(["%s"] * len(reviewer_roles))
            cursor.execute(
                f"SELECT 1 FROM users WHERE org_id=%s AND role IN ({placeholders}) "
                "AND id != %s LIMIT 1", (org_id, *reviewer_roles, exclude_user_id))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def create_policy_change(policy_id, org_id, requested_by, payload, changed) -> str:
    request_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE policy_change_requests SET status='superseded' "
            "WHERE policy_id=%s AND status='pending'", (policy_id,))
        cursor.execute(
            "INSERT INTO policy_change_requests "
            "(id, policy_id, org_id, requested_by, payload, changed) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (request_id, policy_id, org_id, requested_by,
             json.dumps(payload), json.dumps(sorted(changed))))
        conn.commit()
        return request_id
    finally:
        cursor.close()
        conn.close()


def _load_policy_change(row):
    if not row:
        return None
    for col in ('payload', 'changed'):
        if isinstance(row.get(col), str):
            try:
                row[col] = json.loads(row[col])
            except ValueError:
                row[col] = None
    return row


def get_policy_change(request_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM policy_change_requests WHERE id=%s", (request_id,))
        return _load_policy_change(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()


def list_policy_changes(org_id, status='pending'):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT u.name FROM users u WHERE u.id = r.requested_by) AS requester_name,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM policy_change_requests r
            WHERE r.org_id = %s AND r.status = %s
            ORDER BY r.created_at ASC
            """, (org_id, status))
        return [_load_policy_change(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def resolve_policy_change(request_id, status, reviewer_id, reviewer_email,
                          self_approved=False, reason=None) -> bool:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE policy_change_requests SET status=%s, reviewed_by=%s, "
            "reviewer_email=%s, reviewed_at=UTC_TIMESTAMP(), self_approved=%s, "
            "reason=%s WHERE id=%s AND status='pending'",
            (status, reviewer_id, reviewer_email, bool(self_approved),
             reason, request_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def _policy_change_label(r, with_status=False):
    name = r.get('policy_name') or r.get('policy_id')
    changed = ', '.join(r.get('changed') or []) or 'content'
    label = f"Policy {name}: {changed}"
    if with_status:
        label = f"Policy {name}: {r['status']} ({changed})"
        if r['status'] == 'rejected' and r.get('reason'):
            label += f": {r['reason']}"
    return label


def pending_policy_summary(org_id):
    rows = list_policy_changes(org_id, 'pending')
    return {"count": len(rows),
            "oldest": rows[0]['created_at'] if rows else None,
            "examples": [_policy_change_label(r) for r in rows[:3]]}


def _request_label(r):
    if r.get('request_type') == 'policy':
        name = r.get('policy_name') or r.get('policy_id')
        return f"Policy {name}: +{', +'.join(r.get('added') or [])}"
    name = r.get('agent_name') or r.get('agent_key')
    return f"{name}: +{', +'.join(r.get('added') or [])}"


def pending_summary(org_id):
    rows = list_requests(org_id, 'pending')
    return {"count": len(rows),
            "oldest": rows[0]['created_at'] if rows else None,
            "examples": [_request_label(r) for r in rows[:3]]}


def pending_own_requests(user_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT a.name FROM agents a WHERE a.agent_key = r.agent_key) AS agent_name,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM agent_tool_requests r
            WHERE r.requested_by = %s AND r.status = 'pending'
            ORDER BY r.created_at ASC
            """, (user_id,))
        tool_rows = [_load(r) for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM policy_change_requests r
            WHERE r.requested_by = %s AND r.status = 'pending'
            ORDER BY r.created_at ASC
            """, (user_id,))
        policy_rows = [_load_policy_change(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()
    labeled = ([(r['created_at'], _request_label(r)) for r in tool_rows]
               + [(r['created_at'], _policy_change_label(r)) for r in policy_rows])
    labeled.sort(key=lambda x: (x[0] is None, x[0]))
    return {"count": len(labeled),
            "oldest": labeled[0][0] if labeled else None,
            "examples": [label for _, label in labeled[:3]]}


def unacknowledged_outcomes(user_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT a.name FROM agents a WHERE a.agent_key = r.agent_key) AS agent_name,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM agent_tool_requests r
            WHERE r.requested_by = %s AND r.status IN ('approved','rejected')
              AND r.acknowledged_at IS NULL
              AND (r.reviewed_by IS NULL OR r.reviewed_by != r.requested_by)
            ORDER BY r.reviewed_at ASC
            """, (user_id,))
        tool_rows = [_load(r) for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT p.name FROM policies p WHERE p.id = r.policy_id) AS policy_name
            FROM policy_change_requests r
            WHERE r.requested_by = %s AND r.status IN ('approved','rejected')
              AND r.acknowledged_at IS NULL
              AND (r.reviewed_by IS NULL OR r.reviewed_by != r.requested_by)
            ORDER BY r.reviewed_at ASC
            """, (user_id,))
        policy_rows = [_load_policy_change(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()
    labeled = []
    for r in tool_rows:
        if r.get('request_type') == 'policy':
            name = f"Policy {r.get('policy_name') or r.get('policy_id')}"
        else:
            name = r.get('agent_name') or r.get('agent_key')
        label = f"{name}: {r['status']} (+{', +'.join(r.get('added') or [])})"
        if r['status'] == 'rejected' and r.get('reason'):
            label += f": {r['reason']}"
        labeled.append((r['reviewed_at'], label))
    labeled.extend((r['reviewed_at'], _policy_change_label(r, with_status=True))
                   for r in policy_rows)
    labeled.sort(key=lambda x: (x[0] is None, x[0]))
    return {"count": len(labeled),
            "oldest": labeled[0][0] if labeled else None,
            "examples": [label for _, label in labeled[:3]]}


def acknowledge_outcomes(user_id) -> int:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cleared = 0
        for table in ('agent_tool_requests', 'policy_change_requests'):
            cursor.execute(
                f"UPDATE {table} SET acknowledged_at=UTC_TIMESTAMP() "
                f"WHERE requested_by=%s AND status IN ('approved','rejected') "
                f"AND acknowledged_at IS NULL", (user_id,))
            cleared += cursor.rowcount
        conn.commit()
        return cleared
    finally:
        cursor.close()
        conn.close()
