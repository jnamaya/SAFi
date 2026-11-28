import hashlib
from typing import Optional, Tuple

from ..persistence import database as db


def resolve_api_key_identity(
    raw_key: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    if not raw_key:
        return None, None, None, None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    policy_id = None
    label = None
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT policy_id, label FROM api_keys WHERE key_hash=%s",
            (key_hash,),
        )
        row = cursor.fetchone()
        if not row:
            return None, None, None, None
        policy_id, label = row[0], row[1]
        try:
            cursor.execute(
                "UPDATE api_keys SET last_used_at=NOW() WHERE key_hash=%s",
                (key_hash,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
    finally:
        cursor.close()
        conn.close()

    if isinstance(label, str) and label.startswith("safi-cli:"):
        cli_uid = label.split(":", 1)[1].strip()
        if cli_uid:
            u_det = db.get_user_details(cli_uid)
            if u_det:
                return (
                    policy_id,
                    u_det.get("id"),
                    u_det.get("org_id"),
                    u_det.get("role"),
                )

    policy = db.get_policy(policy_id) or {}
    owner_id = policy.get("created_by")
    owner_role = None
    if owner_id:
        u_det = db.get_user_details(owner_id) or {}
        owner_role = u_det.get("role")
    return policy_id, owner_id, policy.get("org_id"), owner_role
