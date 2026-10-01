"""Application-layer bootstrap for configurable policy and account content."""
from __future__ import annotations

import json
import logging
import uuid

from werkzeug.security import generate_password_hash

from .config import Config
from .persistence import database as db
from .core.policies.demo.policies import DEMO_AGENT_POLICIES, DEMO_AGENT_POLICY_MAP
from .core.policies.safi.policy import SAFI_DEFAULT_POLICY
from .role_config import ROLE_CONFIG

log = logging.getLogger(__name__)

SAFI_POLICY_ID = "safi_default_policy"


def _seed_default_policy() -> None:
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM policies WHERE id=%s", (SAFI_POLICY_ID,))
        if cursor.fetchone():
            return
        cursor.execute(
            "INSERT INTO policies "
            "(id, org_id, name, worldview, will_rules, values_weights, created_by, is_demo) "
            "VALUES (%s, NULL, %s, %s, %s, %s, NULL, TRUE)",
            (
                SAFI_POLICY_ID,
                "SAFi Default Policy",
                SAFI_DEFAULT_POLICY.get("global_worldview", ""),
                json.dumps(SAFI_DEFAULT_POLICY.get("global_will_rules", [])),
                json.dumps(SAFI_DEFAULT_POLICY.get("global_values", [])),
            ),
        )
        conn.commit()
    except Exception:
        log.exception("Could not seed the default policy template.")
    finally:
        cursor.close()
        conn.close()


def _seed_demo_policies() -> None:
    active_ids = {
        policy_id for agent_key, policy_id in DEMO_AGENT_POLICY_MAP.items()
        if Config.builtin_agent_enabled(agent_key)
    }
    for policy_id, policy in DEMO_AGENT_POLICIES.items():
        if policy_id not in active_ids:
            continue
        try:
            if db.get_policy(policy_id):
                continue
            db.create_policy(
                name=policy["name"],
                worldview=policy.get("worldview", ""),
                will_rules=policy.get("will_rules", []),
                values=policy.get("values", []),
                policy_id=policy_id,
                policy_config={
                    "business_unit": policy.get("business_unit", ""),
                    "scope_statement": policy.get("scope_statement", ""),
                },
            )
            conn = db.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE policies SET is_demo=TRUE WHERE id=%s", (policy_id,))
                conn.commit()
            finally:
                cursor.close()
                conn.close()
        except Exception:
            log.exception("Could not seed a configured example policy.")

    # Retired seed rows remain available to historical records but not in the
    # current example-policy picker.
    visible_ids = active_ids | {SAFI_POLICY_ID}
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(visible_ids))
        cursor.execute(
            f"UPDATE policies SET is_demo=FALSE WHERE is_demo=TRUE AND org_id IS NULL "
            f"AND id NOT IN ({placeholders})",
            tuple(visible_ids),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _seed_local_admin() -> None:
    if not Config.ENABLE_LOCAL_LOGIN:
        return
    email = Config.LOCAL_ADMIN_EMAIL
    username = Config.LOCAL_ADMIN_USERNAME
    display_name = username or email or "Local Admin"
    password_hash = generate_password_hash(Config.LOCAL_ADMIN_PASSWORD)

    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE id='local_admin'")
        if cursor.fetchone():
            cursor.execute(
                "UPDATE users SET email=%s, username=%s, name=%s, password_hash=%s "
                "WHERE id='local_admin'",
                (email or None, username or None, display_name, password_hash),
            )
        else:
            cursor.execute(
                "SELECT id FROM organizations WHERE name=%s ORDER BY created_at LIMIT 1",
                ("Local Admin Organization",),
            )
            row = cursor.fetchone()
            org_id = row["id"] if row else str(uuid.uuid4())
            if not row:
                cursor.execute(
                    "INSERT INTO organizations (id, name) VALUES (%s, %s)",
                    (org_id, "Local Admin Organization"),
                )
            authority_role = (ROLE_CONFIG.get("organization_admin_roles") or [
                ROLE_CONFIG["default_role"]
            ])[0]
            cursor.execute(
                "INSERT INTO users "
                "(id, email, username, name, picture, role, org_id, password_hash, active_profile) "
                "VALUES ('local_admin', %s, %s, %s, '', %s, %s, %s, %s)",
                (email or None, username or None, display_name, authority_role, org_id,
                 password_hash, Config.DEFAULT_PROFILE),
            )
        conn.commit()
    except Exception:
        log.exception("Could not synchronize the configured local administrator.")
    finally:
        cursor.close()
        conn.close()


def initialize() -> None:
    """Seed deployment-owned configuration after the generic schema exists."""
    _seed_default_policy()
    _seed_demo_policies()
    _seed_local_admin()


def create_organization(org_name: str, user_id: str):
    """Create an organization using the deployment's selected policy template."""
    return db.create_organization_atomic(org_name, user_id, SAFI_DEFAULT_POLICY)
