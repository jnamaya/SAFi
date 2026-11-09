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
            existing = db.get_policy(policy_id)
            if existing:
                if existing.get("is_demo") and existing.get("org_id") is None:
                    new_rules = policy.get("will_rules", [])
                    if existing.get("will_rules") != new_rules:
                        conn = db.get_db_connection()
                        cursor = conn.cursor()
                        try:
                            cursor.execute(
                                "UPDATE policies SET will_rules=%s WHERE id=%s",
                                (json.dumps(new_rules), policy_id),
                            )
                            conn.commit()
                        finally:
                            cursor.close()
                            conn.close()
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
    username = Config.LOCAL_ADMIN_USERNAME or "admin"
    display_name = username or email or "Local Admin"
    password_hash = generate_password_hash(Config.LOCAL_ADMIN_PASSWORD)

    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, org_id FROM users WHERE id='local_admin'")
        existing_user = cursor.fetchone()
        org_id = None
        if existing_user:
            org_id = existing_user.get("org_id")
            if not org_id:
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
                cursor.execute(
                    "UPDATE users SET email=%s, username=%s, name=%s, password_hash=%s, org_id=%s "
                    "WHERE id='local_admin'",
                    (email or None, username, display_name, password_hash, org_id),
                )
            else:
                cursor.execute(
                    "UPDATE users SET email=%s, username=%s, name=%s, password_hash=%s "
                    "WHERE id='local_admin'",
                    (email or None, username, display_name, password_hash),
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
                (email or None, username, display_name, authority_role, org_id,
                 password_hash, Config.DEFAULT_PROFILE),
            )

        # Synchronize password and role for any existing admin/local_admin row
        cursor.execute(
            "UPDATE users SET password_hash=%s, role='admin' "
            "WHERE id='local_admin' OR id='admin' OR username='admin'",
            (password_hash,),
        )
        conn.commit()

        if org_id:
            try:
                active_ids = [
                    policy_id for agent_key, policy_id in DEMO_AGENT_POLICY_MAP.items()
                    if Config.builtin_agent_enabled(agent_key)
                ]
                if active_ids:
                    placeholders = ",".join(["%s"] * len(active_ids))
                    cursor.execute(
                        f"UPDATE policies "
                        f"SET org_id=%s, is_demo=FALSE, created_by='local_admin' "
                        f"WHERE (org_id IS NULL OR is_demo=TRUE) AND id IN ({placeholders})",
                        (org_id, *active_ids),
                    )
                    for pid in active_ids:
                        cursor.execute("SELECT policy_config FROM policies WHERE id=%s", (pid,))
                        prow = cursor.fetchone()
                        if prow and prow.get("policy_config"):
                            pcfg = (
                                json.loads(prow["policy_config"])
                                if isinstance(prow["policy_config"], str)
                                else (prow["policy_config"] or {})
                            )
                            bu = pcfg.get("business_unit", "")
                            if " (Demo)" in bu:
                                pcfg["business_unit"] = bu.replace(" (Demo)", "").strip()
                                cursor.execute(
                                    "UPDATE policies SET policy_config=%s WHERE id=%s",
                                    (json.dumps(pcfg), pid),
                                )

                # Auto-seed standard default enterprise groups for role & agent governance
                from .persistence import sharing_store
                default_groups = [
                    ("Developers", "Software engineering and code development staff", "default"),
                    ("IT-Infrastructure", "Systems administration, servers, and network operations", "default"),
                    ("SecOps", "Security engineering, vulnerability assessment, and audit", "default"),
                    ("Cloud AI Access", "Authorized users and teams permitted to query external cloud AI models", "cloud"),
                ]
                for gname, _desc, gpolicy in default_groups:
                    try:
                        if not sharing_store.group_name_taken(org_id, gname):
                            sharing_store.create_group(org_id, gname, "local_admin", model_policy=gpolicy)
                            log.info("Bootstrapped default group '%s' (policy: %s) for org %s", gname, gpolicy, org_id)
                        elif gname == "Cloud AI Access":
                            existing = sharing_store.get_group_by_name(org_id, gname)
                            if existing and existing.get("model_policy") != "cloud":
                                sharing_store.update_group_model_policy(existing["id"], "cloud")
                    except Exception as ge:
                        log.warning("Could not auto-seed group '%s': %s", gname, ge)
                conn.commit()
            except Exception as pol_err:
                log.warning("Could not synchronize policies or groups for local admin: %s", pol_err)
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
