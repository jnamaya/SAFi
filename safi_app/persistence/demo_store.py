"""Demo-only lifecycle and usage accounting, separate from core persistence."""
from __future__ import annotations

import logging

from . import database as db

log = logging.getLogger(__name__)


def init_demo_usage_schema():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS demo_usage_daily (
                day DATE PRIMARY KEY,
                accounts INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("SELECT COUNT(*) FROM demo_usage_daily")
        if (cursor.fetchone() or [0])[0]:
            conn.commit()
            return 0
        cursor.execute("""
            INSERT INTO demo_usage_daily (day, accounts)
            SELECT DATE(ts), COUNT(DISTINCT user_id) FROM (
                SELECT user_id, created_at AS ts FROM sessions WHERE user_id LIKE 'demo\\_%'
                UNION ALL
                SELECT user_id, ts AS ts FROM auth_events WHERE user_id LIKE 'demo\\_%'
            ) usage_rows
            GROUP BY DATE(ts)
            ON DUPLICATE KEY UPDATE accounts = GREATEST(accounts, VALUES(accounts))
        """)
        filled = cursor.rowcount
        conn.commit()
        log.info("Demo usage backfill populated %d day(s).", filled)
        return filled
    except Exception:
        log.exception("Demo usage schema/backfill failed.")
        return 0
    finally:
        cursor.close()
        conn.close()


def record_demo_signup():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO demo_usage_daily (day, accounts) VALUES (CURDATE(), 1) "
            "ON DUPLICATE KEY UPDATE accounts = accounts + 1"
        )
        conn.commit()
    except Exception:
        log.warning("Demo signup was not counted.", exc_info=True)
    finally:
        cursor.close()
        conn.close()


def cleanup_orphaned_public_users():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.id FROM users u
             WHERE u.id LIKE 'public\\_%'
               AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.user_id = u.id)
               AND NOT EXISTS (SELECT 1 FROM governance_records g WHERE g.user_id = u.id)
        """)
        ids = [row[0] for row in cursor.fetchall()]
        if not ids:
            return 0
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(f"DELETE FROM users WHERE id IN ({placeholders})", tuple(ids))
        conn.commit()
        return len(ids)
    finally:
        cursor.close()
        conn.close()


def cleanup_old_demo_users():
    """Expire disposable demo work while retaining authentication evidence."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, org_id FROM users "
            "WHERE id LIKE 'demo_%' AND created_at < NOW() - INTERVAL 24 HOUR"
        )
        expired = cursor.fetchall()
        if not expired:
            return
        user_ids = [row[0] for row in expired]
        org_ids = [row[1] for row in expired if row[1]]
        if user_ids:
            placeholders = ",".join(["%s"] * len(user_ids))
            params = tuple(user_ids)
            cursor.execute(
                f"DELETE FROM governance_records WHERE user_id IN ({placeholders})", params
            )
            cursor.execute(
                "DELETE FROM chat_audit_trail WHERE conversation_id IN "
                f"(SELECT id FROM conversations WHERE user_id IN ({placeholders}))", params
            )
            for table in ("conversations", "prompt_usage", "oauth_tokens", "user_profiles", "agents"):
                cursor.execute(f"DELETE FROM {table} WHERE " + (
                    "created_by" if table == "agents" else "user_id"
                ) + f" IN ({placeholders})", params)
            cursor.execute(f"DELETE FROM users WHERE id IN ({placeholders})", params)
        if org_ids:
            placeholders = ",".join(["%s"] * len(org_ids))
            params = tuple(org_ids)
            cursor.execute(f"DELETE FROM governance_records WHERE org_id IN ({placeholders})", params)
            cursor.execute(f"DELETE FROM chat_audit_trail WHERE org_id IN ({placeholders})", params)
            for table in ("auth_events", "sessions"):
                cursor.execute(f"UPDATE {table} SET org_id=NULL WHERE org_id IN ({placeholders})", params)
            for table in (
                "llm_usage", "org_compliance_log", "knowledge_bases", "agents", "policies",
                "org_charter", "org_ai_standards", "org_invitations", "custom_groups",
                "approval_settings",
            ):
                cursor.execute(f"DELETE FROM {table} WHERE org_id IN ({placeholders})", params)
            cursor.execute(f"DELETE FROM organizations WHERE id IN ({placeholders})", params)
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("Demo cleanup failed.")
    finally:
        cursor.close()
        conn.close()
