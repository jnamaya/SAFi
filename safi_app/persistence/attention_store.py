"""
The attention inbox's data plane (backlog 57): everything currently waiting
on a human, aggregated live from the tables that already hold the truth.

DERIVED, NEVER STORED. There is no notifications table and none of these
functions writes anything. A stored notification row can go stale, duplicate,
or survive the work it announced; a derived row cannot. The price is a few
indexed COUNT/MIN queries per open of the panel, which the existing indexes
(status + org_id on every source table) make cheap.

This module also grants nothing: it is read-only USB aggregation. Role
filtering happens in the API layer; every function here just answers "what
is pending in this org / for this user" and the caller decides who may see
which answer.

WHY IT IS NOT IN database.py: same boundary reasoning as mcp_store and
sharing_store. database.py is manifest-covered; a read-only summary of
pending work is not a record of what the system decided.
"""
from __future__ import annotations

import logging

from . import database as db

log = logging.getLogger(__name__)


def _one(sql, params):
    """One aggregate row: (count, oldest, examples...) style queries."""
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchone() or {}
    finally:
        cursor.close()
        conn.close()


def _column(sql, params, key):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return [row[key] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def pending_kb_documents(org_id):
    """Documents awaiting sign-off in this org's shared knowledge bases."""
    agg = _one(
        """
        SELECT COUNT(*) AS n, MIN(d.created_at) AS oldest
        FROM knowledge_base_documents d
        JOIN knowledge_bases k ON k.id = d.kb_id
        WHERE d.status = 'pending' AND k.org_id = %s
        """, (org_id,))
    examples = _column(
        """
        SELECT CONCAT(d.filename, ' (', k.name, ')') AS label
        FROM knowledge_base_documents d
        JOIN knowledge_bases k ON k.id = d.kb_id
        WHERE d.status = 'pending' AND k.org_id = %s
        ORDER BY d.created_at ASC LIMIT 3
        """, (org_id,), 'label') if agg.get('n') else []
    return {"count": int(agg.get('n') or 0), "oldest": agg.get('oldest'),
            "examples": examples}


def pending_review_items(org_id):
    """Supervisory review queue: flagged turns awaiting disposition."""
    agg = _one(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM review_queue "
        "WHERE org_id = %s AND status = 'pending'", (org_id,))
    examples = _column(
        "SELECT CONCAT('agent ', COALESCE(profile_name, 'unknown')) AS label "
        "FROM review_queue WHERE org_id = %s AND status = 'pending' "
        "ORDER BY created_at ASC LIMIT 3", (org_id,), 'label') if agg.get('n') else []
    return {"count": int(agg.get('n') or 0), "oldest": agg.get('oldest'),
            "examples": examples}


def pending_invitations(org_id):
    agg = _one(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM org_invitations "
        "WHERE org_id = %s AND accepted_at IS NULL AND revoked_at IS NULL "
        "AND expires_at > NOW()", (org_id,))
    examples = _column(
        "SELECT email AS label FROM org_invitations "
        "WHERE org_id = %s AND accepted_at IS NULL AND revoked_at IS NULL "
        "AND expires_at > NOW() ORDER BY created_at ASC LIMIT 3",
        (org_id,), 'label') if agg.get('n') else []
    return {"count": int(agg.get('n') or 0), "oldest": agg.get('oldest'),
            "examples": examples}


def open_incidents(org_id):
    agg = _one(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM security_incidents "
        "WHERE org_id = %s AND status != 'closed'", (org_id,))
    examples = _column(
        "SELECT CONCAT(title, ' (', severity, ')') AS label FROM security_incidents "
        "WHERE org_id = %s AND status != 'closed' "
        "ORDER BY created_at ASC LIMIT 3", (org_id,), 'label') if agg.get('n') else []
    return {"count": int(agg.get('n') or 0), "oldest": agg.get('oldest'),
            "examples": examples}


def failed_schedules(user_id):
    """The caller's own scheduled tasks whose last run errored. User-scoped:
    a schedule is personal, so its failure is only its owner's business."""
    agg = _one(
        "SELECT COUNT(*) AS n FROM scheduled_tasks "
        "WHERE user_id = %s AND enabled = 1 AND last_status LIKE 'error%%'",
        (user_id,))
    examples = _column(
        "SELECT CONCAT(agent_key, ': ', last_status) AS label FROM scheduled_tasks "
        "WHERE user_id = %s AND enabled = 1 AND last_status LIKE 'error%%' "
        "ORDER BY last_run_date DESC LIMIT 3", (user_id,), 'label') if agg.get('n') else []
    return {"count": int(agg.get('n') or 0), "oldest": None, "examples": examples}
