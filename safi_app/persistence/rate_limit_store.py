from __future__ import annotations

import logging
import time

from . import database as db

log = logging.getLogger(__name__)


def init_schema():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit_attempts (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                bucket_key VARCHAR(191) NOT NULL,
                attempted_at DOUBLE NOT NULL,
                INDEX idx_rla_bucket_time (bucket_key, attempted_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
    except Exception:
        log.exception("Rate limit schema init failed.")
    finally:
        cursor.close()
        conn.close()


def is_rate_limited(bucket_key: str, max_attempts: int, window_seconds: int) -> bool | None:
    cutoff = time.time() - window_seconds
    conn = None
    cursor = None
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM rate_limit_attempts WHERE bucket_key = %s AND attempted_at < %s",
            (bucket_key, cutoff),
        )
        cursor.execute(
            "SELECT COUNT(*) FROM rate_limit_attempts WHERE bucket_key = %s AND attempted_at >= %s",
            (bucket_key, cutoff),
        )
        count = (cursor.fetchone() or [0])[0]
        conn.commit()
        return int(count) >= int(max_attempts)
    except Exception:
        return None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def record_attempt(bucket_key: str, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    conn = None
    cursor = None
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM rate_limit_attempts WHERE bucket_key = %s AND attempted_at < %s",
            (bucket_key, cutoff),
        )
        cursor.execute(
            "INSERT INTO rate_limit_attempts (bucket_key, attempted_at) VALUES (%s, %s)",
            (bucket_key, now),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def clear_attempts(bucket_key: str) -> bool:
    conn = None
    cursor = None
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM rate_limit_attempts WHERE bucket_key = %s",
            (bucket_key,),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
