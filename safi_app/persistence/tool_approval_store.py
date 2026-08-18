"""
Tool-grant approvals (backlog 57b): additions to an org agent's tool list
wait for a second person; removals never do.

The tool list is the capability boundary: prose is advice and values are
scored, but a tool is something the agent can DO. Widening that boundary is
the one agent edit that gets a request-and-approve workflow, on the KB
sign-off model: the author may not approve their own change, and a sole
eligible reviewer may self-approve with the non-independence recorded on the
row itself (same reasoning as knowledge_base_documents.self_approved: an
examiner reading the request's own record must see the review was not
independent without cross-referencing another table).

WHY IT IS NOT IN database.py: same boundary as the other stores. This table
is workflow state, not audit ledger; the evidence rows it produces go to
org_compliance_log, and the applied change lands on the agents row.

Writing agents.tools_json happens HERE (apply_tools) rather than through a
new helper in database.py, which is manifest-covered. The file is the TCB
boundary, not the table.
"""
from __future__ import annotations

import json
import logging
import uuid

from . import database as db
from .sharing_store import _target_collation

log = logging.getLogger(__name__)


def init_schema() -> None:
    """Create the request table if absent, collation-matched to `agents`
    (the 3e0f0ee lesson: a charset without a collation takes the server
    default and breaks the first join against the legacy schema)."""
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
        # Requester acknowledgment (backlog 57c): NULL until the requester
        # dismisses the outcome from their inbox. Workflow state on the
        # workflow row, so the inbox stays derived.
        cursor.execute("SHOW COLUMNS FROM agent_tool_requests LIKE 'acknowledged_at'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE agent_tool_requests ADD COLUMN acknowledged_at TIMESTAMP NULL")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def create_request(agent_key, org_id, requested_by, added, requested_tools) -> str:
    """Open a pending request, superseding any earlier pending request for
    the same agent: the latest ask is the only live one, or a reviewer could
    approve a stale widening the requester already walked back."""
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


def _load(row):
    if not row:
        return None
    for col in ('added', 'requested_tools'):
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
    """Requests for the reviewer view, newest last so the oldest ask is
    read first, with requester and agent display names resolved."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT u.name FROM users u WHERE u.id = r.requested_by) AS requester_name,
                   (SELECT a.name FROM agents a WHERE a.agent_key = r.agent_key) AS agent_name
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
    """The approved widening, applied to the agents row directly."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE agents SET tools_json=%s WHERE agent_key=%s",
                       (json.dumps(sorted(tools)), agent_key))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def other_reviewer_exists(org_id, exclude_user_id) -> bool:
    """Is there an eligible reviewer besides this person? When not, the
    sole-administrator exception applies and self-approval is recorded as
    non-independent rather than being a deadlock."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM users WHERE org_id=%s AND role IN ('admin','auditor') "
            "AND id != %s LIMIT 1", (org_id, exclude_user_id))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def pending_summary(org_id):
    """For the attention inbox: count, oldest, and short labels."""
    rows = list_requests(org_id, 'pending')
    examples = []
    for r in rows[:3]:
        name = r.get('agent_name') or r['agent_key']
        examples.append(f"{name}: +{', +'.join(r.get('added') or [])}")
    return {"count": len(rows),
            "oldest": rows[0]['created_at'] if rows else None,
            "examples": examples}


def unacknowledged_outcomes(user_id):
    """The caller's own decided requests they have not dismissed yet, for
    the inbox (backlog 57c). Two exclusions: superseded (the requester
    caused those themselves by filing a newer ask) and decisions the
    requester made themselves (a sole-admin self-approval is not news to
    the person who clicked Approve)."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT a.name FROM agents a WHERE a.agent_key = r.agent_key) AS agent_name
            FROM agent_tool_requests r
            WHERE r.requested_by = %s AND r.status IN ('approved','rejected')
              AND r.acknowledged_at IS NULL
              AND (r.reviewed_by IS NULL OR r.reviewed_by != r.requested_by)
            ORDER BY r.reviewed_at ASC
            """, (user_id,))
        rows = [_load(r) for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()
    examples = []
    for r in rows[:3]:
        name = r.get('agent_name') or r['agent_key']
        label = f"{name}: {r['status']} (+{', +'.join(r.get('added') or [])})"
        if r['status'] == 'rejected' and r.get('reason'):
            label += f": {r['reason']}"
        examples.append(label)
    return {"count": len(rows),
            "oldest": rows[0]['reviewed_at'] if rows else None,
            "examples": examples}


def acknowledge_outcomes(user_id) -> int:
    """Dismiss all of the caller's decided-and-unseen outcomes. Scoped to
    requested_by, so nobody can clear anyone else's inbox."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agent_tool_requests SET acknowledged_at=UTC_TIMESTAMP() "
            "WHERE requested_by=%s AND status IN ('approved','rejected') "
            "AND acknowledged_at IS NULL", (user_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()
