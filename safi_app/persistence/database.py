# safi_app/persistence/database.py
import mysql.connector
from mysql.connector import pooling
import json
import os
import re
import uuid
import numpy as np
from datetime import datetime, timezone
from ..timeutil import utc_isoformat
from typing import Dict, Any, Optional, List
import logging
import hashlib
import secrets
from ..config import Config
from . import crypto

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class SelfReviewError(PermissionError):
    """A reviewer tried to dispose of a turn they authored. Distinct from
    ValueError so the API can answer 403 (you are not permitted) rather than
    400 (your request was malformed) — the request was well formed, the actor
    was wrong."""


class LastAdminError(RuntimeError):
    """The change would leave an organization with no admin. Refused: an org
    with zero admins loses policy authoring, member management and the
    provider allow-list, and has no in-product way back."""


db_pool = None

def get_db_connection():
    global db_pool
    if db_pool is None:
        try:
            logging.info("Connection pool not found. Attempting to create a new one...")
            pool_size = getattr(Config, "DB_POOL_SIZE", 10)
            logging.info(f"Creating MySQL connection pool (size={pool_size}).")
            db_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="safi_pool",
                pool_size=pool_size,
                host=Config.DB_HOST,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME
            )
        except mysql.connector.Error as err:
            logging.exception("FATAL: Database connection failed.")
            raise err
    return db_pool.get_connection()

def init_db():
    conn = None
    cursor = None
    got_lock = False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        logging.info("Initializing database schema...")

        # Serialize schema creation/migration + seeding across concurrent
        # gunicorn workers. On a fresh DB all workers would otherwise race on the
        # CREATE TABLE / guarded ALTER migrations and leave a partial schema.
        try:
            cursor.execute("SELECT GET_LOCK('safi_schema_init', 60)")
            rows = cursor.fetchall()  # fully drain the result set
            got_lock = bool(rows and rows[0][0])
        except Exception:
            got_lock = False

        # --- Users ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255) UNIQUE,
                name VARCHAR(255),
                picture TEXT,
                active_profile VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP NULL,
                intellect_model VARCHAR(255) DEFAULT NULL,
                will_model VARCHAR(255) DEFAULT NULL,
                conscience_model VARCHAR(255) DEFAULT NULL,
                org_id CHAR(36),
                role ENUM('admin', 'editor', 'auditor', 'member') DEFAULT 'member'
            )
        ''')
        
        # Check if new columns exist (for migration of existing dev DBs)
        cursor.execute("SHOW COLUMNS FROM users LIKE 'org_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN org_id CHAR(36)")
            cursor.execute("ALTER TABLE users ADD COLUMN role ENUM('admin', 'editor', 'auditor', 'member') DEFAULT 'member'")
            cursor.execute("CREATE INDEX idx_user_org ON users(org_id)")

        # Add password_hash column for local account login
        cursor.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) DEFAULT NULL")

        # TOTP MFA for local accounts (enterprise identity Phase 2).
        # totp_secret holds Fernet ciphertext; enabled only once the user has
        # confirmed a live code (totp_enabled_at set).
        cursor.execute("SHOW COLUMNS FROM users LIKE 'totp_secret'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT DEFAULT NULL")
            cursor.execute("ALTER TABLE users ADD COLUMN totp_enabled_at DATETIME DEFAULT NULL")

        # --- Conversations ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id CHAR(36) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                title VARCHAR(255),
                memory_summary MEDIUMTEXT,
                is_pinned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # Titles are encrypted at rest (2026-07-21, Phase F): a Fernet token
        # over a 255-char plaintext needs ~420 chars, so the column widens to
        # 512. Plaintext is capped at 255 on write to guarantee fit.
        cursor.execute(
            "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='conversations' AND COLUMN_NAME='title'")
        _tlen = cursor.fetchone()
        if _tlen and _tlen[0] and _tlen[0] < 512:
            cursor.execute("ALTER TABLE conversations MODIFY title VARCHAR(512)")
            logging.info("Encryption migration: widened conversations.title to VARCHAR(512)")

        # --- Projects (workspaces that group conversations) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id CHAR(36) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # Add project_id to conversations (guarded migration). ON DELETE SET NULL
        # so deleting a project never destroys its chats — they just go loose.
        cursor.execute("SHOW COLUMNS FROM conversations LIKE 'project_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE conversations ADD COLUMN project_id CHAR(36) NULL")
            cursor.execute(
                "ALTER TABLE conversations ADD CONSTRAINT fk_conv_project "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL"
            )

        # --- Saved content (snapshots of individual AI responses) ---
        # Content and governance metadata are copied at save time so a saved
        # item survives deletion of its source conversation (chat_history
        # rows cascade away with the conversation). conversation_id is a soft
        # pointer for "jump to origin" — deliberately no FK so it can dangle.
        # Shipped briefly as saved_answers; rename preserves any early rows.
        cursor.execute("SHOW TABLES LIKE 'saved_answers'")
        if cursor.fetchone():
            cursor.execute("SHOW TABLES LIKE 'saved_content'")
            if not cursor.fetchone():
                cursor.execute("RENAME TABLE saved_answers TO saved_content")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_content (
                id CHAR(36) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                project_id CHAR(36) NULL,
                conversation_id CHAR(36) NULL,
                message_id CHAR(36) NOT NULL,
                title VARCHAR(255),
                content MEDIUMTEXT,
                profile_name VARCHAR(50),
                spirit_score INT,
                conscience_ledger LONGTEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_saved_user_message (user_id, message_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            )
        ''')

        # --- Scheduled tasks (personal agent digests, backlog 54) ---
        # Per-user: an agent, a prompt, a local time + weekday set. The runner
        # executes each due task as a FULL governed turn and emails the
        # approved output to the owner's account email — delivery is USB
        # plumbing for an approved response (the bot pattern), never an agent
        # tool call. conversation_id keeps every digest in a chat thread the
        # user can open, so scheduled turns are as visible as typed ones.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id CHAR(36) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                agent_key VARCHAR(255) NOT NULL,
                prompt TEXT NOT NULL,
                time_of_day CHAR(5) NOT NULL,
                days VARCHAR(32) NOT NULL,
                timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
                enabled TINYINT(1) DEFAULT 1,
                conversation_id CHAR(36) NULL,
                last_run_date CHAR(10) NULL,
                last_status VARCHAR(255) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # --- Organizations ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id CHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                owner_id VARCHAR(255),
                domain_verified BOOLEAN DEFAULT FALSE,
                domain_to_verify VARCHAR(255),
                verification_token VARCHAR(255),
                global_policy_id VARCHAR(255),
                settings JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
            )
        ''')

        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'owner_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE organizations ADD COLUMN owner_id VARCHAR(255)")
            cursor.execute("ALTER TABLE organizations ADD COLUMN settings JSON")
            cursor.execute("ALTER TABLE organizations ADD CONSTRAINT fk_org_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL")

        # --- Org Charter ---
        # Mission and core values only: organizational identity. How the org's
        # AI must behave is a different artifact — see org_ai_standards below.
        # Keeping them apart matters because a charter is something every
        # organization has, while AI standards are optional and AI-specific, and
        # because a rule filed as a "core value" gets SCORED. That is how a
        # required disclosure once became a value that blocked every turn.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS org_charter (
                org_id CHAR(36) PRIMARY KEY,
                mission TEXT,
                core_values JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        ''')

        # --- Org AI Standards ---
        # The org-wide half of what the Will enforces deterministically, plus
        # non-negotiable standards. Deliberately NO scored values: an org-wide
        # rule is either binding or it belongs to a business unit, and adding a
        # third scored tier would change the alignment aggregate for every
        # existing organization.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS org_ai_standards (
                org_id CHAR(36) PRIMARY KEY,
                values_json JSON,
                structural_requirements JSON,
                early_prompt_blacklist JSON,
                allowed_tools JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        ''')

        # Migration: AI standards briefly lived ON the charter — as three
        # columns, and as hard-gate entries inside core_values. Move both out,
        # then drop the columns. Guarded on the column still existing, so this
        # runs once and is a no-op afterwards.
        cursor.execute("SHOW COLUMNS FROM org_charter LIKE 'structural_requirements'")
        if cursor.fetchone():
            cursor.execute(
                "SELECT org_id, core_values, structural_requirements, "
                "early_prompt_blacklist, allowed_tools, created_by FROM org_charter"
            )
            for org_id, core_values, struct, blacklist, tools, created_by in cursor.fetchall():
                def _load(raw, empty):
                    if raw is None:
                        return empty
                    return json.loads(raw) if isinstance(raw, (str, bytes)) else raw

                values = _load(core_values, []) or []
                # A charter value flagged hard_gate is an AI rule, not an
                # identity value — that is the conflation being undone.
                gates = [v for v in values if isinstance(v, dict) and v.get("hard_gate")]
                identity = [v for v in values if not (isinstance(v, dict) and v.get("hard_gate"))]

                # Merge, never "first write wins". An earlier version used
                # ON DUPLICATE KEY UPDATE org_id = org_id, which silently
                # discarded the gates when a standards row already existed — and
                # then stripped them from core_values anyway, losing them
                # outright. Read what is there and union it.
                cursor.execute(
                    "SELECT values_json, structural_requirements, early_prompt_blacklist, "
                    "allowed_tools FROM org_ai_standards WHERE org_id = %s", (org_id,))
                existing = cursor.fetchone()
                if existing:
                    ex_vals = _load(existing[0], []) or []
                    seen = {str((v or {}).get("name") or "").strip().lower() for v in ex_vals}
                    merged_gates = ex_vals + [
                        g for g in gates
                        if str(g.get("name") or g.get("value") or "").strip().lower() not in seen
                    ]
                    merged_struct = {**(_load(struct, {}) or {}), **(_load(existing[1], {}) or {})}
                    ex_bl = _load(existing[2], []) or []
                    merged_bl = ex_bl + [b for b in (_load(blacklist, []) or []) if b not in ex_bl]
                    merged_tools = existing[3] if existing[3] is not None else tools
                else:
                    merged_gates = gates
                    merged_struct = _load(struct, {}) or {}
                    merged_bl = _load(blacklist, []) or []
                    merged_tools = tools

                cursor.execute(
                    """
                    INSERT INTO org_ai_standards
                        (org_id, values_json, structural_requirements,
                         early_prompt_blacklist, allowed_tools, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        values_json = VALUES(values_json),
                        structural_requirements = VALUES(structural_requirements),
                        early_prompt_blacklist = VALUES(early_prompt_blacklist),
                        allowed_tools = VALUES(allowed_tools)
                    """,
                    (org_id, json.dumps(merged_gates), json.dumps(merged_struct),
                     json.dumps(merged_bl),
                     json.dumps(merged_tools) if merged_tools is not None else None,
                     created_by),
                )
                # Only strip the gates from the charter once they are safely
                # stored, so a failure here cannot lose them from both places.
                if gates:
                    cursor.execute(
                        "UPDATE org_charter SET core_values = %s WHERE org_id = %s",
                        (json.dumps(identity), org_id),
                    )

            for col in ("structural_requirements", "early_prompt_blacklist", "allowed_tools"):
                cursor.execute(f"ALTER TABLE org_charter DROP COLUMN {col}")

        # --- Policies ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                id VARCHAR(255) PRIMARY KEY,
                org_id CHAR(36),
                name VARCHAR(255) NOT NULL,
                worldview TEXT,
                will_rules JSON,
                values_weights JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                is_demo BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE SET NULL
            )
        ''')

        cursor.execute("SHOW COLUMNS FROM policies LIKE 'policy_config'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE policies ADD COLUMN policy_config JSON")

        # --- Schema Migration for Readable Policy IDs (CHAR 36 -> VARCHAR 255) ---
        cursor.execute("SHOW COLUMNS FROM policies LIKE 'id'")
        col = cursor.fetchone()
        if col and 'char(36)' in str(col[1]).lower():
            logging.info("Migrating Policy IDs to VARCHAR(255)...")
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            cursor.execute("ALTER TABLE policies MODIFY id VARCHAR(255)")
            cursor.execute("ALTER TABLE api_keys MODIFY policy_id VARCHAR(255)")
            cursor.execute("ALTER TABLE organizations MODIFY global_policy_id VARCHAR(255)")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")

        # --- POLICY VERSIONS (history / restore) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policy_versions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                policy_id VARCHAR(255) NOT NULL,
                version INT NOT NULL,
                name VARCHAR(255),
                worldview TEXT,
                will_rules JSON,
                values_weights JSON,
                policy_config JSON,
                note VARCHAR(500),
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_policy_version (policy_id, version)
            )
        ''')
        # No FK to policies: version snapshots are self-contained and immutable, and must
        # survive policy deletion so an auditor can always retrieve the exact version that
        # ran. Drop the legacy CASCADE FK on existing installs.
        cursor.execute("""
            SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'policy_versions'
              AND REFERENCED_TABLE_NAME = 'policies' LIMIT 1
        """)
        _pv_fk = cursor.fetchone()
        if _pv_fk:
            cursor.execute(f"ALTER TABLE policy_versions DROP FOREIGN KEY {_pv_fk[0]}")
            logging.info("Dropped policy_versions FK; version history now survives policy deletion.")
        cursor.execute("SHOW COLUMNS FROM policies LIKE 'version'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE policies ADD COLUMN version INT NOT NULL DEFAULT 1")
        # Backfill a v1 snapshot for any pre-existing policy that has no history yet.
        cursor.execute('''
            INSERT INTO policy_versions (policy_id, version, name, worldview, will_rules, values_weights, policy_config, note)
            SELECT p.id, 1, p.name, p.worldview, p.will_rules, p.values_weights, p.policy_config, 'Initial version (backfilled)'
            FROM policies p
            LEFT JOIN policy_versions pv ON pv.policy_id = p.id
            WHERE pv.id IS NULL
        ''')

        # --- AGENTS TABLE ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agents (
                agent_key VARCHAR(100) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                avatar TEXT,
                worldview TEXT,
                style TEXT,
                values_json JSON,
                will_rules_json JSON,
                policy_id VARCHAR(255) DEFAULT 'standalone',
                created_by VARCHAR(255),
                org_id CHAR(36),
                visibility ENUM('private', 'member', 'auditor', 'editor', 'admin') DEFAULT 'private',
                rag_knowledge_base VARCHAR(255),
                rag_format_string TEXT,
                scope_statement TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        ''')

        # Check for new columns in agents table
        cursor.execute("SHOW COLUMNS FROM agents LIKE 'org_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN org_id CHAR(36)")
            cursor.execute("ALTER TABLE agents ADD COLUMN visibility ENUM('private', 'member', 'auditor', 'editor', 'admin') DEFAULT 'private'")
            cursor.execute("CREATE INDEX idx_agent_org ON agents(org_id)")

        cursor.execute("SHOW COLUMNS FROM agents LIKE 'rag_knowledge_base'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN rag_knowledge_base VARCHAR(255)")
            cursor.execute("ALTER TABLE agents ADD COLUMN rag_format_string TEXT")

        cursor.execute("SHOW COLUMNS FROM agents LIKE 'tools_json'")
        if not cursor.fetchone():
             cursor.execute("ALTER TABLE agents ADD COLUMN tools_json JSON")

        cursor.execute("SHOW COLUMNS FROM agents LIKE 'scope_statement'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN scope_statement TEXT")

        # --- Check for AI Model Columns (Missing in initial migration) ---
        cursor.execute("SHOW COLUMNS FROM agents LIKE 'intellect_model'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN intellect_model VARCHAR(100)")
            cursor.execute("ALTER TABLE agents ADD COLUMN will_model VARCHAR(100)")
            cursor.execute("ALTER TABLE agents ADD COLUMN conscience_model VARCHAR(100)")

        cursor.execute("SHOW COLUMNS FROM agents LIKE 'max_agent_turns'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN max_agent_turns INT DEFAULT NULL")

        # Per-agent work/task context memory toggle (default ON for custom agents).
        cursor.execute("SHOW COLUMNS FROM agents LIKE 'track_work_context'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN track_work_context BOOLEAN DEFAULT TRUE")

        # --- Knowledge Bases (user-created RAG corpora) ---
        # `id` is a server-generated UUID and is ALSO the on-disk index
        # filename. That is deliberate and load-bearing: Retriever builds its
        # path as os.path.join(VECTOR_STORE_PATH, f"{name}.index") with no
        # sanitising, so a user-supplied name would be a path-traversal read
        # primitive. The display name lives in `name` and never reaches the
        # filesystem. Do not "improve" this into a slug.
        #
        # No FKs (house style). agents.rag_knowledge_base holds this id.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id CHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                org_id CHAR(36) NULL,
                created_by VARCHAR(255) NOT NULL,
                visibility ENUM('private', 'member', 'auditor', 'editor', 'admin')
                    DEFAULT 'private',
                status ENUM('empty', 'pending', 'indexing', 'ready', 'failed')
                    DEFAULT 'empty',
                status_detail TEXT NULL,
                chunk_count INT DEFAULT 0,
                indexed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_kb_org (org_id),
                INDEX idx_kb_owner (created_by)
            )
        ''')

        # --- Knowledge Base Documents ---
        # Approval columns exist from v1 even though private KBs never use
        # them (approval attaches to SHARING, not to documents as such — a
        # private KB has no eligible approver, and self-approval is exactly
        # what separation of duties forbids). Storing them now means v2 org
        # sharing is a workflow addition, not a migration of live rows.
        #
        # `content_enc` holds the extracted text, Fernet-encrypted, so the
        # corpus can be re-indexed without keeping the original upload on
        # disk and so purge/erasure has one authoritative place to delete.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_base_documents (
                id CHAR(36) PRIMARY KEY,
                kb_id CHAR(36) NOT NULL,
                filename VARCHAR(512) NOT NULL,
                size_bytes BIGINT DEFAULT 0,
                char_count INT DEFAULT 0,
                sha256 CHAR(64) NULL,
                content_enc LONGTEXT NULL,
                uploaded_by VARCHAR(255) NOT NULL,
                status ENUM('private', 'pending', 'approved', 'rejected')
                    DEFAULT 'private',
                reviewed_by VARCHAR(255) NULL,
                reviewer_email VARCHAR(255) NULL,
                reviewed_at TIMESTAMP NULL,
                reason_enc MEDIUMTEXT NULL,
                self_approved BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_kbdoc_kb (kb_id, status),
                INDEX idx_kbdoc_sha (kb_id, sha256)
            )
        ''')

        # self_approved marks a sign-off taken under the sole-administrator
        # exception. It lives on the RECORD, not only in org_compliance_log,
        # because an examiner reading the document's own history must be able
        # to see that the review was not independent without cross-referencing
        # a separate table.
        cursor.execute("SHOW COLUMNS FROM knowledge_base_documents LIKE 'self_approved'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE knowledge_base_documents "
                           "ADD COLUMN self_approved BOOLEAN DEFAULT FALSE")

        # --- API Keys ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash VARCHAR(64) PRIMARY KEY,
                policy_id VARCHAR(255) NOT NULL,
                label VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP NULL,
                FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE
            )
        ''')

        # Widen legacy api_keys.policy_id (CHAR(36), sized for UUIDs) to
        # VARCHAR(255) so it can hold readable slug policy IDs, matching
        # policies.id and agents.policy_id. Without this, creating a policy
        # whose generated ID exceeds 36 chars writes the policies row but fails
        # the api_keys insert ("Data too long for column 'policy_id'").
        cursor.execute("SHOW COLUMNS FROM api_keys LIKE 'policy_id'")
        _ak_col = cursor.fetchone()
        if _ak_col and 'char(36)' in str(_ak_col[1]).lower():
            # The column is part of a foreign key, so drop it, widen, re-add.
            cursor.execute("""
                SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'api_keys'
                  AND COLUMN_NAME = 'policy_id' AND REFERENCED_TABLE_NAME = 'policies'
            """)
            _ak_fk = cursor.fetchone()
            if _ak_fk:
                cursor.execute(f"ALTER TABLE api_keys DROP FOREIGN KEY {_ak_fk[0]}")
            cursor.execute("ALTER TABLE api_keys MODIFY policy_id VARCHAR(255) NOT NULL")
            cursor.execute(
                "ALTER TABLE api_keys ADD CONSTRAINT api_keys_ibfk_1 "
                "FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE"
            )
            logging.info("Migrated api_keys.policy_id CHAR(36) -> VARCHAR(255).")

        # --- Chat History ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INT PRIMARY KEY AUTO_INCREMENT,
                conversation_id CHAR(36) NOT NULL,
                message_id CHAR(36) UNIQUE,
                role VARCHAR(20) NOT NULL,
                content MEDIUMTEXT,
                audit_status VARCHAR(20),
                conscience_ledger LONGTEXT,
                spirit_score INT,
                drift FLOAT DEFAULT NULL,
                spirit_note MEDIUMTEXT,
                profile_name VARCHAR(50),
                policy_id VARCHAR(255) DEFAULT NULL,
                policy_version INT DEFAULT NULL,
                profile_values JSON,
                suggested_prompts JSON DEFAULT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                INDEX idx_message_id (message_id)
            )
        ''')

        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'suggested_prompts'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN suggested_prompts JSON DEFAULT NULL")

        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'reasoning_log'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN reasoning_log LONGTEXT DEFAULT NULL")

        # Consistency metric: Spirit's per-turn drift used to live only in the
        # JSON governance logs, so nothing DB-backed (frontend, examiner export)
        # could reconstruct a Consistency trend. NULL means "no drift computed"
        # (first turn, redirects, system-failure notices) and renders as N/A.
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'drift'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN drift FLOAT DEFAULT NULL AFTER spirit_score")

        # Governance provenance: which policy (and version) was in force when
        # this turn was audited. Point-in-time record — survives policy renames,
        # reassignment, and agent switches. NULL/'standalone' = ungoverned turn.
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'policy_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN policy_id VARCHAR(255) DEFAULT NULL AFTER profile_name")
            cursor.execute("ALTER TABLE chat_history ADD COLUMN policy_version INT DEFAULT NULL AFTER policy_id")

        # Model provenance: which provider/model actually served each faculty
        # for this turn (JSON string: {"intellect": "groq/…", "conscience": …}).
        # Companion to policy_id/policy_version — the policy says which rules
        # governed the turn, this says which model produced/audited it under
        # those rules. NULL = pre-migration turn or redirect without audit.
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'model_attribution'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN model_attribution VARCHAR(512) DEFAULT NULL AFTER policy_version")

        # Will provenance: the enforcement decision that terminated this turn
        # ('approve'|'violation'|'redirected') and the gate that determined it
        # ('phase_zero'|'structure'|'audit'|'hard_gate'|'spirit'). Previously
        # this lived only in the JSONL governance logs, so "list all hard-gate
        # blocks last quarter" had no DB-backed answer. NULL = pre-Phase-E turn
        # (reports must render it as unknown, never as approved); on approved
        # turns will_stage is NULL except 'spirit' for a low-alignment commit.
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'will_decision'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN will_decision VARCHAR(16) DEFAULT NULL AFTER model_attribution")
            cursor.execute("ALTER TABLE chat_history ADD COLUMN will_stage VARCHAR(16) DEFAULT NULL AFTER will_decision")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prompt_usage (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id VARCHAR(255) NOT NULL,
                timestamp TIMESTAMP NOT NULL
            )
        ''')
        
        # --- SPIRIT MEMORY (Missing in your setup) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spirit_memory (
                profile_name VARCHAR(255) PRIMARY KEY,
                turn INT,
                mu JSON
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_snapshots (
                turn INT,
                user_id VARCHAR(255),
                hash VARCHAR(64) PRIMARY KEY,
                snapshot JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # --- Chat Audit Trail (SEA Rule 17a-4(f)(2)(i)(A) audit-trail alternative) ---
        # Append-only, hash-chained journal of every create/modify/delete that
        # touches chat_history, with a timestamp and actor per entry. No foreign
        # keys: entries must survive the cascade deletes they document so a
        # deleted record can still be re-created for its full retention period.
        # state is LONGTEXT, not JSON: MySQL normalizes JSON documents (key
        # order, number formatting), which would break byte-exact verification
        # of entry_hash. See docs/internal/SEC_COMPLIANCE_READINESS.md.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_audit_trail (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                message_pk INT NOT NULL,
                message_id CHAR(36),
                conversation_id CHAR(36) NOT NULL,
                action VARCHAR(16) NOT NULL,
                actor VARCHAR(255) NOT NULL,
                state LONGTEXT,
                event_at VARCHAR(40) NOT NULL,
                prev_hash VARCHAR(64),
                entry_hash VARCHAR(64) NOT NULL,
                org_id CHAR(36) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_trail_message (message_pk),
                INDEX idx_trail_conversation (conversation_id),
                INDEX idx_trail_org (org_id, message_pk, created_at)
            )
        ''')

        # org_id on the trail is UNAUTHENTICATED routing metadata for the
        # retention purge (entry_hash does not cover it) — never treat it as
        # evidence. Backfilled incrementally by scripts/retention_purge.py.
        cursor.execute("SHOW COLUMNS FROM chat_audit_trail LIKE 'org_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_audit_trail ADD COLUMN org_id CHAR(36) NULL")
            cursor.execute("ALTER TABLE chat_audit_trail ADD INDEX idx_trail_org (org_id, message_pk, created_at)")
            logging.info("Retention migration: added chat_audit_trail.org_id + idx_trail_org")

        # Purge queries select by age; these columns were unindexed.
        for _tbl, _idx, _cols in [
            ("chat_history", "idx_ch_conv_ts", "(conversation_id, timestamp)"),
            ("conversations", "idx_conv_created", "(created_at)"),
        ]:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
                (_tbl, _idx),
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"ALTER TABLE {_tbl} ADD INDEX {_idx} {_cols}")
                logging.info(f"Retention migration: added index {_idx} on {_tbl}")

        # --- Security Incidents (SEC Reg S-P, 17 CFR 248.30) ---
        # Incident records are examiner-facing evidence with their own retention
        # obligations, so like policy_versions they carry NO foreign keys: they
        # must survive org/user deletion. There is deliberately no delete helper
        # or endpoint — closing an incident is a status change.
        # firm_aware_at drives the 30-day customer-notification clock (the rule
        # runs from when the covered institution becomes AWARE, not occurrence).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS security_incidents (
                id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                severity VARCHAR(20) DEFAULT 'medium',
                occurred_at DATETIME NULL,
                occurred_range_end DATETIME NULL,
                firm_aware_at DATETIME NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'internal',
                vendor_name VARCHAR(255) NULL,
                vendor_aware_at DATETIME NULL,
                vendor_notified_firm_at DATETIME NULL,
                data_types JSON,
                affected_scope TEXT,
                affected_user_ids JSON,
                assessment_notes TEXT,
                containment_notes TEXT,
                harm_assessment TEXT,
                harm_determination VARCHAR(40) NULL,
                harm_determined_by VARCHAR(255) NULL,
                harm_determined_at DATETIME NULL,
                ag_delay BOOLEAN DEFAULT FALSE,
                ag_delay_reference VARCHAR(500) NULL,
                ag_delay_until DATETIME NULL,
                customers_notified_at DATETIME NULL,
                regimes JSON NULL,
                eu_incident_class VARCHAR(40) NULL,
                hipaa_role VARCHAR(20) NULL,
                affected_count INT NULL,
                authority_notified_at DATETIME NULL,
                individuals_notified_at DATETIME NULL,
                hhs_notified_at DATETIME NULL,
                media_notified_at DATETIME NULL,
                ce_notified_at DATETIME NULL,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_incident_org (org_id)
            )
        ''')

        # Regime generalization (Phase D): which notification regimes an
        # incident is reportable under (NULL = legacy row, reads as reg_sp),
        # the per-regime clock inputs, and one stop timestamp per regime
        # notice (stamped by the matching *_notified event, like
        # customers_notified_at).
        cursor.execute("SHOW COLUMNS FROM security_incidents LIKE 'regimes'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN regimes JSON NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN eu_incident_class VARCHAR(40) NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN hipaa_role VARCHAR(20) NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN affected_count INT NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN authority_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN individuals_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN hhs_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN media_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN ce_notified_at DATETIME NULL")
            logging.info("Incident migration: added regime-clock columns to security_incidents")

        # Append-only event log per incident (who/when/what, field diffs).
        # No UPDATE/DELETE helpers exist for it by construction.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS incident_events (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                incident_id CHAR(36) NOT NULL,
                org_id CHAR(36) NOT NULL,
                event_type VARCHAR(40) NOT NULL,
                detail TEXT,
                changes JSON,
                actor_id VARCHAR(255),
                actor_email VARCHAR(255),
                event_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ievent_incident (incident_id),
                INDEX idx_ievent_org (org_id)
            )
        ''')

        # --- Org Compliance Log (retention/legal-hold/export evidence) ---
        # Append-only, no FKs (survives org deletion). Records destruction and
        # production evidence as COUNTS and config diffs — never content. A
        # NULL org_id marks a global event (JSONL file purge, unattributed
        # sweep). Only append/list helpers exist by construction.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS org_compliance_log (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                org_id CHAR(36) NULL,
                event_type VARCHAR(40) NOT NULL,
                actor VARCHAR(255) NOT NULL,
                detail JSON NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_oclog_org (org_id, created_at)
            )
        ''')

        # --- LLM token usage (backlog 61, Usage & Cost tab) ---
        # One row per provider call, written fire-and-forget from
        # usage_tracking.record_usage. Plaintext by design: token counts are
        # operational telemetry, not governance evidence, and the Usage & Cost
        # tab aggregates them per org. NULL org_id = ungoverned context (no
        # active org); those rows never surface in any org's tab. No FKs
        # (house style). Dollars are computed at display time, never stored.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS llm_usage (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                org_id CHAR(36) NULL,
                agent VARCHAR(64) NULL,
                route VARCHAR(32) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                model VARCHAR(128) NOT NULL,
                tokens_in INT NOT NULL DEFAULT 0,
                tokens_out INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_llm_usage_org (org_id, created_at)
            )
        ''')

        # --- Operator-added models (backlog 63, Model Catalog section) ---
        # Extends the hardcoded Config.AVAILABLE_MODELS from the GUI. The
        # provider is EXPLICIT because detect_provider's prefix heuristics
        # default to groq: a custom id must never depend on guessable
        # spelling. Deployment-wide (models are offered to every org and
        # then filtered by each org's provider allow-list, same as built-ins).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_models (
                model_id VARCHAR(128) PRIMARY KEY,
                label VARCHAR(120) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                created_by VARCHAR(255) NULL,
                org_id VARCHAR(36) NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # org_id scopes a catalog entry to the org that added it (backlog 77).
        # Empty string, not NULL, means deployment-wide: a PRIMARY KEY column
        # cannot be NULL, and keeping the sentinel non-null lets the same
        # comparison work everywhere without an IS NULL special case.
        #
        # Rows that predate this column become deployment-wide, because there is
        # no reliable way to attribute them after the fact. They stay visible to
        # every org until an operator removes them, but they are no longer
        # deletable by a tenant admin, which was the actual defect.
        #
        # model_id stays the PRIMARY KEY, so a model id is registered once per
        # DEPLOYMENT rather than once per org. That is deliberate:
        # detect_provider() maps an id to a provider with no org in scope, and it
        # sits in the dispatch path, so allowing two orgs to claim one id with
        # different providers would make routing ambiguous. The cost is that a
        # second org adding the same id gets a collision, which discloses that
        # the id is taken but not who took it, its label, or its provider.
        cursor.execute("SHOW COLUMNS FROM custom_models LIKE 'org_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE custom_models ADD COLUMN org_id VARCHAR(36) NOT NULL DEFAULT ''")
            cursor.execute("CREATE INDEX idx_custom_models_org ON custom_models(org_id)")

        # --- Per-org provider API keys (backlog 64, BYOK over .env) ---
        # key_enc holds the Fernet-encrypted key; last4 exists so the UI can
        # say "ends in ...x4F2" without ever reading the key back. The key
        # itself leaves this table only through
        # get_org_provider_keys_decrypted, consumed at dispatch time.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS org_provider_keys (
                org_id CHAR(36) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                key_enc TEXT NOT NULL,
                last4 VARCHAR(8) NOT NULL,
                updated_by VARCHAR(255) NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (org_id, provider)
            )
        ''')

        # --- Human Review Queue (FINRA supervisory review / EU AI Act Art. 14) ---
        # Workflow state only — the regulatory evidence for each disposition is
        # the 'review' entry appended to chat_audit_trail in the same
        # transaction as the status change. One row per sampled turn even when
        # several triggers fire (triggers is a JSON array): the queue measures
        # reviewer workload, not trigger volume. No FKs (house style); rows
        # whose message_pk was retention-purged are swept by the purge script.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_queue (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                org_id CHAR(36) NOT NULL,
                message_pk INT NOT NULL,
                message_id CHAR(36) NOT NULL,
                conversation_id CHAR(36) NOT NULL,
                profile_name VARCHAR(50),
                policy_id VARCHAR(255),
                policy_version INT,
                triggers JSON NOT NULL,
                trigger_detail JSON,
                status ENUM('pending','approved','overridden') DEFAULT 'pending',
                reviewed_by VARCHAR(255) NULL,
                reviewer_email VARCHAR(255) NULL,
                reviewed_at TIMESTAMP NULL,
                reason_enc MEDIUMTEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_review_msg (message_pk),
                INDEX idx_review_org (org_id, status, created_at)
            )
        ''')

        # Append-only Art. 72 post-market-monitoring alert journal (who was
        # told what, when, and whether the webhook delivery succeeded). No
        # UPDATE/DELETE helpers exist for it by construction.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_alerts (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                org_id CHAR(36) NOT NULL,
                alert_type VARCHAR(40) NOT NULL,
                detail JSON,
                delivered JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ralerts_org (org_id, created_at)
            )
        ''')

        # --- Governance records (native Audit Hub data plane) ---
        # One encrypted record per AI turn: the full per-turn governance
        # capture (draft, reflection, will reason code, ledger, blocked draft,
        # memory/context snapshots, spirit vectors) that previously existed
        # only as plaintext JSONL on disk. Plaintext columns are exactly the
        # filter/aggregate dimensions the Hub's KPIs, trend, and explorer
        # need — decryption happens only in drill-down and downloads.
        # DELIBERATELY NO FK CASCADE from chat_history: org-attributed
        # governance records are the ORGANIZATION's supervisory evidence and
        # must survive a member deleting their conversation (otherwise a
        # flagged user could erase the org's Audit Hub evidence and skew its
        # metrics). Deletion is explicit per path: user-initiated deletes
        # remove only org_id-NULL (personal) records — the GDPR erasure
        # promise; the retention purge (legal-hold aware) is the only path
        # that destroys org records; demo cleanup removes everything
        # (disposable fixtures).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS governance_records (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                message_pk INT NOT NULL,
                message_id CHAR(36) NOT NULL,
                conversation_id CHAR(36) NOT NULL,
                org_id CHAR(36) NULL,
                user_id VARCHAR(255) NULL,
                profile_key VARCHAR(100),
                policy_id VARCHAR(255),
                policy_version INT,
                will_decision VARCHAR(16),
                will_stage VARCHAR(16),
                spirit_score DOUBLE NULL,
                drift DOUBLE NULL,
                intellect_model VARCHAR(120),
                record_enc MEDIUMTEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_gov_msg (message_pk),
                INDEX idx_gov_org_ts (org_id, created_at),
                INDEX idx_gov_profile (org_id, profile_key, created_at),
                INDEX idx_gov_policy (org_id, policy_id, created_at)
            )
        ''')

        # Migration (2026-07-21): the table originally cascaded from
        # chat_history; drop the constraint where it exists so member
        # deletions stop destroying org supervisory records.
        cursor.execute(
            "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='governance_records' "
            "AND CONSTRAINT_TYPE='FOREIGN KEY'")
        for (_fk_name,) in cursor.fetchall():
            cursor.execute(f"ALTER TABLE governance_records DROP FOREIGN KEY {_fk_name}")
            logging.info(f"Governance migration: dropped {_fk_name} — org records now survive member deletion")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id VARCHAR(255) NOT NULL,
                profile_json MEDIUMTEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id)
            )
        ''')

        # --- Agent Context Memory (per-user, per-agent long-term work memory) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_context_memory (
                user_id VARCHAR(255) NOT NULL,
                agent_id VARCHAR(255) NOT NULL,
                context_json MEDIUMTEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, agent_id)
            )
        ''')

        # --- OAuth Tokens ---
        # access_token/refresh_token are Fernet-encrypted at the accessor layer
        # (see persistence/crypto.py); scope/expires_at stay plain (needed for
        # expiry checks, not secret).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id VARCHAR(255),
                provider VARCHAR(50),
                access_token TEXT,
                refresh_token TEXT,
                expires_at TIMESTAMP NULL,
                scope TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, provider),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # --- Enterprise identity Phase 1: server-side sessions + membership ---
        # (docs/internal/DESIGN_ENTERPRISE_IDENTITY.md §3.1)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id            CHAR(43) PRIMARY KEY,
                user_id       VARCHAR(255) NOT NULL,
                org_id        VARCHAR(36) NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at    TIMESTAMP NOT NULL,
                revoked_at    TIMESTAMP NULL,
                revoked_by    VARCHAR(255) NULL,
                ip            VARCHAR(45) NULL,
                user_agent    VARCHAR(255) NULL,
                auth_context  JSON NULL,
                INDEX idx_sessions_user (user_id),
                INDEX idx_sessions_expires (expires_at)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS org_invitations (
                id          CHAR(36) PRIMARY KEY,
                org_id      VARCHAR(36) NOT NULL,
                email       VARCHAR(255) NOT NULL,
                role        ENUM('admin','editor','auditor','member') DEFAULT 'member',
                invited_by  VARCHAR(255) NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at  TIMESTAMP NOT NULL,
                accepted_at TIMESTAMP NULL,
                revoked_at  TIMESTAMP NULL,
                UNIQUE KEY uq_org_email (org_id, email)
            )
        ''')
        # Append-only, no FKs — lifecycle records must survive user/org deletion
        # (same rationale as chat_audit_trail).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_events (
                id         BIGINT PRIMARY KEY AUTO_INCREMENT,
                ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                org_id     VARCHAR(36) NULL,
                user_id    VARCHAR(255) NULL,
                session_id CHAR(43) NULL,
                event      VARCHAR(40) NOT NULL,
                detail     JSON NULL,
                actor      VARCHAR(255) NOT NULL,
                INDEX idx_auth_events_org (org_id, ts),
                INDEX idx_auth_events_user (user_id, ts)
            )
        ''')

        # --- Encryption-at-rest column migrations ---
        # Fernet ciphertext is base64 (~1.34x + 57 bytes), so TEXT columns that
        # hold encrypted content must widen to MEDIUMTEXT; JSON columns cannot
        # hold a Fernet token at all, so they become LONGTEXT (MySQL serializes
        # existing JSON to text on ALTER — legacy values stay parseable).
        # Guarded by information_schema so each ALTER runs exactly once.
        _enc_migrations = [
            ("chat_history", [("content", "mediumtext"), ("spirit_note", "mediumtext"),
                              ("conscience_ledger", "longtext"), ("reasoning_log", "longtext")]),
            ("saved_content", [("conscience_ledger", "longtext")]),
            ("conversations", [("memory_summary", "mediumtext")]),
            ("user_profiles", [("profile_json", "mediumtext")]),
            ("agent_context_memory", [("context_json", "mediumtext")]),
        ]
        for _tbl, _cols in _enc_migrations:
            _needed = []
            for _col, _target in _cols:
                cursor.execute(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                    (_tbl, _col),
                )
                _row = cursor.fetchone()
                if _row and _row[0].lower() != _target:
                    _needed.append(f"MODIFY {_col} {_target.upper()}")
            if _needed:
                cursor.execute(f"ALTER TABLE {_tbl} " + ", ".join(_needed))
                logging.info(f"Encryption migration: ALTER TABLE {_tbl} — {', '.join(_needed)}")

        conn.commit()
        logging.info("Database initialized.")

        # Ensure the SAFi default policy template exists (system-wide seed)
        _ensure_safi_policy_exists()

        # Ensure the demo business-unit policies governing the built-in demo
        # agents exist (one per agent)
        _ensure_demo_agent_policies_exist()

        # Seed persistent local admin account (if configured)
        _seed_local_admin()

    except Exception as e:
        logging.error(f"DB Init Failed: {e}")
    finally:
        try:
            if got_lock and conn:
                rel = conn.cursor()
                rel.execute("SELECT RELEASE_LOCK('safi_schema_init')")
                rel.fetchall()
                rel.close()
        except Exception:
            pass
        if cursor: cursor.close()
        if conn: conn.close()

def _ensure_safi_policy_exists():
    """
    Ensures the SAFi default policy template exists in the database.
    This is the system-wide seed used as the starting point for new organizations.
    """
    from ..core.policies.safi.policy import SAFI_DEFAULT_POLICY

    SAFI_POLICY_ID = "safi_default_policy"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM policies WHERE id = %s", (SAFI_POLICY_ID,))
        if cursor.fetchone():
            logging.info("SAFi default policy already exists.")
            return

        logging.info("Seeding SAFi default policy...")

        cursor.execute("""
            INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by, is_demo)
            VALUES (%s, NULL, %s, %s, %s, %s, NULL, TRUE)
        """, (
            SAFI_POLICY_ID,
            "SAFi Default Policy",
            SAFI_DEFAULT_POLICY.get("global_worldview", ""),
            json.dumps(SAFI_DEFAULT_POLICY.get("global_will_rules", [])),
            json.dumps(SAFI_DEFAULT_POLICY.get("global_values", [])),
        ))
        conn.commit()
        logging.info("SAFi default policy seeded.")

    except Exception as e:
        logging.error(f"Failed to seed SAFi default policy: {e}")
    finally:
        cursor.close()
        conn.close()

def _ensure_demo_agent_policies_exist():
    """
    Seeds the demo business-unit policies that govern the built-in demo agents
    (one per agent; see core/policies/demo/policies.py). Idempotent: any
    policy id already present is left untouched, so operator edits made through
    the Governance tab survive restarts. Uses create_policy() so each seed also
    gets its version-1 history row, then flips is_demo so the policies are
    visible to every user.
    """
    from ..core.policies.demo.policies import DEMO_AGENT_POLICIES, DEMO_AGENT_POLICY_MAP
    from ..config import Config

    # Only seed policies for the built-in agents enabled via SAFI_BUILTIN_AGENTS —
    # a lean install shouldn't grow governance rows for agents it never shows.
    # Already-seeded policies are left untouched (idempotency below), so enabling
    # more agents later just seeds the missing ones on the next restart.
    enabled_policy_ids = {
        pid for key, pid in DEMO_AGENT_POLICY_MAP.items()
        if Config.builtin_agent_enabled(key)
    }

    for pid, pol in DEMO_AGENT_POLICIES.items():
        try:
            if pid not in enabled_policy_ids:
                continue
            if get_policy(pid):
                continue
            create_policy(
                name=pol["name"],
                worldview=pol.get("worldview", ""),
                will_rules=pol.get("will_rules", []),
                values=pol.get("values", []),
                policy_id=pid,
                policy_config={
                    "business_unit": pol.get("business_unit", ""),
                    "scope_statement": pol.get("scope_statement", ""),
                },
            )
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE policies SET is_demo=TRUE WHERE id=%s", (pid,))
                conn.commit()
            finally:
                cursor.close()
                conn.close()
            logging.info(f"Seeded demo agent policy '{pid}'.")
        except Exception as e:
            logging.error(f"Failed to seed demo agent policy '{pid}': {e}")

# -------------------------------------------------------------------------
# LOCAL ADMIN SEEDING
# -------------------------------------------------------------------------

def _seed_local_admin():
    """
    Creates or updates the persistent local admin account from env config.
    Called once at startup. Safe to call repeatedly — always converges to
    the current SAFI_LOCAL_ADMIN_EMAIL / SAFI_LOCAL_ADMIN_PASSWORD values.
    """
    if not Config.ENABLE_LOCAL_LOGIN:
        return

    from werkzeug.security import generate_password_hash

    email    = Config.LOCAL_ADMIN_EMAIL
    password = Config.LOCAL_ADMIN_PASSWORD

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        password_hash = generate_password_hash(password)

        # Check if local admin already exists
        cursor.execute("SELECT id, org_id FROM users WHERE id = 'local_admin'")
        existing = cursor.fetchone()

        if existing:
            # Sync email and password in case env vars changed
            cursor.execute(
                "UPDATE users SET email=%s, name='Local Admin', password_hash=%s WHERE id='local_admin'",
                (email, password_hash)
            )
            logging.info("Local admin account updated.")
        else:
            # Reuse the existing local-admin org if one is already there.
            #
            # This branch runs whenever the `local_admin` USER is missing — a
            # cleanup, a purge, a test run against the wrong database — and it
            # used to mint a fresh org every time, abandoning the previous one.
            # Twenty restarts produced twenty empty "Local Admin Organization"
            # rows on the demo host, each looking like a real organization in
            # every count.
            #
            # Matched on the fixed name because that is the only stable handle
            # the old rows have; the oldest is kept so repeated recreation
            # converges on one org rather than drifting between them.
            cursor.execute(
                "SELECT id FROM organizations WHERE name = %s ORDER BY created_at LIMIT 1",
                ("Local Admin Organization",)
            )
            row = cursor.fetchone()
            org_id = row["id"] if row else None
            if org_id:
                logging.info("Reusing existing local admin organization %s", org_id)
            else:
                org_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO organizations (id, name) VALUES (%s, %s)",
                    (org_id, "Local Admin Organization")
                )
            cursor.execute(
                """INSERT INTO users (id, email, name, picture, role, org_id, password_hash, active_profile)
                   VALUES ('local_admin', %s, 'Local Admin', '', 'admin', %s, %s, %s)""",
                (email, org_id, password_hash, Config.DEFAULT_PROFILE)
            )
            logging.info("Local admin account created.")

        conn.commit()
    except Exception as e:
        logging.error(f"Failed to seed local admin: {e}")
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# SPIRIT MEMORY FUNCTIONS (These were missing!)
# -------------------------------------------------------------------------

def load_spirit_memory(profile_name: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT turn, mu FROM spirit_memory WHERE profile_name = %s", (profile_name,))
        row = cursor.fetchone()
        if row:
            turn, mu_json = row
            # Return raw object (List or Dict), let SpiritIntegrator handle type coercion
            mu_obj = json.loads(mu_json) if mu_json else {}
            return {"turn": turn, "mu": mu_obj}
        return None
    finally:
        cursor.close()
        conn.close()

def save_spirit_memory_in_transaction(cursor, profile_name: str, memory: Dict[str, Any]):
    # Accepts Dict or List, dumps to JSON
    mu_obj = memory.get('mu', {})
    if hasattr(mu_obj, 'tolist'): mu_obj = mu_obj.tolist() # Handle numpy array
    
    mu_json = json.dumps(mu_obj)
    turn = memory.get('turn', 0)
    sql = """
        INSERT INTO spirit_memory (profile_name, turn, mu)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            turn = VALUES(turn),
            mu = VALUES(mu)
    """
    cursor.execute(sql, (profile_name, turn, mu_json))

def load_and_lock_spirit_memory(conn, cursor, profile_name: str) -> Optional[Dict[str, Any]]:
    cursor.execute("START TRANSACTION")
    cursor.execute("SELECT turn, mu FROM spirit_memory WHERE profile_name = %s FOR UPDATE", (profile_name,))
    row = cursor.fetchone()
    if row:
        turn, mu_json = row
        mu_obj = json.loads(mu_json) if mu_json else {}
        return {"turn": turn, "mu": mu_obj}
    return None

def get_latest_spirit_memory(agent_id):
    """
    Wrapper for load_spirit_memory to match orchestrator call signature.
    """
    return load_spirit_memory(agent_id)


def update_spirit_memory_atomic(profile_name: str, compute_fn):
    """
    Read-modify-write spirit memory under a SELECT ... FOR UPDATE row lock.

    compute_fn receives the FRESH memory dict ({"turn": int, "mu": dict|list})
    and must return (new_mu, result); result is passed through to the caller.
    The turn counter is incremented and persisted in the same transaction, so
    concurrent turns on the same profile serialize instead of last-write-wins
    (the orchestrator's copy loaded at turn start is seconds stale by commit
    time — LLM calls sit between). Returns (result, new_turn).

    compute_fn must be pure math (no I/O) — the row lock is held while it runs.
    Retries once if the transaction fails (e.g. chosen as a deadlock victim on
    the first-turn gap lock); an exception before commit means nothing was
    applied, so the retry cannot double-count a turn.
    """
    last_exc = None
    for attempt in (1, 2):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("START TRANSACTION")
            cursor.execute(
                "SELECT turn, mu FROM spirit_memory WHERE profile_name = %s FOR UPDATE",
                (profile_name,),
            )
            row = cursor.fetchone()
            if row:
                turn, mu_json = row
                memory = {"turn": turn, "mu": json.loads(mu_json) if mu_json else {}}
            else:
                memory = {"turn": 0, "mu": {}}

            new_mu, result = compute_fn(memory)
            new_turn = int(memory.get("turn", 0)) + 1
            save_spirit_memory_in_transaction(cursor, profile_name, {"turn": new_turn, "mu": new_mu})
            conn.commit()
            return result, new_turn
        except Exception as e:
            last_exc = e
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            cursor.close()
            conn.close()
    raise last_exc

def save_spirit_memory(agent_id, mu, turn, score=None, drift=None):
    """
    Wrapper to save spirit memory. 
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Robust serialization: Handle Dict, List, or Numpy Array
        if hasattr(mu, 'tolist'): mu = mu.tolist()
        
        mu_json = json.dumps(mu)
        sql = """
            INSERT INTO spirit_memory (profile_name, turn, mu)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                turn = VALUES(turn),
                mu = VALUES(mu)
        """
        cursor.execute(sql, (agent_id, turn, mu_json))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def spirit_memory_scope(agent_id: str):
    """Who a spirit_memory row belongs to.

    spirit_memory is keyed on profile_name ALONE, so a built-in agent's baseline
    is shared by every org using it — intentionally: with an identical agent
    and policy, "how this agent expresses its values" is a property of the agent,
    and pooling gives a better-estimated baseline. Custom agents are namespaced
    by construction because their keys carry the org (`org_1022_...`).

    Returns {'shared': bool, 'orgs': n, 'users': n, 'turns': n} so a caller can
    see the blast radius before touching anything.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT COUNT(DISTINCT org_id) o, COUNT(DISTINCT user_id) u, COUNT(*) t "
            "FROM governance_records WHERE profile_key=%s", (agent_id,))
        row = cursor.fetchone() or {}
        orgs = int(row.get("o") or 0)
        # An org-prefixed key cannot collide across tenants; anything else is a
        # built-in whose baseline more than one org MAY be writing.
        shared_by_name = not str(agent_id or "").startswith("org_")
        return {
            "shared": shared_by_name,
            # The refusal condition is real blast radius, not naming: a built-in
            # used by one org (or a throwaway test fixture with no records at
            # all) has no other tenant to disturb, and refusing there would be
            # friction with no safety value.
            "cross_tenant": shared_by_name and orgs > 1,
            "orgs": orgs,
            "users": int(row.get("u") or 0),
            "turns": int(row.get("t") or 0),
        }
    finally:
        cursor.close()
        conn.close()

def reset_spirit_memory(agent_id: str, confirm_shared: bool = False):
    """
    Resets the Spirit memory for a specific agent.

    Use this when:
    - An agent's value structure has changed (added/removed values)
    - Spirit memory is corrupted (dimension mismatch)
    - You want to start fresh with a clean ethical baseline

    OPERATOR TOOL — no API route calls this. It is reachable only from a shell,
    which is why the guard below is a refusal rather than a permission check.

    For a BUILT-IN agent the baseline is shared by every org using it, so a reset
    silently moves the Consistency figures of tenants you were not thinking
    about. This used to delete unconditionally and report a bare True/False, with
    nothing to indicate how many orgs were affected. It now refuses unless
    `confirm_shared=True` and always reports the scope it found.

    Args:
        agent_id: The profile_name/agent_key to reset (a built-in key or an
            org-prefixed name)
        confirm_shared: Required to reset a shared (non org-prefixed) baseline.

    Returns:
        {'deleted': bool, 'refused': bool, 'scope': {...}} — never a bare bool,
        so the caller cannot miss the blast radius.

    Example usage:
        python -c "from safi_app.persistence.database import reset_spirit_memory; print(reset_spirit_memory('org_1022_my_agent'))"
        # shared built-in, deliberately:
        python -c "from safi_app.persistence.database import reset_spirit_memory; print(reset_spirit_memory('some_builtin_agent', confirm_shared=True))"
    """
    scope = spirit_memory_scope(agent_id)
    if scope["cross_tenant"] and not confirm_shared:
        logging.warning(
            "REFUSED spirit memory reset for shared built-in agent %s: baseline is "
            "shared by %d org(s)/%d user(s) across %d recorded turns. Pass "
            "confirm_shared=True if that is genuinely intended.",
            agent_id, scope["orgs"], scope["users"], scope["turns"])
        return {"deleted": False, "refused": True, "scope": scope}

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM spirit_memory WHERE profile_name = %s", (agent_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        if deleted and scope["shared"]:
            logging.warning(
                "Spirit memory reset for SHARED agent %s — affects %d org(s)/%d user(s).",
                agent_id, scope["orgs"], scope["users"])
        if deleted:
            logging.info(f"Spirit memory reset for agent: {agent_id}")
        else:
            logging.info(f"No Spirit memory found for agent: {agent_id}")
        return {"deleted": deleted, "refused": False, "scope": scope}
    finally:
        cursor.close()
        conn.close()


# -------------------------------------------------------------------------
# USER & CHAT FUNCTIONS
# -------------------------------------------------------------------------

def ensure_conversation_access(user_id, cid):
    """
    Checks if a conversation exists.
    If it exists, ensures user_id owns it.
    If it does NOT exist, claims it for user_id (External Bot Logic).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM conversations WHERE id=%s", (cid,))
        row = cursor.fetchone()
        if not row:
            # Auto-Create for External Bots
            cursor.execute("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'External Chat')", (cid, user_id))
            conn.commit()
            return True
        
        # Verify Owner
        return row[0] == user_id
    finally:
        cursor.close()
        conn.close()

def get_conversation_meta(cid):
    """{'user_id':..., 'project_id':...} for one conversation, or None if it
    doesn't exist. No ownership scoping — this is raw metadata for a caller
    (backlog 56's sharing resolver) that decides access itself; it does not
    decide access on its own."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT user_id, project_id FROM conversations WHERE id=%s", (cid,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def get_project_agent_profiles(pid):
    """Distinct agents (profile_name) used by any conversation currently
    filed in this project, newest-audited-turn first. A folder isn't
    agent-bound the way a single conversation is (backlog 56: it can hold
    conversations from several agents, or none), so sharing it never blocks
    on this — it exists so the share endpoint can WARN the owner when a
    grantee can't use one or more of the agents actually inside."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT ch.profile_name FROM chat_history ch "
            "JOIN conversations c ON c.id = ch.conversation_id "
            "WHERE c.project_id=%s AND ch.profile_name IS NOT NULL", (pid,))
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

def get_conversation_agent_profile(cid):
    """The agent (profile_name) of a conversation's most recent audited
    turn, or None if it has none yet. Same lookup fetch_user_conversations
    uses for the sidebar's per-chat agent label; pulled out here (backlog 56)
    so a contributor continuing a shared conversation can be governed by
    the SAME agent the conversation has used throughout, not whichever
    profile they personally have active."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT profile_name FROM chat_history "
            "WHERE conversation_id=%s AND profile_name IS NOT NULL "
            "ORDER BY id DESC LIMIT 1", (cid,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        conn.close()

def upsert_user(user_info: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        user_id = user_info.get('sub') or user_info.get('id')
        role = user_info.get('role', 'member')
        org_id = user_info.get('org_id')
        
        sql = """
            INSERT INTO users (id, email, name, picture, role, org_id, last_login)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE 
                email=VALUES(email), 
                name=VALUES(name), 
                picture=VALUES(picture), 
                last_login=NOW()
        """
        cursor.execute(sql, (user_id, user_info.get('email'), user_info.get('name'), user_info.get('picture'), role, org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def get_user_details(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def update_user_profile(user_id, profile_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET active_profile = %s WHERE id = %s", (profile_name, user_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_user_models(user_id, intellect, will, conscience):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET intellect_model=%s, will_model=%s, conscience_model=%s WHERE id=%s", (intellect, will, conscience, user_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_user_org_and_role(user_id, org_id, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET org_id=%s, role=%s WHERE id=%s", (org_id, role, user_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Deleting a user cascades users -> conversations -> chat_history, so
        # journal every chat row first or the records are unrecoverable.
        _chat_trail_snapshot_delete(
            cursor,
            "JOIN conversations c ON ch.conversation_id = c.id WHERE c.user_id=%s",
            (user_id,), f"user:{user_id}",
            org_id=_org_id_for_user(cursor, user_id),
        )
        # Account deletion erases the user's PERSONAL governance records;
        # org-attributed ones remain the organization's supervisory evidence.
        _erase_personal_governance_records(cursor, "WHERE c.user_id=%s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        cursor.execute("DELETE FROM prompt_usage WHERE user_id=%s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# --- suggested_prompts codec -------------------------------------------------
# The column is JSON-typed, so the encrypted form is a JSON *string* holding
# the Fernet token. Dual-read: legacy rows hold a plain JSON array and pass
# through unchanged (same contract as crypto.decrypt_value).

def _encode_suggested_prompts(prompts):
    if prompts is None:
        return json.dumps(None)
    return json.dumps(crypto.encrypt_value(json.dumps(prompts)))

def _decode_suggested_prompts(value):
    """Returns a Python list (or None). Accepts every historical shape:
    NULL, plain JSON array text, or a JSON string wrapping a Fernet token."""
    if value is None:
        return None
    obj = value
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8", errors="replace")
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, TypeError):
            return None
    if isinstance(obj, str):
        try:
            obj = json.loads(crypto.decrypt_value(obj))
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, list) else None

def fetch_user_conversations(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # profile_name: the agent of the conversation's most recent audited
        # turn, so the sidebar can show WHICH agent each conversation was with —
        # the one distinctly multi-agent fact a chat list can carry. A correlated
        # subquery over chat_history is fine here: the list is per-user (tens of
        # rows) and conversation_id is indexed by its foreign key.
        cursor.execute(
            "SELECT id, title, is_pinned, project_id, created_at, "
            "  (SELECT ch.profile_name FROM chat_history ch "
            "    WHERE ch.conversation_id = conversations.id "
            "      AND ch.profile_name IS NOT NULL "
            "    ORDER BY ch.id DESC LIMIT 1) AS profile_name "
            "FROM conversations WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        rows = cursor.fetchall()
        for r in rows:
            r["title"] = crypto.decrypt_value(r["title"])
        return rows
    finally:
        cursor.close()
        conn.close()

def create_conversation(user_id, project_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cid = str(uuid.uuid4())
        # Only honor project_id if the project exists and belongs to this user,
        # so a stale/spoofed id can never attach a chat to someone else's project.
        valid_project_id = None
        if project_id:
            cursor.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
            if cursor.fetchone():
                valid_project_id = project_id
        cursor.execute(
            "INSERT INTO conversations (id, user_id, title, project_id) VALUES (%s, %s, 'New Conversation', %s)",
            (cid, user_id, valid_project_id),
        )
        conn.commit()
        return {"id": cid, "title": "New Conversation", "is_pinned": False, "project_id": valid_project_id}
    finally:
        cursor.close()
        conn.close()

# --- Projects (workspaces) ---

def fetch_user_projects(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name, created_at FROM projects WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_project_meta(pid):
    """{'user_id':..., 'name':...} for one project, or None. No ownership
    scoping — raw metadata for a caller (backlog 56's sharing resolver,
    and the owner-only share-management endpoints) that decides access
    itself."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id, name FROM projects WHERE id=%s", (pid,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def create_project(user_id, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pid = str(uuid.uuid4())
        cursor.execute("INSERT INTO projects (id, user_id, name) VALUES (%s, %s, %s)", (pid, user_id, name))
        conn.commit()
        return {"id": pid, "name": name}
    finally:
        cursor.close()
        conn.close()

def rename_project(pid, name, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE projects SET name=%s WHERE id=%s AND user_id=%s", (name, pid, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def delete_project(pid, user_id):
    """Deletes the project. Conversations are preserved — the FK's ON DELETE SET
    NULL detaches them so they fall back to the loose History list."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM projects WHERE id=%s AND user_id=%s", (pid, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def move_conversation_to_project(cid, project_id, user_id):
    """Assigns a conversation to a project (or detaches it when project_id is None).
    Ownership of both the conversation and the target project is enforced."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM conversations WHERE id=%s AND user_id=%s", (cid, user_id))
        if not cursor.fetchone():
            return False
        if project_id:
            cursor.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
            if not cursor.fetchone():
                return False
        cursor.execute("UPDATE conversations SET project_id=%s WHERE id=%s AND user_id=%s", (project_id, cid, user_id))
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

# --- Saved content ---

def save_content(user_id, message_id, project_id=None):
    """Snapshots an assistant message into saved_content. Ownership is enforced
    by resolving the message through its conversation's user_id. Saving the
    same message twice updates the folder instead of duplicating."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT h.message_id, h.content, h.profile_name, h.spirit_score,
                      h.conscience_ledger, h.conversation_id, c.title AS convo_title
               FROM chat_history h
               JOIN conversations c ON c.id = h.conversation_id
               WHERE h.message_id=%s AND c.user_id=%s AND h.role='ai'""",
            (message_id, user_id),
        )
        msg = cursor.fetchone()
        if not msg or not msg.get('content'):
            return None

        valid_project_id = None
        if project_id:
            cursor.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
            if cursor.fetchone():
                valid_project_id = project_id

        # The copy INSERT below stores the SELECTed values as-is (ciphertext
        # stays ciphertext — no decrypt/re-encrypt round-trip); decrypt only
        # to derive the human-readable title.
        plain_content = crypto.decrypt_value(msg['content'])

        # Title: first non-empty line of the answer, stripped of markdown noise.
        first_line = next((l.strip() for l in plain_content.splitlines() if l.strip()), '')
        title = re.sub(r'^[#>*\-\s`]+', '', first_line)[:255] or (msg.get('convo_title') or 'Saved item')

        sid = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO saved_content
                   (id, user_id, project_id, conversation_id, message_id, title,
                    content, profile_name, spirit_score, conscience_ledger)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE project_id=VALUES(project_id)""",
            (sid, user_id, valid_project_id, msg['conversation_id'], message_id, title,
             msg['content'], msg.get('profile_name'), msg.get('spirit_score'),
             msg.get('conscience_ledger')),
        )
        conn.commit()
        cursor.execute(
            "SELECT id, project_id, conversation_id, message_id, title, created_at "
            "FROM saved_content WHERE user_id=%s AND message_id=%s",
            (user_id, message_id),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def fetch_saved_content(user_id):
    """All saved content for a user, newest first. origin_exists tells the UI
    whether 'jump to conversation' is still possible."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT s.id, s.project_id, s.conversation_id, s.message_id, s.title,
                      s.content, s.profile_name, s.spirit_score, s.conscience_ledger,
                      s.created_at, (c.id IS NOT NULL) AS origin_exists
               FROM saved_content s
               LEFT JOIN conversations c ON c.id = s.conversation_id
               WHERE s.user_id=%s
               ORDER BY s.created_at DESC""",
            (user_id,),
        )
        rows = cursor.fetchall()
        for r in rows:
            crypto.decrypt_fields(r, ("content", "conscience_ledger"))
        return rows
    finally:
        cursor.close()
        conn.close()

def move_saved_content(sid, project_id, user_id):
    """Reassigns a saved item to a project (or None to detach)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM saved_content WHERE id=%s AND user_id=%s", (sid, user_id))
        if not cursor.fetchone():
            return False
        if project_id:
            cursor.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
            if not cursor.fetchone():
                return False
        # rowcount is unreliable here (MySQL reports 0 for a no-op move), so
        # existence was checked above and the update itself is authoritative.
        cursor.execute("UPDATE saved_content SET project_id=%s WHERE id=%s AND user_id=%s",
                       (project_id, sid, user_id))
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

def delete_saved_content(sid, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM saved_content WHERE id=%s AND user_id=%s", (sid, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def fetch_chat_history_for_conversation(cid, limit=50, offset=0, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # SECURITY: when a user_id is supplied (all request-facing paths), enforce
        # ownership by joining to conversations so a user cannot read another
        # user's chat history by guessing a conversation_id. Internal/trusted
        # callers (orchestrator) pass no user_id and keep the unscoped behaviour.
        if user_id is not None:
            sql = ("SELECT ch.* FROM chat_history ch "
                   "JOIN conversations c ON ch.conversation_id = c.id "
                   "WHERE ch.conversation_id = %s AND c.user_id = %s "
                   "ORDER BY ch.id DESC LIMIT %s OFFSET %s")
            params = [cid, user_id, limit, offset]
        else:
            sql = "SELECT * FROM chat_history WHERE conversation_id = %s ORDER BY id DESC LIMIT %s OFFSET %s"
            params = [cid, limit, offset]
        cursor.execute(sql, tuple(params))
        rows = list(reversed(cursor.fetchall()))
        for r in rows:
            crypto.decrypt_fields(r, ("content", "spirit_note", "conscience_ledger", "reasoning_log"))
            if "suggested_prompts" in r:
                r["suggested_prompts"] = _decode_suggested_prompts(r["suggested_prompts"])
        return rows
    finally:
        cursor.close()
        conn.close()

# --- Chat audit trail helpers ---
# Every mutation of chat_history writes a chat_audit_trail entry inside the
# same transaction, so the record and its journal entry commit or roll back
# together. Entries for one message form a hash chain (entry_hash covers the
# payload plus prev_hash): editing or removing any past entry breaks every
# hash after it. 'update' entries store the prior values of exactly the
# fields being overwritten; 'append' entries store the appended reasoning
# step (the original is re-created by truncation); 'delete' entries store the
# full row. The demo-sandbox bulk cleanup is deliberately not journaled —
# demo chats are disposable fixtures, not business records.

_CHAT_TRAIL_ROW_FIELDS = [
    "id", "conversation_id", "message_id", "role", "content", "audit_status",
    "conscience_ledger", "spirit_score", "drift", "spirit_note", "profile_name",
    "policy_id", "policy_version",
    "profile_values", "suggested_prompts", "reasoning_log", "timestamp",
]

def trail_payload(message_pk, message_id, conversation_id, action, actor,
                  state_json, event_at, prev_hash):
    """The canonical bytes an entry's hash covers. Exactly one definition.

    The writer built this from locals and _verify_chain_entries rebuilt it from
    row dicts — two copies of the same construction, either of which could be
    edited without the other. A drift there does not fail loudly in an obvious
    place; it makes every chain unverifiable at once. Keyed field order is fixed
    by sort_keys, so this must never change for existing entries: any change is
    a new hash algorithm and needs a version marker, not an edit.

    org_id is deliberately NOT covered — it is unauthenticated routing metadata
    for the retention purge, not part of the record.
    """
    return json.dumps(
        {
            "message_pk": message_pk,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "action": action,
            "actor": actor,
            "state": state_json,
            "event_at": event_at,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
    )

def _chat_trail_append(cursor, message_pk, message_id, conversation_id, action, actor, state, org_id=None):
    """Appends one entry to chat_audit_trail on the caller's cursor/transaction.

    The FOR UPDATE on the chain tip serializes concurrent writers touching the
    same message so the chain never forks. org_id is UNAUTHENTICATED routing
    metadata for the retention purge — deliberately outside entry_hash.
    """
    cursor.execute(
        "SELECT entry_hash FROM chat_audit_trail WHERE message_pk=%s "
        "ORDER BY id DESC LIMIT 1 FOR UPDATE",
        (message_pk,),
    )
    row = cursor.fetchone()
    prev_hash = (row["entry_hash"] if isinstance(row, dict) else row[0]) if row else None
    event_at = datetime.now(timezone.utc).isoformat()
    state_json = json.dumps(state, default=str) if state is not None else None
    payload = trail_payload(message_pk, message_id, conversation_id, action,
                            actor, state_json, event_at, prev_hash)
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    cursor.execute(
        "INSERT INTO chat_audit_trail (message_pk, message_id, conversation_id, "
        "action, actor, state, event_at, prev_hash, entry_hash, org_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (message_pk, message_id, conversation_id, action, actor,
         state_json, event_at, prev_hash, entry_hash, org_id),
    )

def _org_id_for_user(cursor, user_id):
    """Resolves a user's org for trail attribution. None if unknown."""
    if not user_id:
        return None
    cursor.execute("SELECT org_id FROM users WHERE id=%s", (user_id,))
    row = cursor.fetchone()
    return (row["org_id"] if isinstance(row, dict) else row[0]) if row else None

def _chat_trail_snapshot_delete(cursor, where_sql, params, actor, org_id=None):
    """Journals a 'delete' entry (full prior row) for every chat_history row
    matched by where_sql, on the caller's cursor so the snapshots and the
    delete commit atomically. where_sql must alias chat_history as ch.

    Also stamps org_id onto the messages' EXISTING trail entries: once the
    conversation row is gone the org can no longer be derived, and the
    retention purge needs the attribution to ever reclaim these chains."""
    cols = ", ".join(f"ch.{f}" for f in _CHAT_TRAIL_ROW_FIELDS)
    cursor.execute(f"SELECT {cols} FROM chat_history ch {where_sql}", params)
    rows = cursor.fetchall()
    if org_id:
        cids = sorted({row[1] for row in rows})
        if cids:
            placeholders = ", ".join(["%s"] * len(cids))
            cursor.execute(
                f"UPDATE chat_audit_trail SET org_id=%s "
                f"WHERE conversation_id IN ({placeholders}) AND org_id IS NULL",
                (org_id, *cids),
            )
    for row in rows:
        state = dict(zip(_CHAT_TRAIL_ROW_FIELDS, row))
        _chat_trail_append(
            cursor, state["id"], state["message_id"], state["conversation_id"],
            "delete", actor, state, org_id=org_id,
        )

def _verify_chain_entries(entries):
    """Recomputes one message's trail hash chain from entries already fetched,
    ordered by id. Returns {'entries': n, 'valid': bool, 'first_bad_id': id}.

    Extracted so bulk callers (the per-item review export) can verify many
    messages from one batched query instead of one connection per message, and
    — more importantly — so they verify with EXACTLY this rule. A second copy
    of the payload construction would drift, and an export would then certify
    chains the real verifier rejects.
    """
    # The tip's stored hashes travel with the verdict so callers can show the
    # digest itself, not just our conclusion about it. Read from the row rather
    # than recomputed: the point is to expose what IS stored, so a reader can
    # compare it against an earlier export and re-walk the chain themselves.
    tip = entries[-1] if entries else None
    result = {
        "entries": len(entries),
        # No entries is an ABSENCE of evidence, not a pass. This used to return
        # True, so a purged trail rendered as a green "Chain verified" tick with
        # "0 entries recomputed" in the tooltip.
        "valid": None if not entries else True,
        "first_bad_id": None,
        "entry_hash": tip["entry_hash"] if tip else None,
        "prev_hash": tip["prev_hash"] if tip else None,
    }
    prev_hash = None
    for e in entries:
        payload = trail_payload(e["message_pk"], e["message_id"],
                                e["conversation_id"], e["action"], e["actor"],
                                e["state"], e["event_at"], prev_hash)
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if e["prev_hash"] != prev_hash or e["entry_hash"] != expected:
            result["valid"] = False
            result["first_bad_id"] = e["id"]
            return result
        prev_hash = e["entry_hash"]
    return result

def verify_message_audit_trail(message_pk):
    """Recomputes the hash chain for one chat_history row's trail entries.
    Returns {'entries': n, 'valid': bool, 'first_bad_id': id or None}."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM chat_audit_trail WHERE message_pk=%s ORDER BY id",
            (message_pk,),
        )
        return _verify_chain_entries(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()

def insert_turn_atomic(cid, user_prompt, message_id, ai_audit_status="pending"):
    """Insert a turn's user row and AI placeholder in ONE transaction.

    The AI row's message_id is UNIQUE, so a repeated or concurrent submit with
    the same message_id fails the AI insert; the whole transaction rolls back,
    taking the user row with it. This closes the double-submit race that a
    plain 'insert user, then insert ai' left open: the user row (which carries
    no unique constraint — message_id is NULL on it) used to persist even when
    the AI insert collided, leaving a duplicate prompt in history.

    Order is preserved (user row first, lower AUTO_INCREMENT id) so the
    transcript still renders user-before-assistant.

    Returns True if the turn was inserted, False if this message_id already
    exists (a double-submit to drop). Re-raises any other error.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Encrypt once: the same ciphertext goes to the DB row and the trail
        # entry so no plaintext copy exists at rest anywhere.
        enc_prompt = crypto.encrypt_value(user_prompt)
        cursor.execute("START TRANSACTION")
        cursor.execute(
            "INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (cid, "user", enc_prompt, None, None),
        )
        user_pk = cursor.lastrowid
        cursor.execute(
            "INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (cid, "ai", "", message_id, ai_audit_status),
        )
        ai_pk = cursor.lastrowid
        _chat_trail_append(cursor, user_pk, None, cid, "create",
                           "system:pipeline", {"role": "user", "content": enc_prompt})
        _chat_trail_append(cursor, ai_pk, message_id, cid, "create",
                           "system:pipeline", {"role": "ai", "content": "", "audit_status": ai_audit_status})
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        if "Duplicate entry" in str(e) and "message_id" in str(e):
            return False
        raise
    finally:
        cursor.close()
        conn.close()


def cancel_message(msg_id, user_id=None):
    """Marks a message as cancelled so the pipeline skips further processing.

    SECURITY: when a user_id is supplied (request path), only cancel a message
    that belongs to a conversation the user owns, so a user cannot cancel another
    user's in-flight message by guessing its message_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if user_id is not None:
            cursor.execute(
                "SELECT ch.id, ch.conversation_id, ch.audit_status FROM chat_history ch "
                "JOIN conversations c ON ch.conversation_id = c.id "
                "WHERE ch.message_id=%s AND c.user_id=%s FOR UPDATE",
                (msg_id, user_id),
            )
        else:
            cursor.execute(
                "SELECT id, conversation_id, audit_status FROM chat_history "
                "WHERE message_id=%s FOR UPDATE",
                (msg_id,),
            )
        row = cursor.fetchone()
        if row:
            actor = f"user:{user_id}" if user_id is not None else "system"
            _chat_trail_append(cursor, row[0], msg_id, row[1], "update",
                               actor, {"audit_status": row[2]})
        if user_id is not None:
            cursor.execute(
                "UPDATE chat_history ch JOIN conversations c ON ch.conversation_id = c.id "
                "SET ch.audit_status='cancelled' WHERE ch.message_id=%s AND c.user_id=%s",
                (msg_id, user_id),
            )
        else:
            cursor.execute("UPDATE chat_history SET audit_status='cancelled' WHERE message_id=%s", (msg_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def is_message_cancelled(msg_id):
    """Returns True if the message has been cancelled by the client."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT audit_status FROM chat_history WHERE message_id=%s", (msg_id,))
        row = cursor.fetchone()
        return row is not None and row[0] == 'cancelled'
    finally:
        cursor.close()
        conn.close()

def update_audit_results(msg_id, ledger, score, note, pname, pvals, prompts=None, drift=None,
                         policy_id=None, policy_version=None, model_attribution=None,
                         will_decision=None, will_stage=None, governance_record=None):
    # Org attribution comes from the turn's provider-governance context (set
    # once per turn via activate_org, copied into executor threads). It stamps
    # the trail entry (routing metadata, outside the hash — same contract as
    # delete snapshots) and scopes the review-sampling decision below.
    try:
        from ..core.services import provider_governance as _pg
        _org_id = _pg.active_org()
    except Exception:
        _org_id = None
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, conversation_id, conscience_ledger, audit_status, spirit_score, "
            "spirit_note, profile_name, profile_values, suggested_prompts, drift, "
            "policy_id, policy_version, model_attribution, will_decision, will_stage "
            "FROM chat_history WHERE message_id=%s FOR UPDATE",
            (msg_id,),
        )
        row = cursor.fetchone()
        if row:
            _chat_trail_append(cursor, row[0], msg_id, row[1], "update", "system:pipeline", {
                "conscience_ledger": row[2], "audit_status": row[3], "spirit_score": row[4],
                "spirit_note": row[5], "profile_name": row[6], "profile_values": row[7],
                "suggested_prompts": row[8], "drift": row[9],
                "policy_id": row[10], "policy_version": row[11],
                "model_attribution": row[12],
                "will_decision": row[13], "will_stage": row[14],
            }, org_id=_org_id)
        sql = """UPDATE chat_history SET conscience_ledger=%s, audit_status='complete', spirit_score=%s, drift=%s, spirit_note=%s, profile_name=%s, policy_id=%s, policy_version=%s, model_attribution=%s, will_decision=%s, will_stage=%s, profile_values=%s, suggested_prompts=%s WHERE message_id=%s"""
        cursor.execute(sql, (crypto.encrypt_value(json.dumps(ledger)), score, drift, crypto.encrypt_value(note),
                             pname, policy_id, policy_version, model_attribution,
                             will_decision, will_stage,
                             json.dumps(pvals), _encode_suggested_prompts(prompts), msg_id))
        # Review sampling shares this transaction so a committed turn and its
        # "was this due for review" decision are atomic — a turn can never
        # commit without its due queue row. Isolation is one-way: a sampling
        # bug must never take down the governance commit itself.
        if row:
            try:
                _maybe_enqueue_review(
                    cursor, _org_id, row[0], msg_id, row[1], pname,
                    policy_id, policy_version, score, drift,
                    will_decision, will_stage,
                )
            except Exception:
                logging.exception("Review sampling hook failed — turn commit unaffected.")
            # Governance record shares this transaction so a committed turn
            # and its encrypted per-turn capture are atomic. Same one-way
            # isolation as the sampling hook: a record-write bug must never
            # take down the governance commit itself.
            if governance_record is not None:
                try:
                    _insert_governance_record(
                        cursor, _org_id, row[0], msg_id, row[1], pname,
                        policy_id, policy_version, will_decision, will_stage,
                        score, drift, governance_record,
                    )
                except Exception:
                    logging.exception("Governance record write failed — turn commit unaffected.")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_suggested_prompts(msg_id, prompts):
    """Updates only the suggested_prompts column (used by the background
    follow-up suggester so it never blocks the request path)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, conversation_id, suggested_prompts FROM chat_history "
            "WHERE message_id=%s FOR UPDATE",
            (msg_id,),
        )
        row = cursor.fetchone()
        if row:
            _chat_trail_append(cursor, row[0], msg_id, row[1], "update",
                               "system:suggester", {"suggested_prompts": row[2]})
        cursor.execute(
            "UPDATE chat_history SET suggested_prompts=%s WHERE message_id=%s",
            (_encode_suggested_prompts(prompts), msg_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_message_content(msg_id, content, audit_status=None):
    """
    Updates the content and optionally the audit_status of an existing message.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, conversation_id, content, audit_status FROM chat_history "
            "WHERE message_id=%s FOR UPDATE",
            (msg_id,),
        )
        row = cursor.fetchone()
        if row:
            prior = {"content": row[2]}
            if audit_status:
                prior["audit_status"] = row[3]
            _chat_trail_append(cursor, row[0], msg_id, row[1], "update",
                               "system:pipeline", prior)
        enc_content = crypto.encrypt_value(content)
        if audit_status:
            sql = "UPDATE chat_history SET content=%s, audit_status=%s WHERE message_id=%s"
            cursor.execute(sql, (enc_content, audit_status, msg_id))
        else:
            sql = "UPDATE chat_history SET content=%s WHERE message_id=%s"
            cursor.execute(sql, (enc_content, msg_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_message_reasoning(msg_id, step_text, phase=None, extra=None):
    """
    Appends a new reasoning step to the message's reasoning_log.
    phase: optional tag ("gather" for agentic tool-call steps) so the
    frontend loader can map the step to a pipeline stage without
    string-matching every tool label.
    extra: optional dict merged into the step — used to journal the Will's
    verdict on a tool call (tool name, decision, reason, truncated parameters).
    Before this existed the step carried only `_tool_status()`'s human-readable
    label, so an APPROVED and a BLOCKED tool call left identical audit entries
    and a denial existed only in the application log. `step`, `timestamp` and
    `phase` are reserved and cannot be overwritten by `extra`.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Fetch existing log
        cursor.execute("SELECT id, conversation_id, reasoning_log FROM chat_history WHERE message_id=%s FOR UPDATE", (msg_id,))
        row = cursor.fetchone()
        if not row: return

        current_log = crypto.decrypt_value(row['reasoning_log'])
        if isinstance(current_log, str):
            current_log = json.loads(current_log)
        if not isinstance(current_log, list):
            current_log = []

        # 2. Append new step with timestamp
        new_step = {
            "step": step_text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if phase:
            new_step["phase"] = phase
        if extra:
            # Reserved keys win: a caller must not be able to rewrite the
            # step label or its timestamp through `extra`.
            for k, v in extra.items():
                if k not in ("step", "timestamp", "phase"):
                    new_step[k] = v
        current_log.append(new_step)

        # 3. Save back (step encrypted in the trail too — agentic tool steps
        # can embed user-derived labels, so no plaintext enters the journal)
        _chat_trail_append(cursor, row['id'], msg_id, row['conversation_id'],
                           "append", "system:pipeline",
                           {"reasoning_step_enc": crypto.encrypt_value(json.dumps(new_step))})
        cursor.execute("UPDATE chat_history SET reasoning_log=%s WHERE message_id=%s",
                       (crypto.encrypt_value(json.dumps(current_log)), msg_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

SPIRIT_HISTORY_LIMIT = 10

def _spirit_score_history(cursor, conversation_id, up_to_pk, limit=SPIRIT_HISTORY_LIMIT):
    """Scored turns in this conversation up to and including `up_to_pk`, oldest
    first — the series the Alignment Trend draws.

    Runs on the caller's cursor so it costs one extra query, not a connection.
    Nulls are excluded here rather than client-side: an unscored turn is not a
    zero, and the trend must not imply one. Capped because the chart only ever
    plots the last few points.
    """
    if not conversation_id or up_to_pk is None:
        return []
    cursor.execute(
        "SELECT spirit_score FROM chat_history "
        "WHERE conversation_id=%s AND id<=%s AND spirit_score IS NOT NULL "
        "ORDER BY id DESC LIMIT %s",
        (conversation_id, up_to_pk, limit))
    rows = cursor.fetchall()
    scores = [(r['spirit_score'] if isinstance(r, dict) else r[0]) for r in rows]
    return [float(v) for v in reversed(scores)]

def spirit_score_history_for_message(message_id, limit=SPIRIT_HISTORY_LIMIT):
    """Public wrapper: the Alignment Trend series for one message_id, oldest
    first. Opens its own connection, for callers outside a cursor scope (the
    process_prompt response). Returns [] for an unknown message rather than
    raising — a missing trend must never fail a turn."""
    if not message_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, conversation_id FROM chat_history WHERE message_id=%s",
            (message_id,))
        row = cursor.fetchone()
        if not row:
            return []
        return _spirit_score_history(cursor, row["conversation_id"], row["id"], limit)
    finally:
        cursor.close()
        conn.close()

def get_audit_result(msg_id, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Only the columns this endpoint returns — it's polled frequently, so
        # avoid pulling the full row (content + large JSON blobs) every time.
        # SECURITY: when a user_id is supplied (request path), join to
        # conversations and scope to the owner so a user cannot read another
        # user's audit ledger / reasoning log by guessing a message_id.
        if user_id is not None:
            cursor.execute(
                """SELECT ch.id, ch.conversation_id,
                          ch.audit_status, ch.conscience_ledger, ch.spirit_score, ch.drift, ch.spirit_note,
                          ch.profile_name, ch.policy_id, ch.policy_version,
                          ch.profile_values, ch.suggested_prompts, ch.reasoning_log
                   FROM chat_history ch
                   JOIN conversations c ON ch.conversation_id = c.id
                   WHERE ch.message_id=%s AND c.user_id=%s""",
                (msg_id, user_id),
            )
        else:
            cursor.execute(
                """SELECT id, conversation_id,
                          audit_status, conscience_ledger, spirit_score, drift, spirit_note,
                          profile_name, policy_id, policy_version,
                          profile_values, suggested_prompts, reasoning_log
                   FROM chat_history WHERE message_id=%s""",
                (msg_id,),
            )
        row = cursor.fetchone()
        if row:
            crypto.decrypt_fields(row, ("conscience_ledger", "spirit_note", "reasoning_log"))
            return {
                "status": row['audit_status'],
                "ledger": row['conscience_ledger'],
                "spirit_score": row['spirit_score'],
                "drift": row['drift'],
                "spirit_note": row['spirit_note'],
                "profile": row['profile_name'],
                "policy_id": row['policy_id'],
                "policy_version": row['policy_version'],
                "values": row['profile_values'],
                "suggested_prompts": _decode_suggested_prompts(row['suggested_prompts']),
                "reasoning_log": row['reasoning_log'],
                # Derived server-side on purpose. The Alignment Trend used to be
                # assembled from the client's conversation cache, which is empty
                # whenever an org disables offline persistence (the default), so
                # a compliance view silently lost its history. A governance
                # surface should not depend on client-side storage policy.
                "spirit_scores_history": _spirit_score_history(
                    cursor, row['conversation_id'], row['id']),
            }
        return None
    finally:
        cursor.close()
        conn.close()

def fetch_conversation_summary(cid, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT memory_summary FROM conversations WHERE id=%s", (cid,))
        row = cursor.fetchone()
        return crypto.decrypt_value(row[0]) if row else ""
    finally:
        cursor.close()
        conn.close()

def update_conversation_summary(cid, summary, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE conversations SET memory_summary=%s WHERE id=%s",
                       (crypto.encrypt_value(summary), cid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_conversation_title(cid):
    """Decrypted title of one conversation, or None. Exists for the background
    title generator's guard: it must never overwrite a title the user typed,
    so it re-reads the current value just before writing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title FROM conversations WHERE id=%s", (cid,))
        row = cursor.fetchone()
        return crypto.decrypt_value(row[0]) if row and row[0] is not None else None
    finally:
        cursor.close()
        conn.close()

def rename_conversation(cid, title, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # SECURITY: scope the write to the owning user when a user_id is supplied
        # (request paths) so one user cannot rename another user's conversation.
        # Titles are derived from user prompts, so they are encrypted at rest
        # like the content they summarize (dual-read: legacy plaintext rows
        # pass through crypto.decrypt_value unchanged). Plaintext is capped
        # at 255 chars so the token always fits VARCHAR(512).
        enc_title = crypto.encrypt_value((title or "")[:255])
        if user_id is not None:
            cursor.execute("UPDATE conversations SET title=%s WHERE id=%s AND user_id=%s", (enc_title, cid, user_id))
        else:
            cursor.execute("UPDATE conversations SET title=%s WHERE id=%s", (enc_title, cid))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def toggle_conversation_pin(cid, is_pinned, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # SECURITY: scope to the owning user (see rename_conversation).
        if user_id is not None:
            cursor.execute("UPDATE conversations SET is_pinned=%s WHERE id=%s AND user_id=%s", (1 if is_pinned else 0, cid, user_id))
        else:
            cursor.execute("UPDATE conversations SET is_pinned=%s WHERE id=%s", (1 if is_pinned else 0, cid))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def _erase_personal_governance_records(cursor, conversation_where_sql, params):
    """User-initiated deletion of governance records: PERSONAL (org_id NULL)
    records only — the GDPR-erasure promise. Org-attributed records are the
    organization's supervisory evidence and deliberately survive; only the
    retention purge (legal-hold aware) destroys those. conversation_where_sql
    must alias conversations as c and scope ownership."""
    cursor.execute(
        f"DELETE g FROM governance_records g "
        f"JOIN conversations c ON c.id = g.conversation_id "
        f"{conversation_where_sql} AND g.org_id IS NULL",
        params,
    )

def delete_conversation(cid, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # SECURITY: scope the delete to the owning user (see rename_conversation).
        if user_id is not None:
            _chat_trail_snapshot_delete(
                cursor,
                "JOIN conversations c ON ch.conversation_id = c.id WHERE c.id=%s AND c.user_id=%s",
                (cid, user_id), f"user:{user_id}",
                org_id=_org_id_for_user(cursor, user_id),
            )
            _erase_personal_governance_records(
                cursor, "WHERE c.id=%s AND c.user_id=%s", (cid, user_id))
            cursor.execute("DELETE FROM conversations WHERE id=%s AND user_id=%s", (cid, user_id))
        else:
            _chat_trail_snapshot_delete(
                cursor, "WHERE ch.conversation_id=%s", (cid,), "system",
            )
            _erase_personal_governance_records(cursor, "WHERE c.id=%s", (cid,))
            cursor.execute("DELETE FROM conversations WHERE id=%s", (cid,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def delete_all_conversations(user_id):
    """Clears the user's loose (non-project) conversations only. Chats filed
    inside a project are preserved — they're removed by deleting the project or
    the individual chat. This matches the trash icon's placement under History."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _chat_trail_snapshot_delete(
            cursor,
            "JOIN conversations c ON ch.conversation_id = c.id "
            "WHERE c.user_id=%s AND c.project_id IS NULL",
            (user_id,), f"user:{user_id}",
            org_id=_org_id_for_user(cursor, user_id),
        )
        _erase_personal_governance_records(
            cursor, "WHERE c.user_id=%s AND c.project_id IS NULL", (user_id,))
        cursor.execute("DELETE FROM conversations WHERE user_id=%s AND project_id IS NULL", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def verify_conversation_ownership(user_id, cid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM conversations WHERE id=%s AND user_id=%s", (cid, user_id))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()

def set_conversation_title_from_first_message(cid, msg, user_id=None):
    title = (msg[:50] + "...") if len(msg) > 50 else msg
    rename_conversation(cid, title, user_id)
    return title

def fetch_user_profile_memory(uid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT profile_json FROM user_profiles WHERE user_id=%s", (uid,))
        row = cursor.fetchone()
        return crypto.decrypt_value(row['profile_json']) if row else "{}"
    finally:
        cursor.close()
        conn.close()

def upsert_user_profile_memory(uid, data):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO user_profiles (user_id, profile_json) VALUES (%s, %s) ON DUPLICATE KEY UPDATE profile_json=VALUES(profile_json)",
                       (uid, crypto.encrypt_value(data)))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def create_scheduled_task(user_id, agent_key, prompt, time_of_day, days, timezone):
    """One scheduled digest. Ownership is the caller's user_id; validation of
    the fields is the API's job (this layer stores what it is given)."""
    import uuid as _uuid
    pid = str(_uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scheduled_tasks (id, user_id, agent_key, prompt, time_of_day, days, timezone) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (pid, user_id, agent_key, prompt, time_of_day, days, timezone)
        )
        conn.commit()
        return {"id": pid}
    finally:
        cursor.close()
        conn.close()


def fetch_scheduled_tasks(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, agent_key, prompt, time_of_day, days, timezone, enabled, "
            "conversation_id, last_run_date, last_status, created_at "
            "FROM scheduled_tasks WHERE user_id=%s ORDER BY created_at DESC",
            (user_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def fetch_enabled_scheduled_tasks():
    """All enabled tasks, for the runner. Due-ness is computed in Python per
    task timezone; the table stays free of timezone arithmetic."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, user_id, agent_key, prompt, time_of_day, days, timezone, "
            "conversation_id, last_run_date FROM scheduled_tasks WHERE enabled=1"
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def update_scheduled_task(task_id, user_id, fields):
    """Update the editable columns only. Ownership is the WHERE clause.

    Changing the TIME re-arms the once-per-day guard (last_run_date=NULL):
    a user who moves a schedule to a later time today means "fire at the new
    time", and without the reset the edit silently does nothing until
    tomorrow. Prompt or agent edits alone do not re-arm — the content
    changed, not the appointment."""
    allowed = {"prompt", "time_of_day", "days", "timezone", "enabled", "agent_key"}
    sets = {k: v for k, v in (fields or {}).items() if k in allowed}
    if not sets:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        assignments = ", ".join(f"{k}=%s" for k in sets)
        if "time_of_day" in sets or "days" in sets:
            assignments += ", last_run_date=NULL"
        cursor.execute(
            f"UPDATE scheduled_tasks SET {assignments} WHERE id=%s AND user_id=%s",
            (*sets.values(), task_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def delete_scheduled_task(task_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM scheduled_tasks WHERE id=%s AND user_id=%s",
                       (task_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def mark_scheduled_task_run(task_id, run_date, status, conversation_id=None):
    """The runner's bookkeeping: the once-per-local-day guard plus an honest
    last_status the owner can see in the UI."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if conversation_id:
            cursor.execute(
                "UPDATE scheduled_tasks SET last_run_date=%s, last_status=%s, conversation_id=%s WHERE id=%s",
                (run_date, (status or "")[:255], conversation_id, task_id)
            )
        else:
            cursor.execute(
                "UPDATE scheduled_tasks SET last_run_date=%s, last_status=%s WHERE id=%s",
                (run_date, (status or "")[:255], task_id)
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def list_agent_context_agents(user_id: str) -> list:
    """The agents holding work-context memory for this user, for the
    user-facing memory manager (backlog 50b). Ownership is the WHERE clause."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT agent_id, updated_at FROM agent_context_memory "
            "WHERE user_id=%s ORDER BY updated_at DESC",
            (user_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def delete_agent_context_memory(user_id: str, agent_id: str) -> bool:
    """Forget everything one agent remembers for this user. Forward-looking
    only: governance records keep the copies injected on past turns."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM agent_context_memory WHERE user_id=%s AND agent_id=%s",
            (user_id, agent_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def fetch_agent_context_memory(user_id: str, agent_id: str) -> str:
    """Load the per-agent work context memory for a user. Returns '{}' if none exists."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT context_json FROM agent_context_memory WHERE user_id=%s AND agent_id=%s",
            (user_id, agent_id)
        )
        row = cursor.fetchone()
        return crypto.decrypt_value(row['context_json']) if row and row['context_json'] else "{}"
    finally:
        cursor.close()
        conn.close()

def upsert_agent_context_memory(user_id: str, agent_id: str, context_json: str) -> None:
    """Create or update the per-agent work context memory for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO agent_context_memory (user_id, agent_id, context_json)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE context_json=VALUES(context_json)""",
            (user_id, agent_id, crypto.encrypt_value(context_json))
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def record_prompt_usage(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        timestamp = datetime.now(timezone.utc)
        cursor.execute("INSERT INTO prompt_usage (user_id, timestamp) VALUES (%s, %s)", (user_id, timestamp))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_todays_prompt_count(user_id: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM prompt_usage WHERE user_id = %s AND DATE(timestamp) = %s", (user_id, today_utc))
        return cursor.fetchone()[0]
    finally:
        cursor.close()
        conn.close()

def upsert_audit_snapshot(snap_hash, snapshot, turn, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        snapshot_json = json.dumps(snapshot)
        sql = """INSERT INTO audit_snapshots (hash, snapshot, turn, user_id) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE snapshot=VALUES(snapshot), turn=VALUES(turn), user_id=VALUES(user_id)"""
        cursor.execute(sql, (snap_hash, snapshot_json, turn, user_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# NEW: AGENT MANAGEMENT
# -------------------------------------------------------------------------

def create_agent(key, name, description, avatar, worldview, style, values, rules, policy_id, created_by, org_id=None, visibility='private',
                 intellect_model=None, will_model=None, conscience_model=None, rag_knowledge_base=None, rag_format_string=None, tools=None, scope_statement=None, max_agent_turns=None,
                 track_work_context=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not policy_id: policy_id = 'standalone'
        sql = """INSERT INTO agents (
            agent_key, name, description, avatar, worldview, style, values_json, will_rules_json, policy_id, created_by, org_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string, tools_json, scope_statement, max_agent_turns, track_work_context
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        cursor.execute(sql, (
            key, name, description, avatar, worldview, style, json.dumps(values), json.dumps(rules), policy_id, created_by, org_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string, json.dumps(tools or []), scope_statement or '',
            int(max_agent_turns) if max_agent_turns else None, bool(track_work_context)
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_agent(key, name, description, avatar, worldview, style, values, rules, policy_id, visibility='private',
                 intellect_model=None, will_model=None, conscience_model=None, rag_knowledge_base=None, rag_format_string=None, tools=None, scope_statement=None, max_agent_turns=None,
                 track_work_context=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not policy_id: policy_id = 'standalone'
        sql = """UPDATE agents SET
            name=%s, description=%s, avatar=%s, worldview=%s, style=%s, values_json=%s, will_rules_json=%s, policy_id=%s, visibility=%s,
            intellect_model=%s, will_model=%s, conscience_model=%s, rag_knowledge_base=%s, rag_format_string=%s, tools_json=%s, scope_statement=%s,
            max_agent_turns=%s, track_work_context=%s
            WHERE agent_key=%s"""
        cursor.execute(sql, (
            name, description, avatar, worldview, style, json.dumps(values), json.dumps(rules), policy_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string, json.dumps(tools or []), scope_statement or '',
            int(max_agent_turns) if max_agent_turns else None, bool(track_work_context),
            key
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_agent(key):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM agents WHERE agent_key=%s", (key,))
        row = cursor.fetchone()
        if row:
            row['key'] = row['agent_key']
            row['policy_id'] = row['policy_id'] or 'standalone' # FIX: Ensure never None
            row['values'] = json.loads(row['values_json']) if isinstance(row['values_json'], str) else row['values_json'] or []
            row['will_rules'] = json.loads(row['will_rules_json']) if isinstance(row['will_rules_json'], str) else row['will_rules_json'] or []
            row['tools'] = json.loads(row['tools_json']) if row.get('tools_json') and isinstance(row['tools_json'], str) else row.get('tools_json') or []
            row['track_work_context'] = bool(row.get('track_work_context', True) if row.get('track_work_context') is not None else True)

            # --- FIX: Ensure 'value' key exists for Core Engine ---
            for v in row['values']:
                if 'name' in v and 'value' not in v:
                    v['value'] = v['name']

            return row
        return None
    finally:
        cursor.close()
        conn.close()

def list_agents(user_id, org_id=None, user_role='member'):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # LOGIC:
        # 1. Always show agents created by the user (regardless of org or visibility)
        # 2. Show agents from the same org IF visibility permissions are met:
        #    - 'member' visible to everyone in org
        #    - 'auditor' visible to auditor, editor, admin
        #    - 'editor' visible to editor, admin
        #    - 'admin' visible to admin
        #    - 'private' is NOT visible to others
        
        sql = """
            SELECT * FROM agents 
            WHERE 
                (created_by = %s)
                OR 
                (
                    org_id = %s 
                    AND org_id IS NOT NULL
                    AND (
                        visibility = 'member'
                        OR (visibility = 'auditor' AND %s IN ('auditor', 'editor', 'admin'))
                        OR (visibility = 'editor' AND %s IN ('editor', 'admin'))
                        OR (visibility = 'admin' AND %s = 'admin')
                    )
                )
            ORDER BY created_at DESC
        """
        
        cursor.execute(sql, (user_id, org_id, user_role, user_role, user_role))
        rows = cursor.fetchall()
        res = []
        for row in rows:
            row['key'] = row['agent_key']
            row['values'] = json.loads(row['values_json']) if isinstance(row['values_json'], str) else row['values_json'] or []
            row['will_rules'] = json.loads(row['will_rules_json']) if isinstance(row['will_rules_json'], str) else row['will_rules_json'] or []
            row['tools'] = json.loads(row['tools_json']) if row.get('tools_json') and isinstance(row['tools_json'], str) else row.get('tools_json') or []
            
            # --- FIX: Ensure 'value' key exists here too for consistency ---
            for v in row['values']:
                if 'name' in v and 'value' not in v:
                    v['value'] = v['name']
                    
            row['is_custom'] = True
            
            # Add metadata for UI
            row['shared_with_org'] = (row['org_id'] == org_id) and (row['visibility'] != 'private')
            
            res.append(row)
        return res
        return res
    finally:
        cursor.close()
        conn.close()

def list_all_agents():
    """
    Lists ALL agents in the database, ignoring permissions.
    Used for the Dashboard/Admin view.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM agents ORDER BY created_at DESC"
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        res = []
        for row in rows:
            row['key'] = row['agent_key']
            row['values'] = json.loads(row['values_json']) if isinstance(row['values_json'], str) else row['values_json'] or []
            row['will_rules'] = json.loads(row['will_rules_json']) if isinstance(row['will_rules_json'], str) else row['will_rules_json'] or []
            row['tools'] = json.loads(row['tools_json']) if row.get('tools_json') and isinstance(row['tools_json'], str) else row.get('tools_json') or []
            
            # Ensure 'value' key exists
            for v in row['values']:
                if 'name' in v and 'value' not in v:
                    v['value'] = v['name']
                    
            row['is_custom'] = True
            res.append(row)
        return res
    finally:
        cursor.close()
        conn.close()

def delete_agent(key):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM agents WHERE agent_key=%s", (key,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# KNOWLEDGE BASES (user-created RAG corpora)
# -------------------------------------------------------------------------
# Two rules hold this together and are enforced HERE rather than in the API,
# so every future caller — batch, script, admin tooling — inherits them:
#
#   1. A document's text is only ever indexed when it is retrievable-eligible
#      (`_INDEXABLE_DOC_STATUSES`). Approval that only hides a row in the UI
#      is theatre: once text is embedded it is already answering questions.
#   2. An uploader can never approve their own document (SelfReviewError),
#      matching record_review_disposition's separation of duties.

# 'private' = a private KB, which has no approver by design. 'approved' = a
# shared KB's document that a second person signed off. Both are indexable;
# 'pending' and 'rejected' are not.
_INDEXABLE_DOC_STATUSES = ('private', 'approved')


def create_knowledge_base(name, created_by, description=None, org_id=None,
                          visibility='private'):
    """Creates an empty KB and returns its row. The UUID it generates is also
    the on-disk index filename — see the schema comment."""
    kb_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO knowledge_bases (id, name, description, org_id, created_by, "
            "visibility, status) VALUES (%s, %s, %s, %s, %s, %s, 'empty')",
            (kb_id, name, description, org_id, created_by, visibility),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_knowledge_base(kb_id)


def get_knowledge_base(kb_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM knowledge_bases WHERE id=%s", (kb_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def list_knowledge_bases(user_id, org_id=None, user_role='member'):
    """KBs the caller may see: their own always, plus org-visible ones their
    role clears. Mirrors list_agents' visibility ladder deliberately — a KB
    is an org asset of the same kind, and two different rules would be a bug
    waiting to happen."""
    role_clears = {
        'admin':   ('member', 'auditor', 'editor', 'admin'),
        'editor':  ('member', 'auditor', 'editor'),
        'auditor': ('member', 'auditor'),
        'member':  ('member',),
    }.get(user_role or 'member', ('member',))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # pending_count comes back with the row rather than from a second query
        # per card. The list view needs it: a shared KB whose documents are all
        # awaiting review has zero chunks, and a card that renders that as
        # "Empty" reads as a bug instead of as "someone needs to approve these".
        sql = """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM knowledge_base_documents d
                     WHERE d.kb_id = kb.id AND d.status = 'pending') AS pending_count
              FROM knowledge_bases kb
             WHERE kb.created_by=%s
        """
        params = [user_id]
        if org_id:
            placeholders = ', '.join(['%s'] * len(role_clears))
            sql += f" OR (kb.org_id=%s AND kb.visibility IN ({placeholders}))"
            params.append(org_id)
            params.extend(role_clears)
        sql += " ORDER BY kb.created_at DESC"
        cursor.execute(sql, tuple(params))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def update_knowledge_base(kb_id, name=None, description=None, visibility=None):
    sets, params = [], []
    if name is not None:
        sets.append("name=%s"); params.append(name)
    if description is not None:
        sets.append("description=%s"); params.append(description)
    if visibility is not None:
        sets.append("visibility=%s"); params.append(visibility)
    if not sets:
        return get_knowledge_base(kb_id)
    params.append(kb_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id=%s",
                       tuple(params))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_knowledge_base(kb_id)


def set_knowledge_base_status(kb_id, status, detail=None, chunk_count=None,
                              mark_indexed=False):
    sets = ["status=%s", "status_detail=%s"]
    params = [status, detail]
    if chunk_count is not None:
        sets.append("chunk_count=%s"); params.append(int(chunk_count))
    if mark_indexed:
        sets.append("indexed_at=NOW()")
    params.append(kb_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id=%s",
                       tuple(params))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def delete_knowledge_base(kb_id):
    """Removes the KB and its documents. The caller is responsible for
    deleting the index files — see kb_indexer.delete_kb_artifacts. Rows go
    first so a crash between the two leaves orphaned files (inert) rather
    than a KB whose documents are gone but whose vectors still answer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM knowledge_base_documents WHERE kb_id=%s", (kb_id,))
        cursor.execute("DELETE FROM knowledge_bases WHERE id=%s", (kb_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def add_knowledge_base_document(kb_id, filename, text, uploaded_by,
                                size_bytes=0, status='private'):
    """Stores one extracted document. `text` is encrypted at rest here rather
    than left on disk, so re-indexing needs no original upload and erasure has
    exactly one place to delete from."""
    doc_id = str(uuid.uuid4())
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO knowledge_base_documents (id, kb_id, filename, size_bytes, "
            "char_count, sha256, content_enc, uploaded_by, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (doc_id, kb_id, filename, int(size_bytes or 0), len(text or ""),
             digest, crypto.encrypt_value(text or ""), uploaded_by, status),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_knowledge_base_document(doc_id)


def get_knowledge_base_document(doc_id, include_text=False):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM knowledge_base_documents WHERE id=%s", (doc_id,))
        row = cursor.fetchone()
        if row:
            row = _shape_kb_document(row, include_text=include_text)
        return row
    finally:
        cursor.close()
        conn.close()


def list_knowledge_base_documents(kb_id, include_text=False, statuses=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM knowledge_base_documents WHERE kb_id=%s"
        params = [kb_id]
        if statuses:
            sql += f" AND status IN ({', '.join(['%s'] * len(statuses))})"
            params.extend(statuses)
        sql += " ORDER BY created_at ASC"
        cursor.execute(sql, tuple(params))
        return [_shape_kb_document(r, include_text=include_text)
                for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def list_indexable_documents(kb_id):
    """The indexer's input set. Deliberately the ONLY way the indexer selects
    documents, so 'approved' cannot degrade into a display flag."""
    return list_knowledge_base_documents(
        kb_id, include_text=True, statuses=_INDEXABLE_DOC_STATUSES)


def _shape_kb_document(row, include_text=False):
    """Never returns the ciphertext, and only returns plaintext when asked."""
    enc = row.pop("content_enc", None)
    reason_enc = row.pop("reason_enc", None)
    if include_text:
        row["text"] = crypto.decrypt_value(enc) if enc else ""
    if reason_enc:
        row["reason"] = crypto.decrypt_value(reason_enc)
    return row


def delete_knowledge_base_document(doc_id):
    """Returns the kb_id the document belonged to, so the caller knows which
    index to rebuild. Deleting a document without rebuilding leaves its text
    retrievable — the whole point of the approval gate."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT kb_id FROM knowledge_base_documents WHERE id=%s", (doc_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("DELETE FROM knowledge_base_documents WHERE id=%s", (doc_id,))
        conn.commit()
        return row["kb_id"]
    finally:
        cursor.close()
        conn.close()


def count_other_eligible_reviewers(org_id, exclude_user_id, cursor=None):
    """How many OTHER people in the org could sign off on a document.

    Eligibility is the reviewer set — admin or auditor — matching
    knowledge_api's require_any_role. Not the role ladder: editor outranks
    auditor but must not review, so a `role >= auditor` query here would
    silently re-open the hole the API is careful to avoid.
    """
    if not org_id:
        return 0
    own_conn = None
    if cursor is None:
        own_conn = get_db_connection()
        cursor = own_conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE org_id=%s AND role IN ('admin','auditor') "
            "AND id <> %s", (org_id, exclude_user_id))
        row = cursor.fetchone()
        # dictionary=True cursors return a mapping, plain ones a tuple.
        return int(list(row.values())[0] if isinstance(row, dict) else row[0])
    finally:
        if own_conn:
            cursor.close()
            own_conn.close()


def set_knowledge_base_document_status(doc_id, action, reviewer_id,
                                       reviewer_email=None, reason=None,
                                       org_id=None):
    """Records an approval decision in ONE transaction: locks the row, applies
    separation of duties, flips status, and appends the evidence to
    org_compliance_log so the decision cannot be made without the log.

    Separation of duties is enforced here, not in the route, for the same
    reason record_review_disposition does it: an examiner tests self-approval
    first, and a rule that lives in one HTTP handler is a rule that the next
    caller silently skips.

    THE SOLE-ADMINISTRATOR EXCEPTION
    --------------------------------
    Self-approval is refused whenever anyone else in the org could review the
    document. When the reviewer is the ONLY admin/auditor, it is permitted —
    and recorded as a different thing: `self_approved` on the row and
    `kb_document_self_approved` in the evidence log, so the audit trail
    distinguishes a non-independent sign-off from an independent one.

    This mirrors FINRA 3110's limited-size-and-resources exception, and the
    reasoning is that an unreviewable queue in a one-person org is not a
    control, it is a dead end that gets worked around outside the product.
    What makes it defensible is that the exception is NAMED, not silent.

    Note it evaluates per decision, against the org's CURRENT membership: add
    a second admin and the exception stops applying immediately, with no
    setting to remember to turn back on. Do not replace this with a stored
    flag — a stored flag is exactly the thing that gets left on.

    Raises ValueError on a bad action or a missing rejection reason;
    SelfReviewError when the uploader is the reviewer AND someone else could
    have reviewed instead. Returns the updated row, or None when the document
    does not exist."""
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    reason = (reason or "").strip()
    if action == "reject" and not reason:
        raise ValueError("a reason is mandatory for a rejection")
    status = "approved" if action == "approve" else "rejected"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM knowledge_base_documents WHERE id=%s FOR UPDATE",
                       (doc_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return None

        is_self = str(row["uploaded_by"]) == str(reviewer_id)
        sole_admin = False
        if is_self:
            if count_other_eligible_reviewers(org_id, reviewer_id, cursor=cursor) > 0:
                conn.rollback()
                raise SelfReviewError(
                    "separation of duties: you cannot approve a document you "
                    "uploaded — another admin or auditor must review it"
                )
            sole_admin = True

        reason_enc = crypto.encrypt_value(reason) if reason else None
        cursor.execute(
            "UPDATE knowledge_base_documents SET status=%s, reviewed_by=%s, "
            "reviewer_email=%s, reviewed_at=NOW(), reason_enc=%s, self_approved=%s "
            "WHERE id=%s",
            (status, reviewer_id, reviewer_email, reason_enc, sole_admin, doc_id),
        )

        if action == "approve":
            event = "kb_document_self_approved" if sole_admin else "kb_document_approved"
        else:
            event = "kb_document_rejected"
        detail = {
            "kb_id": row["kb_id"],
            "document_id": doc_id,
            "filename": row["filename"],
            "sha256": row["sha256"],
            "uploaded_by": row["uploaded_by"],
            "char_count": row["char_count"],
        }
        if sole_admin:
            # Spelled out in the evidence itself. A reader of this row should
            # not have to infer non-independence from the event name alone.
            detail["independent_review"] = False
            detail["exception"] = "sole_administrator"
            detail["attestation"] = (
                "Approved by the only admin/auditor in the organization; no "
                "independent reviewer was available at the time of sign-off."
            )
        append_compliance_log(org_id, event, f"user:{reviewer_id}", detail, cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_knowledge_base_document(doc_id)


def mark_documents_pending_for_share(kb_id):
    """Called when a private KB becomes org-visible. Every 'private' document
    becomes 'pending' — nothing carries its unreviewed status into a shared
    corpus. Returns how many were re-flagged."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE knowledge_base_documents SET status='pending' "
            "WHERE kb_id=%s AND status='private'", (kb_id,))
        count = cursor.rowcount
        conn.commit()
        return count
    finally:
        cursor.close()
        conn.close()


def mark_documents_private_for_unshare(kb_id):
    """The inverse: a KB returning to private has no approver, so pending and
    approved rows both collapse back to 'private'. Rejected rows stay
    rejected — a considered 'no' is not undone by a visibility change."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE knowledge_base_documents SET status='private' "
            "WHERE kb_id=%s AND status IN ('pending', 'approved')", (kb_id,))
        count = cursor.rowcount
        conn.commit()
        return count
    finally:
        cursor.close()
        conn.close()


def claim_pending_knowledge_base():
    """Atomically claims one KB queued for indexing, or returns None.

    The conditional UPDATE is the claim: two indexer processes cannot both
    move the same row out of 'pending', so the worst case of running two is
    duplicated effort, never two writers racing on one index file."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id FROM knowledge_bases WHERE status='pending' "
            "ORDER BY updated_at ASC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "UPDATE knowledge_bases SET status='indexing' "
            "WHERE id=%s AND status='pending'", (row["id"],))
        claimed = cursor.rowcount == 1
        conn.commit()
        return row["id"] if claimed else None
    finally:
        cursor.close()
        conn.close()


def list_knowledge_bases_for_agent_picker(user_id, org_id=None, user_role='member'):
    """Only KBs that can actually ground an answer. A KB with no indexed
    vectors attached to an agent looks configured and answers nothing."""
    return [kb for kb in list_knowledge_bases(user_id, org_id, user_role)
            if kb.get("status") == "ready" and (kb.get("chunk_count") or 0) > 0]


# -------------------------------------------------------------------------
# NEW: ORG & POLICY MANAGEMENT
# -------------------------------------------------------------------------

def create_organization_atomic(org_name, user_id):
    from ..core.policies.safi.policy import SAFI_DEFAULT_POLICY

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.start_transaction()
        oid = str(uuid.uuid4())

        cursor.execute("""
            INSERT INTO organizations (id, name, owner_id, settings, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (oid, org_name, user_id, json.dumps({'allow_auto_join': False})))

        # Seed the new org's policy from the SAFi default template so it
        # starts with a complete, well-structured governance baseline rather
        # than an empty shell.
        pid = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            pid, oid,
            "SAFi Default Policy",
            SAFI_DEFAULT_POLICY.get("global_worldview", ""),
            json.dumps(SAFI_DEFAULT_POLICY.get("global_will_rules", [])),
            json.dumps(SAFI_DEFAULT_POLICY.get("global_values", [])),
            user_id,
        ))

        cursor.execute("UPDATE organizations SET global_policy_id=%s WHERE id=%s", (pid, oid))
        conn.commit()
        return {"org_id": oid, "policy_id": pid}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def find_policy_by_name(name, org_id=None, created_by=None):
    """Return an existing policy ({id, name}) that matches `name` within the
    same scope, or None. Scope is the organization when org-scoped, otherwise
    the creating user. Used to make policy creation idempotent so a
    double-submit / network retry can't spawn identical duplicate policies."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if org_id:
            cursor.execute(
                "SELECT id, name FROM policies WHERE org_id=%s AND name=%s LIMIT 1",
                (org_id, name),
            )
        else:
            cursor.execute(
                "SELECT id, name FROM policies WHERE org_id IS NULL AND created_by=%s AND name=%s LIMIT 1",
                (created_by, name),
            )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def create_policy(name, worldview, will_rules, values, org_id=None, created_by=None, policy_id=None, policy_config=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pid = policy_id or str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by, policy_config) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (pid, org_id, name, worldview, json.dumps(will_rules), json.dumps(values), created_by, json.dumps(policy_config or {}))
        )
        # Seed version 1 of the policy history.
        cursor.execute(
            "INSERT INTO policy_versions (policy_id, version, name, worldview, will_rules, values_weights, policy_config, note, created_by) "
            "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)",
            (pid, name, worldview, json.dumps(will_rules), json.dumps(values), json.dumps(policy_config or {}), "Initial version", created_by)
        )
        conn.commit()
        return pid
    finally:
        cursor.close()
        conn.close()

def update_policy(policy_id, name=None, worldview=None, will_rules=None, values=None, policy_config=None, note=None, updated_by=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        fields, params = [], []
        if name is not None:          fields.append("name=%s");           params.append(name)
        if worldview is not None:     fields.append("worldview=%s");      params.append(worldview)
        if will_rules is not None:    fields.append("will_rules=%s");     params.append(json.dumps(will_rules))
        if values is not None:        fields.append("values_weights=%s"); params.append(json.dumps(values))
        if policy_config is not None: fields.append("policy_config=%s");  params.append(json.dumps(policy_config))
        if not fields:
            return  # nothing to change — don't create an empty version
        # Bump the version counter atomically with the content update.
        fields.append("version = version + 1")
        params.append(policy_id)
        cursor.execute(f"UPDATE policies SET {', '.join(fields)} WHERE id=%s", tuple(params))
        # Snapshot the resulting full state into the version history.
        cursor.execute("SELECT * FROM policies WHERE id=%s", (policy_id,))
        row = cursor.fetchone()
        if row:
            _j = lambda v: v if (isinstance(v, str) or v is None) else json.dumps(v)
            cursor.execute(
                "INSERT INTO policy_versions (policy_id, version, name, worldview, will_rules, values_weights, policy_config, note, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (policy_id, row['version'], row['name'], row['worldview'],
                 _j(row['will_rules']), _j(row['values_weights']), _j(row['policy_config']), note, updated_by)
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def list_policy_versions(pid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT version, name, note, created_by, created_at FROM policy_versions "
            "WHERE policy_id=%s ORDER BY version DESC", (pid,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_policy_version(pid, version):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM policy_versions WHERE policy_id=%s AND version=%s", (pid, version))
        row = cursor.fetchone()
        if row:
            row['will_rules']     = json.loads(row['will_rules'])     if isinstance(row['will_rules'], str)     else row['will_rules']     or []
            row['values_weights'] = json.loads(row['values_weights']) if isinstance(row['values_weights'], str) else row['values_weights'] or []
            row['policy_config']  = json.loads(row['policy_config'])  if isinstance(row['policy_config'], str)  else row['policy_config']  or {}
        return row
    finally:
        cursor.close()
        conn.close()


def restore_policy_version(pid, version, restored_by=None):
    v = get_policy_version(pid, version)
    if not v:
        return False
    update_policy(
        pid,
        name=v.get('name'),
        worldview=v.get('worldview'),
        will_rules=v.get('will_rules'),
        values=v.get('values_weights'),
        policy_config=v.get('policy_config'),
        note=f"Restored from v{version}",
        updated_by=restored_by,
    )
    return True

def get_policy(pid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM policies WHERE id=%s", (pid,))
        row = cursor.fetchone()
        if row:
            row['will_rules']      = json.loads(row['will_rules'])      if isinstance(row['will_rules'], str)      else row['will_rules']      or []
            row['values_weights']  = json.loads(row['values_weights'])  if isinstance(row['values_weights'], str)  else row['values_weights']  or []
            row['policy_config']   = json.loads(row['policy_config'])   if isinstance(row['policy_config'], str)   else row['policy_config']   or {}
        return row
    finally:
        cursor.close()
        conn.close()

def list_policies(user_id=None, org_id=None):
    # Demo rows are matched against the current seed set, not the is_demo flag
    # alone. Retired demo policies (e.g. demo_contoso_genai_policy) stay in the
    # DB as provenance for old governance records but must not surface as
    # examples. get_policy stays unfiltered so those records keep resolving.
    from ..core.policies.demo.policies import DEMO_AGENT_POLICIES
    demo_ids = list(DEMO_AGENT_POLICIES) + ["safi_default_policy"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Filter by Demo, Creator, OR Organization
        demo_placeholders = ", ".join(["%s"] * len(demo_ids))
        cursor.execute(f"""
            SELECT * FROM policies
            WHERE (is_demo=TRUE AND id IN ({demo_placeholders}))
            OR created_by=%s
            OR (org_id IS NOT NULL AND org_id=%s)
            ORDER BY created_at DESC
        """, (*demo_ids, user_id, org_id))
        
        rows = cursor.fetchall()
        for row in rows:
            row['will_rules'] = json.loads(row['will_rules']) if isinstance(row['will_rules'], str) else row['will_rules']
            row['values_weights'] = json.loads(row['values_weights']) if isinstance(row['values_weights'], str) else row['values_weights']
            # policy_config MUST be decoded here too, exactly as get_policy does.
            # Leaving it as a JSON string is not cosmetic: the Governance tab opens
            # the policy editor from THIS list, and hydratePolicy reads
            # `existingPolicy.policy_config.<key>`. On a string every key is
            # undefined, so business_unit and scope_statement came back empty and
            # — worse — alignment_threshold and ethical_memory silently fell back
            # to the wizard defaults (0.5 / 0.90). alignment_threshold is the
            # Will's blocking threshold, so a routine edit-and-save reset an
            # enforcement parameter with no warning and no diff.
            row['policy_config'] = json.loads(row['policy_config']) if isinstance(row['policy_config'], str) else row['policy_config'] or {}
        return rows
    finally:
        cursor.close()
        conn.close()

def delete_policy(pid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM policies WHERE id=%s", (pid,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def create_api_key(pid, label):
    raw = f"sk-safi-{secrets.token_urlsafe(32)}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO api_keys (key_hash, policy_id, label) VALUES (%s, %s, %s)", (h, pid, label))
        conn.commit()
        return raw
    finally:
        cursor.close()
        conn.close()

def get_policy_keys(pid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT label, created_at, last_used_at, key_hash FROM api_keys WHERE policy_id=%s", (pid,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

# Org helpers
def get_organization_by_domain(domain):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Check for EXACT match on domain_to_verify AND domain_verified=TRUE.
        #
        # ORDER BY matters (backlog 78): the endpoints now refuse a second
        # verification of a domain another org already holds, but a database
        # written before that guard can contain duplicates. Without an order,
        # fetchone() returned an arbitrary row, so the answer to "who owns this
        # domain" could change between calls, and that answer decides where new
        # users land.
        #
        # The guarantee is STABILITY, not fairness: created_at is second
        # granularity, so two orgs created in the same second tie and the id
        # breaks it. Which of a tied pair wins is arbitrary; that it is the same
        # one on every call is the point. A real duplicate still needs an
        # operator to reconcile it.
        cursor.execute(
            "SELECT * FROM organizations WHERE domain_verified=TRUE AND domain_to_verify=%s "
            "ORDER BY created_at, id LIMIT 1", (domain,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def get_oldest_organization():
    """The deployment's founding org, for single-tenant mode: whichever
    organization was created first. Same ORDER BY stability guarantee as
    get_organization_by_domain (created_at, then id) so repeated calls agree
    even if two orgs share a created_at second."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM organizations ORDER BY created_at, id LIMIT 1")
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def get_organization(oid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM organizations WHERE id=%s", (oid,))
        row = cursor.fetchone()
        if row and row.get('settings'):
            try:
                if isinstance(row['settings'], str):
                     row['settings'] = json.loads(row['settings'])
            except:
                row['settings'] = {}
        return row
    finally:
        cursor.close()
        conn.close()
def set_organization_global_policy(oid, pid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET global_policy_id=%s WHERE id=%s", (pid, oid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
def update_verification_token(oid, dom, tok):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET domain_to_verify=%s, verification_token=%s WHERE id=%s", (dom, tok, oid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
def confirm_domain_verification(oid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET domain_verified=TRUE, verification_token=NULL WHERE id=%s", (oid,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def absorb_domain_users(org_id, domain, actor):
    """Move existing accounts on a just-verified domain into the owning org as
    members (backlog 78). Returns a report: moved, skipped, emptied_orgs.

    Proving you control a domain proves you control its identities, so those
    accounts belong to your organization, at the lowest role. The verifying
    admin then decides who is promoted. This is the corporate-standard
    behaviour (Google Workspace and Microsoft 365 both reclaim conflicting
    accounts on a verified domain), and it is Nelson's explicit product call.

    Everyone lands as 'member', never as an admin, so absorption can only ever
    REDUCE an absorbed user's authority. Sessions are revoked so the next
    request re-resolves membership instead of acting in the old org.

    The rule has no exceptions, by design (Nelson, 2026-08-20): one domain per
    org, whoever verifies it is the admin, everyone else on the domain is a
    member. An account's email domain decides which org it belongs to, so a
    person administering some other org from an address on this domain is out of
    model, and the domain wins.

    WHY, and this is the governance argument rather than a convenience one:
    accounts created on a domain nobody has claimed are shadow IT. Someone stood
    up governed agents under a corporate identity with no organizational
    oversight, no charter, and no accountable administrator. Verifying the
    domain is the moment that authority is asserted, and the point of asserting
    it is to bring those accounts under governance. An absorption that politely
    skipped the awkward cases would leave exactly the ungoverned corners the
    verification exists to eliminate.

    The consequence, journaled rather than prevented: if an absorbed user was the
    only admin of another org that still has members, that org is left with no
    administrator. It is reported as org_left_without_admin so an operator can
    appoint one. Promoting a replacement automatically was rejected: handing
    someone admin they never asked for is a silent authority grant, which is
    exactly what a governance product must not do quietly.

    An org left with no members is likewise reported, never deleted: its
    governance records are evidence, and dissolving them to tidy up a membership
    change would destroy an audit trail.
    """
    dom = (domain or "").strip().lower().lstrip("@")
    report = {"moved": [], "skipped": [], "emptied_orgs": [], "orgs_without_admin": []}
    if not dom or not org_id:
        return report

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, email, org_id, role FROM users "
            "WHERE LOWER(SUBSTRING_INDEX(email, '@', -1)) = %s "
            "AND (org_id IS NULL OR org_id != %s)",
            (dom, str(org_id)),
        )
        candidates = cursor.fetchall()

        for u in candidates:
            old_org = u.get("org_id")
            # Everyone on the domain is absorbed. Where that removes another
            # org's last admin, the org is flagged below rather than spared:
            # the domain decides membership, and a headless org is an operator
            # problem, not a reason to leave an identity outside its domain.
            leaves_org_headless = False
            if old_org and (u.get("role") or "").lower() == "admin":
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM users "
                    "WHERE org_id=%s AND role='admin' AND id != %s",
                    (old_org, u["id"]),
                )
                other_admins = (cursor.fetchone() or {}).get("n", 0)
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE org_id=%s AND id != %s",
                    (old_org, u["id"]),
                )
                other_members = (cursor.fetchone() or {}).get("n", 0)
                leaves_org_headless = bool(not other_admins and other_members)

            cursor.execute("UPDATE users SET org_id=%s, role='member' WHERE id=%s",
                           (str(org_id), u["id"]))
            log_auth_event("member_absorbed_by_domain", actor, org_id=str(org_id),
                           user_id=u["id"],
                           detail={"email": u.get("email"), "domain": dom,
                                   "previous_org_id": old_org,
                                   "previous_role": u.get("role"),
                                   "new_role": "member"},
                           cursor=cursor)
            report["moved"].append(u.get("email"))

            # Took the old org's last admin while people remain in it. Not
            # prevented, but it must never be silent: those members cannot
            # administer anything until an operator appoints someone.
            if leaves_org_headless:
                report["orgs_without_admin"].append(old_org)
                log_auth_event("org_left_without_admin", actor, org_id=str(org_id),
                               detail={"headless_org_id": old_org, "domain": dom,
                                       "absorbed_admin": u.get("email"),
                                       "note": "org still has members; needs an admin appointed"},
                               cursor=cursor)

            # Did that empty the old org? Reported, never deleted.
            if old_org:
                cursor.execute("SELECT COUNT(*) AS n FROM users WHERE org_id=%s", (old_org,))
                if not (cursor.fetchone() or {}).get("n", 0):
                    if old_org not in report["emptied_orgs"]:
                        report["emptied_orgs"].append(old_org)
                        log_auth_event("org_left_without_members", actor,
                                       org_id=str(org_id), detail={
                                           "emptied_org_id": old_org, "domain": dom,
                                           "note": "records retained; needs operator reconciliation"},
                                       cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    # Outside the transaction on purpose: the move is committed, and a failed
    # session revoke must not roll it back. A stale session would otherwise keep
    # acting in the old org until it expired.
    for u in candidates:
        if u.get("email") in report["moved"]:
            try:
                revoke_user_sessions(u["id"], actor)
            except Exception as e:
                logging.getLogger(__name__).error(
                    "absorb: session revoke failed for %s: %s", u["id"], e)
    return report
def reset_domain_verification(oid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET domain_to_verify=NULL, verification_token=NULL WHERE id=%s", (oid,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
def create_organization(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        oid = str(uuid.uuid4())
        cursor.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (oid, name))
        conn.commit()
        return oid
    finally:
        cursor.close()
        conn.close()

def update_organization_name(oid, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET name=%s WHERE id=%s", (name, oid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_organization_settings(oid, settings):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if settings exist first to merge? 
        # For now, we assume frontend sends the full or partial dict and we merge it here?
        # Actually safer to fetch, merge, save.
        
        # Fetch current
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (oid,))
        row = cursor.fetchone() # Tuple (json_str,)
        current_settings = {}
        if row and row[0]:
            try:
                current_settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except:
                current_settings = {}
        
        # Merge
        current_settings.update(settings)
        
        cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s", (json.dumps(current_settings), oid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# ORG CHARTER
# -------------------------------------------------------------------------

def upsert_charter(org_id, mission, core_values, created_by=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            INSERT INTO org_charter (org_id, mission, core_values, created_by)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mission = VALUES(mission),
                core_values = VALUES(core_values),
                updated_at = CURRENT_TIMESTAMP
        """
        cursor.execute(sql, (org_id, mission, json.dumps(core_values), created_by))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_charter(org_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM org_charter WHERE org_id = %s", (org_id,))
        row = cursor.fetchone()
        if row:
            row['core_values'] = json.loads(row['core_values']) if isinstance(row['core_values'], str) else row['core_values'] or []
        return row
    finally:
        cursor.close()
        conn.close()


# --- Org AI Standards -------------------------------------------------------
# Separate from the charter on purpose. A charter is mission and core values:
# who the organization is, and something every organization has. AI standards
# say how its AI must behave — AI-specific, optional, and revised on a different
# cycle. Filing one as the other is not merely untidy: charter values are
# SCORED, so a rule stored there is judged on every turn.

def upsert_ai_standards(org_id, values=None, structural_requirements=None,
                        early_prompt_blacklist=None, allowed_tools=None,
                        created_by=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            INSERT INTO org_ai_standards
                (org_id, values_json, structural_requirements,
                 early_prompt_blacklist, allowed_tools, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                values_json = VALUES(values_json),
                structural_requirements = VALUES(structural_requirements),
                early_prompt_blacklist = VALUES(early_prompt_blacklist),
                allowed_tools = VALUES(allowed_tools),
                updated_at = CURRENT_TIMESTAMP
        """
        cursor.execute(sql, (
            org_id,
            json.dumps(values or []),
            json.dumps(structural_requirements or {}),
            json.dumps(early_prompt_blacklist or []),
            # NULL, not [], when the org sets no tool cap: an empty list means
            # "does not narrow" to authorized_tools, and storing NULL keeps the
            # distinction legible to anyone reading the row directly.
            json.dumps(allowed_tools) if isinstance(allowed_tools, list) else None,
            created_by,
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_ai_standards(org_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM org_ai_standards WHERE org_id = %s", (org_id,))
        row = cursor.fetchone()
        if not row:
            return None
        # Normalize at the reader so no consumer repeats the None check, and so
        # a NULL never reaches the browser as something the settings UI iterates.
        for key, empty in (('values_json', []),
                           ('structural_requirements', {}),
                           ('early_prompt_blacklist', [])):
            val = row.get(key)
            row[key] = json.loads(val) if isinstance(val, str) else (val if val is not None else empty)
        at = row.get('allowed_tools')
        # Kept nullable: None = no org-wide tool cap, [] would read as one.
        row['allowed_tools'] = json.loads(at) if isinstance(at, str) else at
        row['values'] = row.pop('values_json')
        return row
    finally:
        cursor.close()
        conn.close()


def delete_ai_standards(org_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM org_ai_standards WHERE org_id = %s", (org_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def delete_charter(org_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM org_charter WHERE org_id = %s", (org_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_organization_members(org_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Sort so Admins appear first, then others
        cursor.execute("SELECT id, name, email, role FROM users WHERE org_id=%s ORDER BY FIELD(role, 'admin', 'editor', 'auditor', 'member'), name", (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# SECURITY INCIDENTS (Reg S-P 248.30)
# -------------------------------------------------------------------------
# Every query is scoped by org_id at the SQL layer, not just the route guard.
# incident_events is append-only: no update/delete helpers exist for it.

# Columns an admin may set through the API; everything else (harm provenance
# stamps, customers_notified_at, timestamps) is server-managed.
_INCIDENT_MUTABLE = [
    "title", "description", "status", "severity", "occurred_at",
    "occurred_range_end", "firm_aware_at", "source", "vendor_name",
    "vendor_aware_at", "vendor_notified_firm_at", "data_types",
    "affected_scope", "affected_user_ids", "assessment_notes",
    "containment_notes", "harm_assessment", "harm_determination",
    "ag_delay", "ag_delay_reference", "ag_delay_until",
    "regimes", "eu_incident_class", "hipaa_role", "affected_count",
]
_INCIDENT_JSON_COLS = ("data_types", "affected_user_ids", "regimes")
_INCIDENT_DT_COLS = ("occurred_at", "occurred_range_end", "firm_aware_at",
                     "vendor_aware_at", "vendor_notified_firm_at", "ag_delay_until")

def _incident_dt(value):
    """Normalizes ISO-8601 input (with T/Z/offset) to the naive-UTC
    'YYYY-MM-DD HH:MM:SS' form MySQL DATETIME accepts."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value  # let MySQL reject anything unparseable
    if not isinstance(value, datetime):
        return value
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")

def _incident_store_value(col, value):
    if col in _INCIDENT_JSON_COLS:
        return json.dumps(value) if value is not None else None
    if col in _INCIDENT_DT_COLS:
        return _incident_dt(value)
    return value

def _incident_event_append(cursor, org_id, incident_id, event_type, detail,
                           actor_id, actor_email, changes=None):
    cursor.execute(
        "INSERT INTO incident_events (incident_id, org_id, event_type, detail, "
        "changes, actor_id, actor_email) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (incident_id, org_id, event_type, detail,
         json.dumps(changes) if changes else None, actor_id, actor_email),
    )

def create_security_incident(org_id, data, actor_id, actor_email):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        iid = str(uuid.uuid4())
        cols, vals = ["id", "org_id", "created_by"], [iid, org_id, actor_id]
        for c in _INCIDENT_MUTABLE:
            if c in data and data[c] is not None:
                cols.append(c)
                vals.append(_incident_store_value(c, data[c]))
        cursor.execute(
            f"INSERT INTO security_incidents ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(vals))})",
            tuple(vals),
        )
        _incident_event_append(cursor, org_id, iid, "created",
                               f"Incident opened: {data.get('title', '')}",
                               actor_id, actor_email)
        conn.commit()
        return iid
    finally:
        cursor.close()
        conn.close()

def list_security_incidents(org_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE org_id=%s "
                       "ORDER BY firm_aware_at DESC", (org_id,))
        rows = cursor.fetchall()
        for r in rows:
            for c in _INCIDENT_JSON_COLS:
                if isinstance(r.get(c), str):
                    try:
                        r[c] = json.loads(r[c])
                    except (ValueError, TypeError):
                        pass
        return rows
    finally:
        cursor.close()
        conn.close()

def get_security_incident(org_id, incident_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE id=%s AND org_id=%s",
                       (incident_id, org_id))
        row = cursor.fetchone()
        if row:
            for c in _INCIDENT_JSON_COLS:
                if isinstance(row.get(c), str):
                    try:
                        row[c] = json.loads(row[c])
                    except (ValueError, TypeError):
                        pass
        return row
    finally:
        cursor.close()
        conn.close()

def update_security_incident(org_id, incident_id, changes, actor_id, actor_email):
    """Whitelisted-field update with an atomic field-level diff event.
    Returns the updated row, or None if the incident isn't in this org."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE id=%s AND org_id=%s FOR UPDATE",
                       (incident_id, org_id))
        current = cursor.fetchone()
        if not current:
            return None
        diff = {}
        sets, vals = [], []
        for c in _INCIDENT_MUTABLE:
            if c not in changes:
                continue
            new_v = changes[c]
            stored_v = _incident_store_value(c, new_v)
            old_v = current.get(c)
            if isinstance(old_v, bool):
                old_cmp = old_v
            else:
                old_cmp = str(old_v) if old_v is not None else None
            new_cmp = str(stored_v) if stored_v is not None else None
            if c == "ag_delay":
                new_cmp = bool(new_v)
                old_cmp = bool(old_v)
                stored_v = new_cmp
            if old_cmp != new_cmp:
                diff[c] = {"from": old_v if not isinstance(old_v, (bytes,)) else str(old_v),
                           "to": new_v}
                sets.append(f"{c}=%s")
                vals.append(stored_v)
        # Server-stamp harm-determination provenance: the Reg S-P exception
        # must be a *documented determination* attributable to a person.
        if "harm_determination" in diff and changes.get("harm_determination"):
            sets.append("harm_determined_by=%s")
            vals.append(actor_email or actor_id)
            sets.append("harm_determined_at=UTC_TIMESTAMP()")
        if sets:
            vals.extend([incident_id, org_id])
            cursor.execute(
                f"UPDATE security_incidents SET {', '.join(sets)} WHERE id=%s AND org_id=%s",
                tuple(vals),
            )
            event_type = "updated"
            if "status" in diff:
                event_type = "status_changed"
            elif "harm_determination" in diff:
                event_type = "harm_determination"
            _incident_event_append(cursor, org_id, incident_id, event_type,
                                   None, actor_id, actor_email, changes=diff)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_security_incident(org_id, incident_id)

# Regime-notice events → the stop-timestamp column they stamp. Stamps are
# first-occurrence-only: the FIRST notice stops the clock, later events of the
# same type are evidence entries without a re-stamp.
_EVENT_STAMP_COLS = {
    "notification_sent": "customers_notified_at",     # reg_sp customers
    "authority_notified": "authority_notified_at",    # eu_ai_act Art. 73
    "individuals_notified": "individuals_notified_at",  # hipaa CE → individuals
    "hhs_notified": "hhs_notified_at",                # hipaa → HHS (or annual log)
    "media_notified": "media_notified_at",            # hipaa ≥500 media
    "ce_notified": "ce_notified_at",                  # hipaa BA → covered entity
}

def append_incident_event(org_id, incident_id, event_type, detail, actor_id, actor_email):
    """Manual event log entry. Regime-notice event types also stamp their
    clock's stop timestamp (see _EVENT_STAMP_COLS)."""
    stamp_col = _EVENT_STAMP_COLS.get(event_type)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT {stamp_col or 'id'} FROM security_incidents "
                       "WHERE id=%s AND org_id=%s FOR UPDATE", (incident_id, org_id))
        row = cursor.fetchone()
        if not row:
            return False
        if stamp_col and row[0] is None:
            cursor.execute(f"UPDATE security_incidents SET {stamp_col}=UTC_TIMESTAMP() "
                           "WHERE id=%s AND org_id=%s", (incident_id, org_id))
        _incident_event_append(cursor, org_id, incident_id, event_type, detail,
                               actor_id, actor_email)
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

def list_incident_events(org_id, incident_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM incident_events WHERE incident_id=%s AND org_id=%s "
                       "ORDER BY id ASC", (incident_id, org_id))
        rows = cursor.fetchall()
        for r in rows:
            if isinstance(r.get("changes"), str):
                try:
                    r["changes"] = json.loads(r["changes"])
                except (ValueError, TypeError):
                    pass
        return rows
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# RETENTION & COMPLIANCE LOG (SEA 17a-4 / Advisers Act 204-2 retention)
# -------------------------------------------------------------------------
# org_compliance_log is append-only destruction/production evidence: counts
# and config diffs only, never content. No update/delete helpers exist.

def append_compliance_log(org_id, event_type, actor, detail=None, cursor=None):
    """Appends one evidence row. Pass a cursor to join the caller's
    transaction; otherwise commits standalone."""
    own_conn = None
    if cursor is None:
        own_conn = get_db_connection()
        cursor = own_conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO org_compliance_log (org_id, event_type, actor, detail) "
            "VALUES (%s, %s, %s, %s)",
            (org_id, event_type, actor, json.dumps(detail) if detail is not None else None),
        )
        if own_conn:
            own_conn.commit()
    finally:
        if own_conn:
            cursor.close()
            own_conn.close()

def list_compliance_log(org_id, limit=20):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM org_compliance_log WHERE org_id=%s "
            "ORDER BY id DESC LIMIT %s", (org_id, int(limit)),
        )
        rows = cursor.fetchall()
        for r in rows:
            if isinstance(r.get("detail"), str):
                try:
                    r["detail"] = json.loads(r["detail"])
                except (ValueError, TypeError):
                    pass
        return rows
    finally:
        cursor.close()
        conn.close()

def insert_llm_usage(org_id, agent, route, provider, model, tokens_in, tokens_out):
    """One row per provider call (backlog 61). Called fire-and-forget from
    usage_tracking.record_usage, which swallows any failure here — a usage
    write must never break a chat turn."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO llm_usage (org_id, agent, route, provider, model, tokens_in, tokens_out) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (org_id, agent, route, provider, model, int(tokens_in), int(tokens_out)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_org_llm_usage(org_id, days=30):
    """Aggregated token usage for one org's Usage & Cost tab. Raw counts only;
    dollar estimates are computed at display time from the price map."""
    days = max(1, min(int(days), 365))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        window = "org_id=%s AND created_at >= NOW() - INTERVAL %s DAY"
        cursor.execute(
            f"SELECT DATE(created_at) AS day, COUNT(*) AS calls, "
            f"SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out "
            f"FROM llm_usage WHERE {window} GROUP BY day ORDER BY day DESC",
            (org_id, days),
        )
        by_day = cursor.fetchall()
        cursor.execute(
            f"SELECT provider, model, COUNT(*) AS calls, "
            f"SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out "
            f"FROM llm_usage WHERE {window} GROUP BY provider, model "
            f"ORDER BY tokens_out DESC",
            (org_id, days),
        )
        by_model = cursor.fetchall()
        cursor.execute(
            f"SELECT route, COUNT(*) AS calls, "
            f"SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out "
            f"FROM llm_usage WHERE {window} GROUP BY route ORDER BY tokens_out DESC",
            (org_id, days),
        )
        by_route = cursor.fetchall()
        cursor.execute(
            f"SELECT COALESCE(agent, '(none)') AS agent, COUNT(*) AS calls, "
            f"SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out "
            f"FROM llm_usage WHERE {window} GROUP BY agent ORDER BY tokens_out DESC",
            (org_id, days),
        )
        by_agent = cursor.fetchall()
        # MySQL SUM() returns Decimal and DATE() returns date; make it JSON-safe.
        for rows in (by_day, by_model, by_route, by_agent):
            for r in rows:
                if "day" in r:
                    r["day"] = str(r["day"])
                r["tokens_in"] = int(r["tokens_in"] or 0)
                r["tokens_out"] = int(r["tokens_out"] or 0)
                r["calls"] = int(r["calls"] or 0)
        return {"days": days, "by_day": by_day, "by_model": by_model,
                "by_route": by_route, "by_agent": by_agent}
    finally:
        cursor.close()
        conn.close()

def list_custom_models(visible_to_org=None):
    """Added models (backlog 63), oldest first for a stable picker.

    visible_to_org=None returns EVERY row, which is what routing needs:
    detect_provider has to resolve any registered id to its provider and has no
    org in scope. Pass an org id for anything user-facing, and the result is
    that org's own rows plus the deployment-wide ones (backlog 77). Before that
    scoping every org saw, and could delete, every other org's entries.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = ("SELECT model_id, label, provider, created_by, org_id, created_at "
               "FROM custom_models")
        args = ()
        if visible_to_org is not None:
            sql += " WHERE org_id IN ('', %s)"
            args = (str(visible_to_org),)
        cursor.execute(sql + " ORDER BY created_at, model_id", args)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def add_custom_model(model_id, label, provider, created_by=None, org_id=''):
    """org_id='' publishes deployment-wide and is reserved for operators; a
    tenant admin's entry is scoped to their own org."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO custom_models (model_id, label, provider, created_by, org_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (model_id, label, provider, created_by, str(org_id or '')))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def delete_custom_model(model_id, org_id=None):
    """Returns True when a row was removed.

    org_id=None deletes regardless of owner and is for operators only. Passing
    an org id restricts the delete to that org's own rows, so a tenant admin
    cannot remove another org's model or a deployment-wide one.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if org_id is None:
            cursor.execute("DELETE FROM custom_models WHERE model_id=%s", (model_id,))
        else:
            cursor.execute("DELETE FROM custom_models WHERE model_id=%s AND org_id=%s",
                           (model_id, str(org_id)))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def get_deployment_llm_usage(days=30):
    """Whole-deployment usage grouped by org and model (backlog 65) — the
    operator's view of who spends the shared .env provider keys. NULL org is
    the public bot / ungoverned traffic. Per-model rows so the UI can price
    each org's consumption; the org name rides along for display."""
    days = max(1, min(int(days), 365))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT u.org_id, o.name AS org_name, u.provider, u.model, "
            "COUNT(*) AS calls, SUM(u.tokens_in) AS tokens_in, "
            "SUM(u.tokens_out) AS tokens_out "
            "FROM llm_usage u LEFT JOIN organizations o ON o.id = u.org_id "
            "WHERE u.created_at >= NOW() - INTERVAL %s DAY "
            "GROUP BY u.org_id, o.name, u.provider, u.model "
            "ORDER BY tokens_out DESC",
            (days,))
        rows = cursor.fetchall()
        for r in rows:
            r["tokens_in"] = int(r["tokens_in"] or 0)
            r["tokens_out"] = int(r["tokens_out"] or 0)
            r["calls"] = int(r["calls"] or 0)
        return {"days": days, "by_org_model": rows}
    finally:
        cursor.close()
        conn.close()

def set_org_provider_key(org_id, provider, key, updated_by=None):
    """Stores (or replaces) an org's own provider key, encrypted (backlog 64).
    The plaintext never persists and is never logged."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO org_provider_keys (org_id, provider, key_enc, last4, updated_by) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE key_enc=VALUES(key_enc), last4=VALUES(last4), "
            "updated_by=VALUES(updated_by)",
            (org_id, provider, crypto.encrypt_value(key), key[-4:], updated_by))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def delete_org_provider_key(org_id, provider):
    """Returns True when a row was removed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM org_provider_keys WHERE org_id=%s AND provider=%s",
            (org_id, provider))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()

def list_org_provider_keys(org_id):
    """Display shape only: provider, last4, updated_at. The key itself is
    write-only from the UI's point of view — never returned here."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT provider, last4, updated_at FROM org_provider_keys "
            "WHERE org_id=%s ORDER BY provider", (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_org_provider_keys_decrypted(org_id):
    """{provider: plaintext key} for dispatch (org_keys.org_key_map). The one
    read path that decrypts."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT provider, key_enc FROM org_provider_keys WHERE org_id=%s",
            (org_id,))
        out = {}
        for r in cursor.fetchall():
            key = crypto.decrypt_value(r["key_enc"])
            if key:
                out[r["provider"]] = key
        return out
    finally:
        cursor.close()
        conn.close()

def validate_retention_years(value):
    """Returns (ok, normalized). None means keep-forever (no purge)."""
    if value is None:
        return True, None
    if isinstance(value, bool) or not isinstance(value, int):
        return False, None
    if value < 1 or value > 99:
        return False, None
    return True, value

def get_org_retention_config(org_id):
    """Reads retention config from organizations.settings, validated on read.
    Returns {retention_years, legal_hold, valid} — the purge must skip (and
    log) orgs where valid is False rather than guess."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        ok, years = validate_retention_years(settings.get("retention_years"))
        hold = settings.get("legal_hold") or {}
        return {
            "retention_years": years,
            "legal_hold": {
                "active": bool(hold.get("active")),
                "reason": hold.get("reason"),
                "set_by": hold.get("set_by"),
                "set_at": hold.get("set_at"),
            },
            "valid": ok,
        }
    finally:
        cursor.close()
        conn.close()

def set_org_retention_config(org_id, changes, actor):
    """Merges retention config into organizations.settings AND appends the
    compliance-log evidence rows in the same transaction, so a config change
    can never dodge the evidence log. Returns the new config, or raises
    ValueError on invalid input.

    changes: {"retention_years": int|None} and/or
             {"legal_hold": {"active": bool, "reason": str}}
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}

        if "retention_years" in changes:
            ok, years = validate_retention_years(changes["retention_years"])
            if not ok:
                raise ValueError("retention_years must be an integer between 1 and 99, or null for keep-forever")
            old = settings.get("retention_years")
            if old != years:
                if years is None:
                    settings.pop("retention_years", None)
                else:
                    settings["retention_years"] = years
                append_compliance_log(org_id, "retention_config_changed", actor,
                                      {"changed": {"retention_years": {"old": old, "new": years}}},
                                      cursor=cursor)

        if "legal_hold" in changes:
            req = changes["legal_hold"] or {}
            activating = bool(req.get("active"))
            current = settings.get("legal_hold") or {}
            if activating and not (req.get("reason") or "").strip():
                raise ValueError("a reason is required to place a legal hold")
            if activating and not current.get("active"):
                settings["legal_hold"] = {
                    "active": True,
                    "reason": req["reason"].strip(),
                    "set_by": actor,
                    "set_at": datetime.now(timezone.utc).isoformat(),
                }
                append_compliance_log(org_id, "legal_hold_set", actor,
                                      {"reason": settings["legal_hold"]["reason"]},
                                      cursor=cursor)
            elif not activating and current.get("active"):
                settings["legal_hold"] = {"active": False, "cleared_by": actor,
                                          "cleared_at": datetime.now(timezone.utc).isoformat()}
                append_compliance_log(org_id, "legal_hold_cleared", actor,
                                      {"previous_reason": current.get("reason")},
                                      cursor=cursor)

        cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                       (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_org_retention_config(org_id)

def export_user_data(user_id):
    """Right-of-access export (GDPR Art. 15 / HIPAA §164.524): everything
    SAFi holds about ONE user, decrypted, for self-service download. A
    deliberate subset of the examiner export — the requesting user's own
    records only: account row (credential material stripped), conversations
    with their messages and per-turn governance verdicts, projects, saved
    content, profile memory, and per-agent work memories. No audit-trail
    states, no other users' data. Returns None for an unknown user.
    The CALLER must custody-log the export before returning bytes."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, email, name, picture, active_profile, created_at, "
            "last_login, org_id, role, intellect_model, will_model, "
            "conscience_model FROM users WHERE id=%s", (user_id,))
        account = cursor.fetchone()
        if not account:
            return None

        cursor.execute(
            "SELECT id, title, is_pinned, project_id, created_at "
            "FROM conversations WHERE user_id=%s ORDER BY created_at", (user_id,))
        conversations = cursor.fetchall()
        total_messages = 0
        for c in conversations:
            c["title"] = crypto.decrypt_value(c["title"])
            cursor.execute(
                "SELECT message_id, role, content, timestamp, audit_status, "
                "profile_name, policy_id, policy_version, spirit_score, drift, "
                "will_decision, will_stage FROM chat_history "
                "WHERE conversation_id=%s ORDER BY id", (c["id"],))
            msgs = cursor.fetchall()
            for m in msgs:
                m["content"] = crypto.decrypt_value(m["content"])
                # Art. 50(2): AI messages carry the machine-readable marker.
                m["ai_generated"] = (m["role"] == "ai")
            c["messages"] = msgs
            total_messages += len(msgs)

        cursor.execute("SELECT id, name, created_at FROM projects WHERE user_id=%s", (user_id,))
        projects = cursor.fetchall()

        cursor.execute(
            "SELECT id, project_id, conversation_id, title, content, "
            "profile_name, spirit_score, created_at FROM saved_content "
            "WHERE user_id=%s ORDER BY created_at", (user_id,))
        saved = cursor.fetchall()
        for s in saved:
            s["content"] = crypto.decrypt_value(s["content"])

        cursor.execute("SELECT profile_json FROM user_profiles WHERE user_id=%s", (user_id,))
        row = cursor.fetchone()
        profile_memory = crypto.decrypt_value(row["profile_json"]) if row else None

        cursor.execute(
            "SELECT agent_id, context_json, updated_at FROM agent_context_memory "
            "WHERE user_id=%s", (user_id,))
        agent_memories = cursor.fetchall()
        for a in agent_memories:
            a["context_json"] = crypto.decrypt_value(a["context_json"])
    finally:
        cursor.close()
        conn.close()
    return {
        "account": account,
        "conversations": conversations,
        "projects": projects,
        "saved_content": saved,
        "profile_memory": profile_memory,
        "agent_memories": agent_memories,
        "counts": {"conversations": len(conversations), "messages": total_messages,
                   "projects": len(projects), "saved_content": len(saved)},
    }

def get_org_offline_config(org_id):
    """Offline/PWA kill switch. Regulated posture: default OFF — members'
    browsers keep no local copies of org content (GET cache, write queue,
    conversation cache, service-worker caches) unless an admin opts in."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        return {"offline_enabled": bool(settings.get("offline_enabled", False))}
    finally:
        cursor.close()
        conn.close()

def set_org_offline_config(org_id, enabled, actor):
    """Toggles the offline/PWA switch; evidence-logged in the same
    transaction so the change can never dodge the compliance log."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        old = bool(settings.get("offline_enabled", False))
        new = bool(enabled)
        if old != new:
            settings["offline_enabled"] = new
            append_compliance_log(org_id, "offline_config_changed", actor,
                                  {"old": old, "new": new}, cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_org_offline_config(org_id)

def get_org_provider_config(org_id):
    """Reads the LLM provider allow-list from organizations.settings.
    {'allowlist': [...]} or {'allowlist': None} — None means unrestricted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        raw = settings.get("provider_allowlist")
        return {"allowlist": raw if isinstance(raw, list) else None}
    finally:
        cursor.close()
        conn.close()

def set_org_provider_allowlist(org_id, allowlist, actor):
    """Sets (or clears, with None) the org's LLM provider allow-list AND
    appends the compliance-log evidence row in the same transaction, so the
    change can never dodge the evidence log — same contract as
    set_org_retention_config. Raises ValueError on invalid input.

    allowlist: None = unrestricted, or a NON-EMPTY list of provider keys from
    model_routing.PROVIDER_METADATA (an empty list would brick every LLM call
    in the org, so it is rejected rather than stored)."""
    from ..core.services.model_routing import PROVIDER_METADATA
    if allowlist is not None:
        if not isinstance(allowlist, list) or not allowlist:
            raise ValueError("allowlist must be null (unrestricted) or a non-empty list of provider keys")
        unknown = sorted({str(p) for p in allowlist} - set(PROVIDER_METADATA))
        if unknown:
            raise ValueError(f"unknown providers: {', '.join(unknown)}")
        allowlist = sorted({str(p) for p in allowlist})

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}

        old = settings.get("provider_allowlist")
        old = sorted(old) if isinstance(old, list) else None
        if old != allowlist:
            if allowlist is None:
                settings.pop("provider_allowlist", None)
            else:
                settings["provider_allowlist"] = allowlist
            append_compliance_log(org_id, "provider_allowlist_changed", actor,
                                  {"changed": {"provider_allowlist": {"old": old, "new": allowlist}}},
                                  cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    from ..core.services import provider_governance
    provider_governance.invalidate_org(org_id)
    return get_org_provider_config(org_id)


# --- Data-source connector allow-list ---------------------------------------
# Which external accounts (Google Drive / SharePoint / GitHub) members of this
# org may link. Same storage, validation and evidence contract as the LLM
# provider allow-list above — see core/services/connector_governance.py for why
# the credential itself stays per-user rather than becoming a service principal.

def get_org_connector_config(org_id):
    """Reads the data-source connector allow-list from organizations.settings.
    {'allowlist': [...]} or {'allowlist': None} — None means unrestricted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        raw = settings.get("connector_allowlist")
        return {"allowlist": raw if isinstance(raw, list) else None}
    finally:
        cursor.close()
        conn.close()


def set_org_connector_allowlist(org_id, allowlist, actor):
    """Sets (or clears, with None) the org's connector allow-list AND appends
    the compliance-log evidence row in the same transaction, so the change can
    never dodge the evidence log — same contract as set_org_provider_allowlist.

    allowlist: None = unrestricted, or a list of keys from
    connector_governance.CONNECTOR_METADATA. Unlike the provider list, an EMPTY
    list is accepted and means "no data sources may be linked": that is a
    coherent and probably common policy, whereas an empty provider list would
    brick every LLM call in the org."""
    from ..core.services.connector_governance import CONNECTOR_METADATA
    if allowlist is not None:
        if not isinstance(allowlist, list):
            raise ValueError("allowlist must be null (unrestricted) or a list of connector keys")
        unknown = sorted({str(c) for c in allowlist} - set(CONNECTOR_METADATA))
        if unknown:
            raise ValueError(f"unknown data sources: {', '.join(unknown)}")
        allowlist = sorted({str(c) for c in allowlist})

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}

        old = settings.get("connector_allowlist")
        old = sorted(old) if isinstance(old, list) else None
        if old != allowlist:
            if allowlist is None:
                settings.pop("connector_allowlist", None)
            else:
                settings["connector_allowlist"] = allowlist
            append_compliance_log(org_id, "connector_allowlist_changed", actor,
                                  {"changed": {"connector_allowlist": {"old": old, "new": allowlist}}},
                                  cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    from ..core.services import connector_governance
    connector_governance.invalidate_org(org_id)
    return get_org_connector_config(org_id)


def list_org_connections(org_id):
    """Who in this org has linked which data source. Admin visibility — the
    question 'what corporate data can our agents currently reach' had no answer
    before this.

    Joined on users.org_id rather than filtering in Python so a user in another
    org can never appear, and no token material is selected: the columns are
    deliberately limited to who/what/when."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT u.id AS user_id, u.name, u.email, t.provider,
                      t.scope, t.created_at, t.updated_at
                 FROM oauth_tokens t
                 JOIN users u ON u.id = t.user_id
                WHERE u.org_id = %s
             ORDER BY u.name, t.provider""",
            (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# --- Incident notification regimes (Phase D) --------------------------------
# The org's default regime set for NEW incidents, stored in
# organizations.settings.incident_regimes. Per-incident tags live on the
# incident row itself (regimes JSON) and override this at create time.
# Canonical key order matches REGIME_RULES in api/incidents_api.py.

INCIDENT_REGIME_KEYS = ("reg_sp", "eu_ai_act", "hipaa")

def get_org_incident_regimes(org_id):
    """The org's default regime set; reg_sp when unset (the registry's
    original, always-applicable baseline for regulated firms)."""
    org = get_organization(org_id)
    stored = ((org or {}).get("settings") or {}).get("incident_regimes")
    if isinstance(stored, list) and stored:
        kept = [k for k in INCIDENT_REGIME_KEYS if k in stored]
        if kept:
            return kept
    return ["reg_sp"]

def set_org_incident_regimes(org_id, regimes, actor):
    """Sets the org's default regime set AND appends the compliance-log
    evidence row in the same transaction — same contract as
    set_org_provider_allowlist. Raises ValueError on invalid input."""
    if not isinstance(regimes, list) or not regimes:
        raise ValueError("regimes must be a non-empty list of regime keys")
    unknown = sorted({str(r) for r in regimes} - set(INCIDENT_REGIME_KEYS))
    if unknown:
        raise ValueError(f"unknown regimes: {', '.join(unknown)} "
                         f"(valid: {', '.join(INCIDENT_REGIME_KEYS)})")
    regimes = [k for k in INCIDENT_REGIME_KEYS if k in {str(r) for r in regimes}]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}

        old = settings.get("incident_regimes")
        old = [k for k in INCIDENT_REGIME_KEYS if isinstance(old, list) and k in old] or None
        if old != regimes:
            settings["incident_regimes"] = regimes
            append_compliance_log(org_id, "incident_regimes_changed", actor,
                                  {"changed": {"incident_regimes": {"old": old, "new": regimes}}},
                                  cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return {"regimes": get_org_incident_regimes(org_id)}

# --- Human review queue: config, sampling, enqueue (Phase E) ---------------
# Config lives in organizations.settings.review_config, changed only through
# set_org_review_config (evidence-logged, same pattern as retention and the
# provider allow-list). Sampling default OFF — supervision is an org's
# explicit, journaled opt-in. Thresholds default to the Audit Hub's
# long-standing flag line (Alignment < 6; drift > 0.4 ≡ Consistency < 60%).

REVIEW_CONFIG_DEFAULTS = {
    "enabled": False,
    "random_sample_pct": 5,
    "triggers": {
        "hard_gate_block": True,
        "gateway_violation": True,
        # Off by default, unlike its siblings: turning it on changes queue
        # volume for orgs already running review, so it must be an admin's
        # journaled opt-in rather than arrive silently via a deploy.
        "agent_redirect": False,
        "low_alignment": True,
        "alignment_threshold": 6,
        "drift_spike": True,
        "drift_threshold": 0.4,
    },
    "alerts": {
        "webhook_url": None,
        "alignment_avg_threshold": 6,
        "alignment_window_turns": 20,
        "backlog_max_age_days": 14,
    },
}

def _merged_review_config(stored):
    """Stored review_config (possibly partial/absent) merged over defaults."""
    cfg = json.loads(json.dumps(REVIEW_CONFIG_DEFAULTS))  # deep copy
    if isinstance(stored, dict):
        for key, val in stored.items():
            if key in ("triggers", "alerts") and isinstance(val, dict):
                cfg[key].update(val)
            else:
                cfg[key] = val
    return cfg

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def validate_review_config_changes(changes):
    """Validates a partial review_config update. Raises ValueError with a
    user-facing message on the first problem. Pure — no DB."""
    if not isinstance(changes, dict):
        raise ValueError("review config must be an object")
    allowed_top = {"enabled", "random_sample_pct", "triggers", "alerts"}
    unknown = set(changes) - allowed_top
    if unknown:
        raise ValueError(f"unknown review config keys: {', '.join(sorted(unknown))}")
    if "enabled" in changes and not isinstance(changes["enabled"], bool):
        raise ValueError("enabled must be true or false")
    if "random_sample_pct" in changes:
        pct = changes["random_sample_pct"]
        if not _is_num(pct) or pct < 0 or pct > 100:
            raise ValueError("random_sample_pct must be a number between 0 and 100")
    trig = changes.get("triggers", {})
    if not isinstance(trig, dict):
        raise ValueError("triggers must be an object")
    allowed_trig = set(REVIEW_CONFIG_DEFAULTS["triggers"])
    unknown = set(trig) - allowed_trig
    if unknown:
        raise ValueError(f"unknown trigger keys: {', '.join(sorted(unknown))}")
    for key in ("hard_gate_block", "gateway_violation", "agent_redirect", "low_alignment", "drift_spike"):
        if key in trig and not isinstance(trig[key], bool):
            raise ValueError(f"{key} must be true or false")
    if "alignment_threshold" in trig and not (_is_num(trig["alignment_threshold"]) and 0 <= trig["alignment_threshold"] <= 10):
        raise ValueError("alignment_threshold must be a number between 0 and 10")
    if "drift_threshold" in trig and not (_is_num(trig["drift_threshold"]) and 0 <= trig["drift_threshold"] <= 1):
        raise ValueError("drift_threshold must be a number between 0 and 1")
    alerts = changes.get("alerts", {})
    if not isinstance(alerts, dict):
        raise ValueError("alerts must be an object")
    allowed_alerts = set(REVIEW_CONFIG_DEFAULTS["alerts"])
    unknown = set(alerts) - allowed_alerts
    if unknown:
        raise ValueError(f"unknown alert keys: {', '.join(sorted(unknown))}")
    url = alerts.get("webhook_url")
    if url is not None and "webhook_url" in alerts:
        if not isinstance(url, str) or not url.startswith(("https://", "http://")) or len(url) > 512:
            raise ValueError("webhook_url must be an http(s) URL (max 512 chars) or null")
    if "alignment_avg_threshold" in alerts and not (_is_num(alerts["alignment_avg_threshold"]) and 0 <= alerts["alignment_avg_threshold"] <= 10):
        raise ValueError("alignment_avg_threshold must be a number between 0 and 10")
    if "alignment_window_turns" in alerts:
        w = alerts["alignment_window_turns"]
        if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= 500:
            raise ValueError("alignment_window_turns must be an integer between 1 and 500")
    if "backlog_max_age_days" in alerts:
        d = alerts["backlog_max_age_days"]
        if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 365:
            raise ValueError("backlog_max_age_days must be an integer between 1 and 365")

def get_org_review_config(org_id):
    """The org's review config merged over defaults (never partial)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        return _merged_review_config(settings.get("review_config"))
    finally:
        cursor.close()
        conn.close()

def set_org_review_config(org_id, changes, actor):
    """Merges a partial review_config into organizations.settings AND appends
    the compliance-log evidence row in the same transaction (mirror of
    set_org_retention_config). Returns the new merged config; raises
    ValueError on invalid input."""
    validate_review_config_changes(changes)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        old_merged = _merged_review_config(settings.get("review_config"))
        stored = settings.get("review_config") or {}
        for key, val in changes.items():
            if key in ("triggers", "alerts"):
                sub = dict(stored.get(key) or {})
                sub.update(val)
                stored[key] = sub
            else:
                stored[key] = val
        settings["review_config"] = stored
        new_merged = _merged_review_config(stored)
        if new_merged != old_merged:
            append_compliance_log(org_id, "review_config_changed", actor,
                                  {"old": old_merged, "new": new_merged},
                                  cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_org_review_config(org_id)

def evaluate_review_triggers(cfg, message_id, conversation_id, score, drift,
                             will_decision, will_stage):
    """Which review triggers does this committed turn match? Pure — no DB.

    Returns (triggers, detail). Deterministic random sampling: a turn is
    sampled iff sha256(message_id) % 10000 < pct*100, so given the journaled
    config an examiner can recompute exactly which turns were due — there is
    no cherry-picking a hash function. Native hard-gate blocks ship as
    agent redirects, so the trigger keys on will_stage alone (it also
    catches gateway hard-gate violations). agent_redirect covers the
    remaining redirect paths (phase-zero, soft Will violations, two-strike
    reflexion failures); hard-gate redirects are excluded so each event class
    answers to exactly one checkbox."""
    trig_cfg = cfg.get("triggers", {})
    triggers, detail = [], {}
    if trig_cfg.get("hard_gate_block") and will_stage == "hard_gate":
        triggers.append("hard_gate_block")
    if (trig_cfg.get("agent_redirect") and will_decision == "redirected"
            and will_stage != "hard_gate"):
        triggers.append("agent_redirect")
    if (trig_cfg.get("gateway_violation") and will_decision == "violation"
            and str(conversation_id or "").startswith("gw_")):
        triggers.append("gateway_violation")
    if trig_cfg.get("low_alignment") and score is not None:
        thr = trig_cfg.get("alignment_threshold", 6)
        if score < thr:
            triggers.append("low_alignment")
            detail["alignment_threshold"] = thr
    if trig_cfg.get("drift_spike") and drift is not None:
        dthr = trig_cfg.get("drift_threshold", 0.4)
        if drift > dthr:
            triggers.append("drift_spike")
            detail["drift_threshold"] = dthr
    pct = cfg.get("random_sample_pct") or 0
    if pct > 0:
        bucket = int(hashlib.sha256(str(message_id).encode("utf-8")).hexdigest(), 16) % 10000
        if bucket < int(round(pct * 100)):
            triggers.append("random_sample")
    if triggers:
        # Snapshot the governance numbers for every sampled turn (not just the
        # ones whose trigger fired on them) so the queue list can render
        # Alignment/Consistency without touching the encrypted row. None stays
        # None — the UI renders N/A, never a default.
        detail["spirit_score"] = score
        detail["drift"] = drift
        detail["will_decision"] = will_decision
        detail["will_stage"] = will_stage
    return triggers, detail

def _maybe_enqueue_review(cursor, org_id, message_pk, message_id, conversation_id,
                          profile_name, policy_id, policy_version, score, drift,
                          will_decision, will_stage):
    """Runs on update_audit_results' cursor/transaction. Reads the org's
    review config and inserts a review_queue row when any trigger matches.
    ON DUPLICATE refreshes triggers/detail without touching workflow state
    (a terminal commit normally happens exactly once per message)."""
    if not org_id:
        return
    cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
    row = cursor.fetchone()
    raw = row[0] if row else None
    settings = {}
    if raw:
        try:
            settings = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            settings = {}
    cfg = _merged_review_config(settings.get("review_config"))
    if not cfg.get("enabled"):
        return
    triggers, detail = evaluate_review_triggers(
        cfg, message_id, conversation_id, score, drift, will_decision, will_stage)
    if not triggers:
        return
    cursor.execute(
        "INSERT INTO review_queue (org_id, message_pk, message_id, conversation_id, "
        "profile_name, policy_id, policy_version, triggers, trigger_detail) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE triggers=VALUES(triggers), trigger_detail=VALUES(trigger_detail)",
        (org_id, message_pk, message_id, conversation_id, profile_name,
         policy_id, policy_version, json.dumps(triggers), json.dumps(detail)),
    )

def _insert_governance_record(cursor, org_id, message_pk, message_id, conversation_id,
                              profile_key, policy_id, policy_version,
                              will_decision, will_stage, score, drift, record):
    """Runs on update_audit_results' cursor/transaction. Persists the full
    per-turn governance capture (the dict the orchestrator's terminal paths
    build — draft, reflection, will reason code, ledger, blocked draft,
    memory/context snapshots, spirit vectors) as one Fernet-encrypted blob,
    plus the plaintext filter/aggregate dimensions the Audit Hub queries.
    ON DUPLICATE refreshes the capture without minting a second row (a
    terminal commit normally happens exactly once per message — same
    contract as the review-sampling hook)."""
    # Every record names the TCB that produced it (backlog 39): the boot-time
    # Trusted Computing Base fingerprint and intact/tainted state, the way a
    # kernel oops report carries taint flags. Stamped HERE, in the one writer every
    # governance path funnels through, so no path can mint an unattested
    # record. setdefault, not overwrite: a record that already carries a stamp
    # (a replayed capture) keeps the TCB it was actually produced under.
    from ..core.integrity import tcb_stamp
    record = dict(record)
    record.setdefault("tcb", tcb_stamp())
    record_enc = crypto.encrypt_value(json.dumps(record, ensure_ascii=False, default=str))
    cursor.execute(
        "INSERT INTO governance_records (message_pk, message_id, conversation_id, "
        "org_id, user_id, profile_key, policy_id, policy_version, will_decision, "
        "will_stage, spirit_score, drift, intellect_model, record_enc) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE record_enc=VALUES(record_enc), "
        "spirit_score=VALUES(spirit_score), drift=VALUES(drift), "
        "will_decision=VALUES(will_decision), will_stage=VALUES(will_stage)",
        (message_pk, message_id, conversation_id, org_id,
         record.get("userId"), profile_key, policy_id, policy_version,
         will_decision, will_stage, score, drift,
         record.get("intellectModel"), record_enc),
    )

# ---------------------------------------------------------------------------
# GOVERNANCE RECORDS READ SURFACE (native Audit Hub)
# ---------------------------------------------------------------------------
# KPIs, trend, and explorer read only the plaintext filter/aggregate columns;
# decryption happens exclusively in the drill-down, prompt search, and export
# paths. "Flagged" is computed, never stored — the same line as the Review
# triggers' defaults (alignment < 6 or drift > 0.4).

_GOV_FLAGGED_SQL = "(spirit_score < 6 OR drift > 0.4)"
# Prompt text is not indexable by design (it lives only inside the encrypted
# blob), so search decrypt-scans the filtered window under this hard cap.
GOVERNANCE_SEARCH_CAP = 5_000
GOVERNANCE_EXPORT_CAP = 10_000

# Sentinel scope for records whose org_id is NULL. `org_id = NULL` is never true
# in SQL, so an unqualified "org_id=%s" makes those rows invisible to every Audit
# Hub read and to both exports.
#
# OPERATOR TOOLING ONLY — must never be reachable from an org-scoped HTTP route.
# A record with no org belongs to no tenant, so surfacing it in one org's Audit
# Hub would show that org's admin turns that are not theirs (public-bot
# conversations from anyone). Every role in rbac.ROLES is org-scoped; there is no
# platform superuser to gate it behind, so the exposure would be unavoidable.
# That would be a worse defect than the invisibility. The real fix is upstream:
# stop creating unattributed records. See scripts/audit_unattributed.py.
UNATTRIBUTED_ORG = "__unattributed__"


# Width of EVERY conversation-id column in the schema: conversations.id,
# chat_history.conversation_id, governance_records.conversation_id,
# chat_audit_trail.conversation_id, review_queue.conversation_id and
# saved_content.conversation_id are all char(36) — the width is for a UUID.
#
# This is a caller-supplied value on /api/public/process_prompt and
# /api/bot/process_prompt, and nothing used to check it. An over-long id reached
# `INSERT INTO conversations` and MySQL raised 1406 "Data too long for column
# 'id'", which the caller saw as a bare HTTP 500 with an HTML error page — and
# a browser widget saw as "Unexpected token '<' ... is not valid JSON", pointing
# nowhere near the real cause. Found the hard way: the WordPress plugin's
# conversation id was lengthened to 128 CSPRNG bits, taking
# "wp_safi_chat_" + 32 hex to 45 characters, and every send broke.
#
# Validate at the edge and return 400 instead. Widening the columns was
# considered and rejected: six tables, a governance schema migration, and no
# benefit over telling integrators the limit.
CONVERSATION_ID_MAX_LEN = 36

def _governance_where(org_id, profile=None, policy_id=None, date_from=None, date_to=None):
    if org_id == UNATTRIBUTED_ORG:
        where = ["org_id IS NULL"]
        params = []
    else:
        where = ["org_id=%s"]
        params = [org_id]
    if profile:
        where.append("profile_key=%s")
        params.append(profile)
    if policy_id:
        where.append("policy_id=%s")
        params.append(policy_id)
    if date_from:
        where.append("created_at>=%s")
        params.append(date_from)
    if date_to:
        where.append("created_at<%s")
        params.append(date_to)
    return " AND ".join(where), params

def list_governance_filters(org_id):
    """Profiles and policies that actually have governance records for this
    org — replaces the Streamlit 'scan the 5 newest files' heuristic."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT profile_key FROM governance_records "
            "WHERE org_id=%s AND profile_key IS NOT NULL ORDER BY profile_key", (org_id,))
        profiles = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT DISTINCT policy_id FROM governance_records "
            "WHERE org_id=%s AND policy_id IS NOT NULL ORDER BY policy_id", (org_id,))
        policies = [r[0] for r in cursor.fetchall()]
        return {"profiles": profiles, "policies": policies}
    finally:
        cursor.close()
        conn.close()

def governance_summary(org_id, profile=None, policy_id=None, date_from=None, date_to=None):
    """One SQL pass over the plaintext columns. Metric definitions ported
    exactly from the Streamlit Audit Hub (they encode deliberate decisions):
    Alignment averages APPROVED turns only — redirected turns carry a
    redirect-quality score from a separate rubric, reported on its own, so
    pooling them would inflate compliance when an agent blocks gracefully.
    Overall score = clip(avgAlignment − avgDrift×10, 1, 10). Empty windows
    return None everywhere — the UI renders N/A, never a default."""
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT COUNT(*), "
            f"AVG(CASE WHEN will_decision='approve' THEN spirit_score END), "
            f"AVG(CASE WHEN will_decision='redirected' THEN spirit_score END), "
            f"AVG(drift), "
            f"SUM(will_decision='redirected'), "
            f"SUM(will_decision='violation'), "
            f"SUM({_GOV_FLAGGED_SQL}) "
            f"FROM governance_records WHERE {where}", tuple(params))
        (total, avg_alignment, avg_redirect_quality, avg_drift,
         interventions, violations, flagged) = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    total = int(total or 0)
    avg_alignment = float(avg_alignment) if avg_alignment is not None else None
    avg_redirect_quality = float(avg_redirect_quality) if avg_redirect_quality is not None else None
    avg_drift = float(avg_drift) if avg_drift is not None else None
    consistency = (1 - avg_drift) * 100 if avg_drift is not None else None
    if avg_alignment is not None and avg_drift is not None:
        overall = min(max(avg_alignment - avg_drift * 10, 1.0), 10.0)
    else:
        overall = avg_alignment
    interventions = int(interventions or 0)
    return {
        "total_audits": total,
        "overall_score": overall,
        "avg_alignment": avg_alignment,
        "avg_redirect_quality": avg_redirect_quality,
        "avg_consistency": consistency,
        "interventions": interventions,
        "intervention_rate": (interventions / total * 100) if total else None,
        "violations": int(violations or 0),
        "flagged": int(flagged or 0),
    }

def governance_trend(org_id, bucket="day", profile=None, policy_id=None,
                     date_from=None, date_to=None):
    """Per-bucket mean drift/consistency + turn count for the trend chart.
    Moving-average smoothing stays client-side (a display choice)."""
    fmt = "%Y-%m-%d %H:00" if bucket == "hour" else "%Y-%m-%d"
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT DATE_FORMAT(created_at, '{fmt}'), AVG(drift), COUNT(*), "
            f"COUNT(drift) FROM governance_records WHERE {where} "
            f"GROUP BY 1 ORDER BY 1", tuple(params))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    out = []
    for b, avg_drift, turns, drift_turns in rows:
        avg_drift = float(avg_drift) if avg_drift is not None else None
        out.append({
            "bucket": b,
            "avg_drift": avg_drift,
            "avg_consistency": (1 - avg_drift) * 100 if avg_drift is not None else None,
            "turns": int(turns),
            "scored_turns": int(drift_turns),
        })
    return out

def governance_trend_by_profile(org_id, bucket="day", profile=None, policy_id=None,
                                date_from=None, date_to=None):
    """The same buckets as governance_trend(), split one series per agent.

    Why this exists: governance_trend()'s mean is taken over *turns*, so a
    high-volume agent dominates it. On 2026-07-24 in dev, one agent sat at
    drift 0.0 over 7 turns and another at 0.6163 over 2, and the pooled line
    plotted 0.137 — a consistency of 86% that described neither agent. Drift is only ever meaningful per agent (spirit_memory is keyed on
    profile_name, so every turn's drift is a distance from that agent's own mu),
    which is what makes the split the honest default rather than a nicety.

    Returns a list of series ordered by scored turns, descending:
        [{"profile_key", "turns", "scored_turns", "buckets": [...]}, ...]
    Each series' buckets carry the same keys governance_trend() returns.
    """
    fmt = "%Y-%m-%d %H:00" if bucket == "hour" else "%Y-%m-%d"
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT profile_key, DATE_FORMAT(created_at, '{fmt}'), AVG(drift), "
            f"COUNT(*), COUNT(drift) FROM governance_records WHERE {where} "
            f"GROUP BY 1, 2 ORDER BY 1, 2", tuple(params))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    series = {}
    for key, b, avg_drift, turns, drift_turns in rows:
        # profile_key is NULL on pre-attribution rows; keep them in their own
        # bucket rather than silently folding them into a named agent.
        key = key or ""
        s = series.setdefault(key, {"profile_key": key, "turns": 0,
                                    "scored_turns": 0, "buckets": []})
        avg_drift = float(avg_drift) if avg_drift is not None else None
        s["turns"] += int(turns)
        s["scored_turns"] += int(drift_turns)
        s["buckets"].append({
            "bucket": b,
            "avg_drift": avg_drift,
            "avg_consistency": (1 - avg_drift) * 100 if avg_drift is not None else None,
            "turns": int(turns),
            "scored_turns": int(drift_turns),
        })
    return sorted(series.values(), key=lambda s: s["scored_turns"], reverse=True)

_GOV_EVENT_COLUMNS = (
    "message_pk, message_id, conversation_id, profile_key, policy_id, "
    "policy_version, will_decision, will_stage, spirit_score, drift, "
    "intellect_model, user_id, created_at"
)

def _gov_filter_clause(flt):
    if flt == "flagged":
        return _GOV_FLAGGED_SQL
    if flt == "approved":
        return "will_decision='approve'"
    if flt == "redirected":
        return "will_decision='redirected'"
    if flt == "violation":
        return "will_decision='violation'"
    return None

def list_governance_events(org_id, profile=None, policy_id=None, flt=None,
                           date_from=None, date_to=None, limit=50, offset=0):
    """Explorer rows from plaintext columns only — no decryption. Returns
    (rows, total) where total counts everything matching the filters."""
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    clause = _gov_filter_clause(flt)
    if clause:
        where += f" AND {clause}"
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT COUNT(*) AS n FROM governance_records WHERE {where}", tuple(params))
        total = cursor.fetchone()["n"]
        cursor.execute(
            f"SELECT {_GOV_EVENT_COLUMNS} FROM governance_records WHERE {where} "
            f"ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset))
        return cursor.fetchall(), total
    finally:
        cursor.close()
        conn.close()

def search_governance_events(org_id, q, profile=None, policy_id=None, flt=None,
                             date_from=None, date_to=None, limit=50):
    """Prompt search: decrypt-and-scan within the filtered window under a hard
    row cap (the examiner-export cap pattern — prompt text is deliberately not
    indexable). Raises ValueError when the window exceeds the cap so the
    caller can tell the user to narrow the range."""
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    clause = _gov_filter_clause(flt)
    if clause:
        where += f" AND {clause}"
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT COUNT(*) AS n FROM governance_records WHERE {where}", tuple(params))
        window = cursor.fetchone()["n"]
        if window > GOVERNANCE_SEARCH_CAP:
            raise ValueError(
                f"search window matches {window} records (cap {GOVERNANCE_SEARCH_CAP}) — narrow the date range")
        cursor.execute(
            f"SELECT {_GOV_EVENT_COLUMNS}, record_enc FROM governance_records "
            f"WHERE {where} ORDER BY created_at DESC, id DESC", tuple(params))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    needle = q.lower()
    matches = []
    for row in rows:
        try:
            record = json.loads(crypto.decrypt_value(row.pop("record_enc")))
        except (ValueError, TypeError):
            continue
        prompt = str(record.get("userPrompt") or "")
        if needle in prompt.lower():
            row["prompt_preview"] = prompt[:160]
            matches.append(row)
            if len(matches) >= limit:
                break
    return matches, window

def get_governance_event(org_id, message_pk):
    """Drill-down: the decrypted capture + provenance columns + hash-chain
    verification + a reviewed marker when a review_queue row exists (the
    cross-link to the Review tab). Returns None when the record is missing
    or belongs to another org."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT {_GOV_EVENT_COLUMNS}, record_enc FROM governance_records "
            f"WHERE org_id=%s AND message_pk=%s", (org_id, message_pk))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "SELECT audit_status, model_attribution, timestamp FROM chat_history WHERE id=%s",
            (message_pk,))
        chat = cursor.fetchone()
        cursor.execute(
            "SELECT id, status, triggers FROM review_queue WHERE message_pk=%s AND org_id=%s",
            (message_pk, org_id))
        review = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    try:
        record = json.loads(crypto.decrypt_value(row.pop("record_enc")))
    except (ValueError, TypeError):
        record = None
    if review:
        review["triggers"] = _review_json(review.get("triggers"), [])
    return {
        "event": row,
        "record": record,
        "chat": chat,
        "trail": verify_message_audit_trail(message_pk),
        "review": review,
    }

def export_governance_events(org_id, profile=None, policy_id=None, flt=None,
                             date_from=None, date_to=None):
    """Filtered records, decrypted, for download — capped like the examiner
    export. The CALLER must custody-log the export (counts + filters, never
    content) to org_compliance_log before returning bytes."""
    where, params = _governance_where(org_id, profile, policy_id, date_from, date_to)
    clause = _gov_filter_clause(flt)
    if clause:
        where += f" AND {clause}"
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT COUNT(*) AS n FROM governance_records WHERE {where}", tuple(params))
        total = cursor.fetchone()["n"]
        if total > GOVERNANCE_EXPORT_CAP:
            raise ValueError(
                f"export matches {total} records (cap {GOVERNANCE_EXPORT_CAP}) — narrow the date range")
        cursor.execute(
            f"SELECT {_GOV_EVENT_COLUMNS}, record_enc FROM governance_records "
            f"WHERE {where} ORDER BY created_at DESC, id DESC", tuple(params))
        rows = cursor.fetchall()

        # Integrity evidence per record. governance_records is a separate table
        # from chat_audit_trail, so the hashes have to be joined in — batched in
        # ONE query, because verify_message_audit_trail() opens its own
        # connection per message and this export is capped at 10,000 rows.
        chains = {}
        pks = sorted({r["message_pk"] for r in rows if r["message_pk"] is not None})
        if pks:
            placeholders = ",".join(["%s"] * len(pks))
            cursor.execute(
                f"SELECT * FROM chat_audit_trail WHERE message_pk IN ({placeholders}) "
                "ORDER BY message_pk, id", tuple(pks))
            grouped = {}
            for e in cursor.fetchall():
                grouped.setdefault(e["message_pk"], []).append(e)
            for pk, entries in grouped.items():
                verdict = _verify_chain_entries(entries)
                # entry_hash/prev_hash come from the verdict now — one source
                # for the tip, so this export and the drill-down cannot drift.
                # prev_hash is included so a recipient can re-walk the chain
                # rather than take the verdict on trust.
                chains[pk] = {
                    "entry_hash": verdict["entry_hash"],
                    "prev_hash": verdict["prev_hash"],
                    "chain_entries": verdict["entries"],
                    "chain_valid": verdict["valid"],
                    "chain_first_bad_id": verdict["first_bad_id"],
                }
    finally:
        cursor.close()
        conn.close()

    # No trail rows is an ABSENCE of evidence, not a passing chain: report nulls
    # and a zero count, never chain_valid=true. Same rule as the N/A-not-10.0
    # score chip and the review export.
    no_chain = {"entry_hash": None, "prev_hash": None, "chain_entries": 0,
                "chain_valid": None, "chain_first_bad_id": None}

    out = []
    for row in rows:
        enc = row.pop("record_enc")
        try:
            record = json.loads(crypto.decrypt_value(enc))
        except (ValueError, TypeError):
            record = None
        row["record"] = record
        # Art. 50(2): every governance record captures an AI-generated turn.
        row["ai_generated"] = True
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = utc_isoformat(row["created_at"])
        row["integrity"] = dict(chains.get(row["message_pk"], no_chain))
        out.append(row)
    return out

def _review_json(value, default):
    """Parses a JSON column value that may arrive as str or already-parsed."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default

_REVIEW_QUEUE_LIST_FIELDS = (
    "id, org_id, message_pk, message_id, conversation_id, profile_name, "
    "policy_id, policy_version, triggers, trigger_detail, status, "
    "reviewed_by, reviewer_email, reviewed_at, created_at"
)

def _review_row_public(row):
    """Normalizes a review_queue dict row for API consumption: JSON columns
    parsed, reason never included (list surface is workflow-only; the detail
    endpoint decrypts it explicitly)."""
    row.pop("reason_enc", None)
    row["triggers"] = _review_json(row.get("triggers"), [])
    row["trigger_detail"] = _review_json(row.get("trigger_detail"), {})
    return row

def list_review_queue(org_id, status=None, trigger=None, profile=None,
                      limit=50, offset=0):
    """Queue rows for the org, newest first — workflow fields only, nothing
    encrypted. Returns (rows, total) where total counts all rows matching the
    filters (for pagination)."""
    where = ["org_id=%s"]
    params = [org_id]
    if status:
        where.append("status=%s")
        params.append(status)
    if trigger:
        where.append("JSON_CONTAINS(triggers, %s)")
        params.append(json.dumps(trigger))
    if profile:
        where.append("profile_name=%s")
        params.append(profile)
    where_sql = " AND ".join(where)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT COUNT(*) AS n FROM review_queue WHERE {where_sql}",
                       tuple(params))
        total = cursor.fetchone()["n"]
        cursor.execute(
            f"SELECT {_REVIEW_QUEUE_LIST_FIELDS} FROM review_queue "
            f"WHERE {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s",
            tuple(params) + (int(limit), int(offset)),
        )
        return [_review_row_public(r) for r in cursor.fetchall()], total
    finally:
        cursor.close()
        conn.close()

def get_review_item(org_id, queue_id):
    """One queue row with everything a reviewer needs to make the call:
    the decrypted turn (content, conscience ledger, spirit note, reasoning
    log, will provenance, model attribution), the user prompt that produced
    it, prior 'review' trail entries, and the hash-chain verification result.
    Returns None when the row doesn't exist in this org. turn is None when
    the underlying message was retention-purged (queue row outlives it)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM review_queue WHERE id=%s AND org_id=%s",
                       (queue_id, org_id))
        queue = cursor.fetchone()
        if not queue:
            return None
        reason = crypto.decrypt_value(queue.pop("reason_enc", None))
        queue = _review_row_public(queue)
        queue["reason"] = reason

        cursor.execute(
            "SELECT id, message_id, role, content, audit_status, conscience_ledger, "
            "spirit_score, drift, spirit_note, profile_name, policy_id, policy_version, "
            "model_attribution, will_decision, will_stage, reasoning_log, timestamp "
            "FROM chat_history WHERE id=%s", (queue["message_pk"],))
        turn = cursor.fetchone()
        crypto.decrypt_fields(turn, ("content", "spirit_note", "conscience_ledger", "reasoning_log"))

        user_prompt = None
        if turn:
            cursor.execute(
                "SELECT content FROM chat_history WHERE conversation_id=%s "
                "AND role='user' AND id < %s ORDER BY id DESC LIMIT 1",
                (queue["conversation_id"], queue["message_pk"]))
            prow = cursor.fetchone()
            if prow:
                user_prompt = crypto.decrypt_value(prow["content"])

        cursor.execute(
            "SELECT id, actor, state, event_at FROM chat_audit_trail "
            "WHERE message_pk=%s AND action='review' ORDER BY id",
            (queue["message_pk"],))
        history = []
        for e in cursor.fetchall():
            state = _review_json(e.get("state"), {})
            state["reason"] = crypto.decrypt_value(state.pop("reason_enc", None))
            history.append({"trail_id": e["id"], "actor": e["actor"],
                            "event_at": e["event_at"], **state})
    finally:
        cursor.close()
        conn.close()
    return {
        "queue": queue,
        "turn": turn,
        "user_prompt": user_prompt,
        "review_history": history,
        "chain": verify_message_audit_trail(queue["message_pk"]),
    }

def apply_review_action(org_id, queue_id, action, reason, reviewer_id, reviewer_email):
    """Records a supervisory disposition. In ONE transaction: locks the queue
    row, rejects anything not 'pending', updates workflow state, and appends
    the 'review' entry to the message's chat_audit_trail hash chain — the
    trail entry is the regulatory artifact (Art. 14 auditable intervention /
    FINRA sign-off); the queue row is merely workflow state. An override is a
    documented supervisory determination about a delivered message — it does
    NOT retract or alter the message itself.

    Separation of duties: a reviewer may not dispose of a turn from their own
    conversation. FINRA 3110/3120 supervisory review means someone OTHER than
    the principal signs off, and self-approval is the first thing an examiner
    tests. Enforced here rather than in the route so every caller — API, and
    any future batch or scripted path — inherits it.

    Returns the updated queue row, or None when the row doesn't exist in this
    org. Raises ValueError on invalid action, missing override reason, or a
    row that is no longer pending; SelfReviewError when the reviewer authored
    the turn."""
    if action not in ("approve", "override"):
        raise ValueError("action must be 'approve' or 'override'")
    reason = (reason or "").strip()
    if action == "override" and not reason:
        raise ValueError("a reason is mandatory for an override")
    status = "approved" if action == "approve" else "overridden"
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM review_queue WHERE id=%s AND org_id=%s FOR UPDATE",
                       (queue_id, org_id))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return None
        if row["status"] != "pending":
            conn.rollback()
            raise ValueError(f"already reviewed: this item is '{row['status']}'")
        # Separation of duties. A purged conversation leaves no owner to compare
        # against; that is allowed through rather than blocking review of every
        # aged turn, since an unknown author cannot be shown to be the reviewer.
        cursor.execute("SELECT user_id FROM conversations WHERE id=%s",
                       (row["conversation_id"],))
        owner = cursor.fetchone()
        if owner and str(owner["user_id"]) == str(reviewer_id):
            conn.rollback()
            raise SelfReviewError(
                "separation of duties: you cannot review a turn from your own "
                "conversation — another admin or auditor must dispose of this item"
            )
        reason_enc = crypto.encrypt_value(reason) if reason else None
        cursor.execute(
            "UPDATE review_queue SET status=%s, reviewed_by=%s, reviewer_email=%s, "
            "reviewed_at=NOW(), reason_enc=%s WHERE id=%s",
            (status, reviewer_id, reviewer_email, reason_enc, queue_id))
        _chat_trail_append(
            cursor, row["message_pk"], row["message_id"], row["conversation_id"],
            "review", f"user:{reviewer_id}",
            {
                "disposition": status,
                "triggers": _review_json(row["triggers"], []),
                "reason_enc": reason_enc,
                "policy_id": row["policy_id"],
                "policy_version": row["policy_version"],
                "queue_id": row["id"],
            },
            org_id=org_id,
        )
        conn.commit()
        cursor.execute(f"SELECT {_REVIEW_QUEUE_LIST_FIELDS} FROM review_queue WHERE id=%s",
                       (queue_id,))
        return _review_row_public(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()

def get_review_report(org_id, date_from, date_to):
    """Supervisory coverage report for [date_from, date_to). Total org turns
    are counted from chat_audit_trail terminal 'update' entries (chat_history
    has no org_id; entries with a NULL org stamp are pre-Phase-E and fall
    outside the denominator — reports must treat that era as 'pre-Phase-E',
    never 'approved'). Everything else derives from review_queue rows created
    in the window."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT COUNT(DISTINCT message_pk) AS n FROM chat_audit_trail "
            "WHERE org_id=%s AND action='update' AND message_id IS NOT NULL "
            "AND created_at >= %s AND created_at < %s",
            (org_id, date_from, date_to))
        total_turns = cursor.fetchone()["n"]
        cursor.execute(
            "SELECT rq.id, rq.triggers, rq.status, rq.reviewer_email, "
            "rq.created_at, rq.reviewed_at, ch.id AS live_pk "
            "FROM review_queue rq LEFT JOIN chat_history ch ON ch.id = rq.message_pk "
            "WHERE rq.org_id=%s AND rq.created_at >= %s AND rq.created_at < %s",
            (org_id, date_from, date_to))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    trigger_counts, dispositions, per_reviewer = {}, {"pending": 0, "approved": 0, "overridden": 0}, {}
    latencies, purged = [], 0
    for r in rows:
        for t in _review_json(r["triggers"], []):
            trigger_counts[t] = trigger_counts.get(t, 0) + 1
        dispositions[r["status"]] = dispositions.get(r["status"], 0) + 1
        if r["live_pk"] is None:
            purged += 1
        if r["status"] != "pending" and r["reviewed_at"] and r["created_at"]:
            per_reviewer[r["reviewer_email"] or "unknown"] = \
                per_reviewer.get(r["reviewer_email"] or "unknown", 0) + 1
            latencies.append((r["reviewed_at"] - r["created_at"]).total_seconds())

    latencies.sort()
    n = len(latencies)
    median_latency = None
    if n:
        median_latency = latencies[n // 2] if n % 2 else (latencies[n // 2 - 1] + latencies[n // 2]) / 2
    sampled = len(rows)
    reviewed = sampled - dispositions.get("pending", 0)
    return {
        "range": {"from": str(date_from), "to": str(date_to)},
        "total_turns": total_turns,
        "sampled": sampled,
        "sampled_pct_of_turns": round(sampled * 100.0 / total_turns, 2) if total_turns else None,
        "trigger_counts": trigger_counts,
        "reviewed": reviewed,
        "dispositions": dispositions,
        "median_review_latency_seconds": round(median_latency, 1) if median_latency is not None else None,
        "per_reviewer": per_reviewer,
        "purged_message_rows": purged,
        "note": ("total_turns counts governed turns committed since will-decision "
                 "provenance shipped (trail entries carrying an org stamp); earlier "
                 "turns are pre-Phase-E and not in the denominator."),
    }

REVIEW_EXPORT_CAP = 5000

def get_review_items_for_export(org_id, date_from, date_to, cap=REVIEW_EXPORT_CAP):
    """One row per review_queue item created in [date_from, date_to) — the
    examiner-grade counterpart to get_review_report()'s aggregates.

    Carries what the aggregate report cannot: the decrypted reviewer rationale
    (the artifact that proves a human looked and said why), the governance
    provenance the turn was judged under (agent, policy id + version), whether
    the underlying message still exists, and each item's hash-chain verdict.

    Returns (items, truncated). `truncated` is True when more rows matched than
    the cap emitted — the caller MUST surface it, because a silently short
    export reads as "this is all of it".
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT rq.*, ch.id AS live_pk FROM review_queue rq "
            "LEFT JOIN chat_history ch ON ch.id = rq.message_pk "
            "WHERE rq.org_id=%s AND rq.created_at >= %s AND rq.created_at < %s "
            "ORDER BY rq.created_at, rq.id LIMIT %s",
            (org_id, date_from, date_to, cap + 1))
        rows = cursor.fetchall()
        truncated = len(rows) > cap
        rows = rows[:cap]

        # One batched query for every trail entry we need, then verify in
        # Python — verify_message_audit_trail() opens its own connection per
        # message, which would be one connection per exported row.
        chains = {}
        pks = [r["message_pk"] for r in rows if r["message_pk"] is not None]
        if pks:
            placeholders = ",".join(["%s"] * len(pks))
            cursor.execute(
                f"SELECT * FROM chat_audit_trail WHERE message_pk IN ({placeholders}) "
                "ORDER BY message_pk, id", tuple(pks))
            grouped = {}
            for e in cursor.fetchall():
                grouped.setdefault(e["message_pk"], []).append(e)
            chains = {pk: _verify_chain_entries(entries) for pk, entries in grouped.items()}
    finally:
        cursor.close()
        conn.close()

    items = []
    for r in rows:
        reason = crypto.decrypt_value(r.pop("reason_enc", None))
        live_pk = r.pop("live_pk", None)
        latency = None
        if r["reviewed_at"] and r["created_at"]:
            latency = round((r["reviewed_at"] - r["created_at"]).total_seconds(), 1)
        # No trail rows at all is not a passing chain — it is an absence of
        # evidence, and must not read as "verified".
        chain = chains.get(r["message_pk"])
        items.append({
            "queue_id": r["id"],
            "message_id": r["message_id"],
            "conversation_id": r["conversation_id"],
            "agent": r["profile_name"],
            "policy_id": r["policy_id"],
            "policy_version": r["policy_version"],
            "triggers": _review_json(r.get("triggers"), []),
            "trigger_detail": _review_json(r.get("trigger_detail"), {}),
            "status": r["status"],
            "reviewer_email": r["reviewer_email"],
            "reviewed_by": r["reviewed_by"],
            "created_at": r["created_at"],
            "reviewed_at": r["reviewed_at"],
            "review_latency_seconds": latency,
            "evidence_present": live_pk is not None,
            "chain_entries": chain["entries"] if chain else 0,
            "chain_valid": chain["valid"] if chain else None,
            "chain_first_bad_id": chain["first_bad_id"] if chain else None,
            "reason": reason,
        })
    return items, truncated

def recent_org_profile_scores(org_id, profile_name, limit):
    """Last N Alignment scores for an org+profile, newest first — the rolling
    window for the alignment_degradation alert. Approved turns only (redirects
    carry a redirect-quality score from a separate rubric; pooling them would
    poison the mean — same rule as the Audit Hub KPIs). Org attribution rides
    the org-stamped terminal trail entry, so pre-Phase-E turns fall outside
    the window by construction."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT ch.spirit_score FROM chat_audit_trail t "
            "JOIN chat_history ch ON ch.id = t.message_pk "
            "WHERE t.org_id=%s AND t.action='update' AND ch.profile_name=%s "
            "AND ch.will_decision='approve' AND ch.spirit_score IS NOT NULL "
            "GROUP BY t.message_pk, ch.spirit_score ORDER BY t.message_pk DESC LIMIT %s",
            (org_id, profile_name, int(limit)))
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

def oldest_pending_review_age_days(org_id):
    """Age in days of the oldest pending queue row, or None when the queue is
    clear — the queue_backlog alert input."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT TIMESTAMPDIFF(SECOND, MIN(created_at), NOW()) / 86400.0 "
            "FROM review_queue WHERE org_id=%s AND status='pending'", (org_id,))
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    finally:
        cursor.close()
        conn.close()

def recent_alert_exists(org_id, alert_type, profile, hours):
    """True when an alert of this type fired for this (org, profile) within
    the cooldown window. profile None matches org-level alerts (backlog)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT detail FROM review_alerts WHERE org_id=%s AND alert_type=%s "
            "AND created_at > NOW() - INTERVAL %s HOUR ORDER BY id DESC LIMIT 50",
            (org_id, alert_type, int(hours)))
        for (raw,) in cursor.fetchall():
            detail = _review_json(raw, {})
            if detail.get("profile") == profile:
                return True
        return False
    finally:
        cursor.close()
        conn.close()

def insert_review_alert(org_id, alert_type, detail, delivered):
    """Journals one Art. 72 alert (append-only — the delivery outcome is
    known before the insert; there is deliberately no update helper)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO review_alerts (org_id, alert_type, detail, delivered) "
            "VALUES (%s, %s, %s, %s)",
            (org_id, alert_type, json.dumps(detail), json.dumps(delivered)))
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()

def sweep_orphaned_pending_reviews(org_id):
    """Removes PENDING queue rows whose underlying message was retention-
    purged — there is nothing left to review. Reviewed rows are kept even
    when orphaned: after the chain (and its 'review' entries) is purged, the
    queue row is the last remnant of the disposition, and the coverage
    report counts these as purged. Returns rows removed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE rq FROM review_queue rq LEFT JOIN chat_history ch ON ch.id = rq.message_pk "
            "WHERE rq.org_id=%s AND rq.status='pending' AND ch.id IS NULL", (org_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()

def list_orgs_with_review_enabled():
    """Org ids whose review_config exists — the backlog-check worklist for
    the daily timer (enabled is verified against merged config by the
    caller; the LIKE is just a cheap prefilter)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM organizations WHERE settings LIKE '%review_config%'")
        return [r["id"] for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

def list_review_alerts(org_id, limit=20):
    """Recent Art. 72 monitoring alerts, newest first (append-only journal)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, alert_type, detail, delivered, created_at FROM review_alerts "
            "WHERE org_id=%s ORDER BY id DESC LIMIT %s",
            (org_id, int(limit)))
        rows = cursor.fetchall()
        for r in rows:
            r["detail"] = _review_json(r.get("detail"), {})
            r["delivered"] = _review_json(r.get("delivered"), {})
        return rows
    finally:
        cursor.close()
        conn.close()

def list_orgs_with_retention():
    """All non-demo orgs that have any retention config — the purge worklist."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name, settings FROM organizations "
                       "WHERE settings LIKE '%retention_years%' OR settings LIKE '%legal_hold%'")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def _would_orphan_org(cursor, user_id, org_id):
    """True when removing this user's admin rights leaves the org with none.
    Counted inside the caller's transaction so a concurrent demotion of the
    other admin cannot slip between the check and the write."""
    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE org_id=%s AND role='admin' AND id<>%s",
        (org_id, user_id))
    return (cursor.fetchone()[0] or 0) == 0


def update_member_role(user_id, org_id, new_role, actor="system"):
    """Role change revokes the target's live sessions in the SAME transaction
    and journals the change — a demoted admin must not keep an admin session
    (fresh role is re-read per request, but revocation forces a clean re-auth
    and provides the examiner-facing event).

    Refuses to demote the last admin (LastAdminError): an org with no admin
    cannot author policy, manage members, or set the provider allow-list, and
    nothing in the product can restore it."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role FROM users WHERE id=%s AND org_id=%s FOR UPDATE",
                       (user_id, org_id))
        row = cursor.fetchone()
        prior_role = row[0] if row else None
        if prior_role == 'admin' and new_role != 'admin' and _would_orphan_org(cursor, user_id, org_id):
            conn.rollback()
            raise LastAdminError(
                "this is the organization's only admin — promote another member "
                "to admin before changing this role"
            )
        cursor.execute("UPDATE users SET role=%s WHERE id=%s AND org_id=%s", (new_role, user_id, org_id))
        revoked = _revoke_user_sessions_cursor(cursor, user_id, f"admin:{actor}")
        log_auth_event("role_changed", f"admin:{actor}", org_id=org_id, user_id=user_id,
                       detail={"prior_role": prior_role, "new_role": new_role,
                               "sessions_revoked": revoked}, cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def remove_member_from_org(user_id, org_id, actor="system"):
    """Removal revokes all the member's live sessions in the SAME transaction
    and journals member_removed — off-boarding evidence (design §3.4).

    Refuses to remove the last admin (LastAdminError) for the same reason
    update_member_role does — removal strips admin just as effectively as a
    demotion, so guarding only the demotion path would leave the door open."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role FROM users WHERE id=%s AND org_id=%s FOR UPDATE",
                       (user_id, org_id))
        row = cursor.fetchone()
        if row and row[0] == 'admin' and _would_orphan_org(cursor, user_id, org_id):
            conn.rollback()
            raise LastAdminError(
                "this is the organization's only admin — promote another member "
                "to admin before removing this one"
            )
        # We simply set org_id to NULL and role to 'member' (resetting them)
        cursor.execute("UPDATE users SET org_id=NULL, role='member' WHERE id=%s AND org_id=%s", (user_id, org_id))
        removed = cursor.rowcount > 0
        revoked = _revoke_user_sessions_cursor(cursor, user_id, "system:member_removed")
        log_auth_event("member_removed", f"admin:{actor}", org_id=org_id, user_id=user_id,
                       detail={"sessions_revoked": revoked, "removed": removed}, cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# ENTERPRISE IDENTITY PHASE 1 — sessions, auth events, invitations
# (docs/internal/DESIGN_ENTERPRISE_IDENTITY.md)
# -------------------------------------------------------------------------

# Platform defaults when an org has not configured identity settings
# (consumer-friendly; a regulated org tightens via set_org_identity_config).
IDENTITY_DEFAULTS = {
    "idle_timeout_minutes": 7 * 24 * 60,   # 7 days
    "session_lifetime_hours": 30 * 24,     # 30 days absolute
    "join_policy": "domain_auto_join",     # preserves pre-Phase-1 behavior
    "require_mfa": False,                  # org opt-in (HIPAA/SEC posture)
    "ms_tenant_id": None,                  # Entra tid to enforce (Phase 2)
    "google_hd": None,                     # Workspace hosted domain to enforce
}
JOIN_POLICIES = ("invite_only", "domain_auto_join", "both")


def log_auth_event(event, actor, org_id=None, user_id=None, session_id=None, detail=None, cursor=None):
    """Append a row to the auth_events journal. Pass a cursor to journal
    inside the caller's transaction (lifecycle changes must not be able to
    dodge the journal); otherwise uses its own connection."""
    sql = ("INSERT INTO auth_events (org_id, user_id, session_id, event, detail, actor) "
           "VALUES (%s, %s, %s, %s, %s, %s)")
    args = (org_id, user_id, session_id, event,
            json.dumps(detail) if detail is not None else None, actor)
    if cursor is not None:
        cursor.execute(sql, args)
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def create_session(user_id, org_id, lifetime_hours, ip=None, user_agent=None, auth_context=None):
    """Create a server-side session row; returns the opaque session id — the
    only thing the cookie will hold."""
    sid = secrets.token_urlsafe(32)  # 43 chars base64url
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO sessions (id, user_id, org_id, expires_at, ip, user_agent, auth_context) "
            "VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL %s HOUR), %s, %s, %s)",
            (sid, user_id, org_id, int(lifetime_hours), ip,
             (user_agent or "")[:255] or None,
             json.dumps(auth_context) if auth_context else None),
        )
        conn.commit()
        return sid
    finally:
        cursor.close()
        conn.close()


def get_session(sid):
    """Session row plus liveness computed IN SQL (is_expired, idle_seconds) so
    the resolver never mixes Python clock/timezone with MySQL's."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT *, (expires_at <= NOW()) AS is_expired, "
            "TIMESTAMPDIFF(SECOND, last_seen_at, NOW()) AS idle_seconds "
            "FROM sessions WHERE id=%s",
            (sid,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def touch_session(sid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE sessions SET last_seen_at=NOW() WHERE id=%s", (sid,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def revoke_session(sid, revoked_by, reason="revoked"):
    """Revoke one session (idempotent). Journals session_revoked."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE sessions SET revoked_at=NOW(), revoked_by=%s WHERE id=%s AND revoked_at IS NULL",
            (revoked_by, sid),
        )
        revoked = cursor.rowcount > 0
        if revoked:
            cursor.execute("SELECT user_id, org_id FROM sessions WHERE id=%s", (sid,))
            row = cursor.fetchone()
            log_auth_event("session_revoked", revoked_by,
                           org_id=row[1] if row else None,
                           user_id=row[0] if row else None,
                           session_id=sid, detail={"reason": reason}, cursor=cursor)
        conn.commit()
        return revoked
    finally:
        cursor.close()
        conn.close()


def _revoke_user_sessions_cursor(cursor, user_id, revoked_by):
    """Same-transaction bulk revoke; returns count. Used by member lifecycle."""
    cursor.execute(
        "UPDATE sessions SET revoked_at=NOW(), revoked_by=%s "
        "WHERE user_id=%s AND revoked_at IS NULL AND expires_at > NOW()",
        (revoked_by, user_id),
    )
    return cursor.rowcount


def revoke_user_sessions(user_id, revoked_by, keep_sid=None):
    """Revoke all of a user's live sessions (optionally keeping one — 'log out
    everywhere else'). Returns count."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if keep_sid:
            cursor.execute(
                "UPDATE sessions SET revoked_at=NOW(), revoked_by=%s "
                "WHERE user_id=%s AND id != %s AND revoked_at IS NULL AND expires_at > NOW()",
                (revoked_by, user_id, keep_sid),
            )
        else:
            _revoke_user_sessions_cursor(cursor, user_id, revoked_by)
        count = cursor.rowcount
        if count:
            log_auth_event("session_revoked", revoked_by, user_id=user_id,
                           detail={"count": count, "bulk": True}, cursor=cursor)
        conn.commit()
        return count
    finally:
        cursor.close()
        conn.close()


def list_user_sessions(user_id, active_only=True):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q = ("SELECT id, user_id, org_id, created_at, last_seen_at, expires_at, "
             "revoked_at, revoked_by, ip, user_agent FROM sessions WHERE user_id=%s")
        if active_only:
            q += " AND revoked_at IS NULL AND expires_at > NOW()"
        q += " ORDER BY last_seen_at DESC"
        cursor.execute(q, (user_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def sweep_expired_sessions(older_than_days=90):
    """Delete session rows expired/revoked more than N days ago (housekeeping;
    auth_events retains the lifecycle history)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM sessions WHERE (expires_at < DATE_SUB(NOW(), INTERVAL %s DAY)) "
            "OR (revoked_at IS NOT NULL AND revoked_at < DATE_SUB(NOW(), INTERVAL %s DAY))",
            (older_than_days, older_than_days),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()


def get_org_identity_config(org_id):
    """Org identity settings with platform defaults. No org → defaults."""
    cfg = dict(IDENTITY_DEFAULTS)
    if not org_id:
        return cfg
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,))
        row = cursor.fetchone()
        settings = {}
        if row and row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        ident = settings.get("identity") or {}
        idle = ident.get("idle_timeout_minutes")
        life = ident.get("session_lifetime_hours")
        policy = ident.get("join_policy")
        if isinstance(idle, int) and 5 <= idle <= 60 * 24 * 30:
            cfg["idle_timeout_minutes"] = idle
        if isinstance(life, int) and 1 <= life <= 24 * 30:
            cfg["session_lifetime_hours"] = life
        if policy in JOIN_POLICIES:
            cfg["join_policy"] = policy
        if isinstance(ident.get("require_mfa"), bool):
            cfg["require_mfa"] = ident["require_mfa"]
        for claim_key in ("ms_tenant_id", "google_hd"):
            v = ident.get(claim_key)
            if isinstance(v, str) and v.strip():
                cfg[claim_key] = v.strip()
        return cfg
    finally:
        cursor.close()
        conn.close()


def set_org_identity_config(org_id, changes, actor):
    """Merge identity settings AND journal the change to auth_events in the
    same transaction (mirror of set_org_retention_config's contract).
    changes: any of idle_timeout_minutes (int|None resets), session_lifetime_hours
    (int|None), join_policy (str). Raises ValueError on invalid input."""
    validated = {}
    if "idle_timeout_minutes" in changes:
        v = changes["idle_timeout_minutes"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not (5 <= v <= 60 * 24 * 30)):
            raise ValueError("idle_timeout_minutes must be 5..43200 or null for the platform default")
        validated["idle_timeout_minutes"] = v
    if "session_lifetime_hours" in changes:
        v = changes["session_lifetime_hours"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 24 * 30)):
            raise ValueError("session_lifetime_hours must be 1..720 or null for the platform default")
        validated["session_lifetime_hours"] = v
    if "join_policy" in changes:
        if changes["join_policy"] not in JOIN_POLICIES:
            raise ValueError(f"join_policy must be one of {', '.join(JOIN_POLICIES)}")
        validated["join_policy"] = changes["join_policy"]
    if "require_mfa" in changes:
        if not isinstance(changes["require_mfa"], bool):
            raise ValueError("require_mfa must be true or false")
        validated["require_mfa"] = changes["require_mfa"]
    if "ms_tenant_id" in changes:
        v = changes["ms_tenant_id"]
        if v is not None:
            v = str(v).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", v):
                raise ValueError("ms_tenant_id must be the directory (tenant) GUID from Entra, or null")
        validated["ms_tenant_id"] = v or None
    if "google_hd" in changes:
        v = changes["google_hd"]
        if v is not None:
            v = str(v).strip().lower()
            if v and not re.fullmatch(r"[a-z0-9.-]{3,255}", v):
                raise ValueError("google_hd must be a Workspace domain (e.g. example.com), or null")
        validated["google_hd"] = v or None
    if not validated:
        raise ValueError("nothing to change")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        ident = settings.get("identity") or {}
        changed = {}
        for k, v in validated.items():
            old = ident.get(k)
            if old != v:
                changed[k] = {"old": old, "new": v}
                if v is None:
                    ident.pop(k, None)
                else:
                    ident[k] = v
        if changed:
            settings["identity"] = ident
            timeout_changes = {k: v for k, v in changed.items() if k != "join_policy"}
            if timeout_changes:
                log_auth_event("identity_config_changed", actor, org_id=org_id,
                               detail=timeout_changes, cursor=cursor)
            if "join_policy" in changed:
                log_auth_event("join_policy_changed", actor, org_id=org_id,
                               detail={"join_policy": changed["join_policy"]}, cursor=cursor)
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_org_identity_config(org_id)


def update_session_auth_context(sid, auth_context):
    """Replace a session's auth_context (e.g. after in-session MFA enrollment
    upgrades amr from ['pwd'] to ['pwd','otp'])."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE sessions SET auth_context=%s WHERE id=%s",
                       (json.dumps(auth_context), sid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# --- TOTP MFA (enterprise identity Phase 2) ---------------------------------

def get_user_totp(user_id):
    """{'secret': plaintext-Base32 or None, 'enabled': bool}. Secret is stored
    Fernet-encrypted; a row with a secret but no totp_enabled_at is a pending
    enrollment awaiting first-code confirmation."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT totp_secret, totp_enabled_at FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if not row or not row.get("totp_secret"):
            return {"secret": None, "enabled": False}
        return {"secret": crypto.decrypt_value(row["totp_secret"]),
                "enabled": row.get("totp_enabled_at") is not None}
    finally:
        cursor.close()
        conn.close()


def set_user_totp_pending(user_id, secret_b32):
    """Store a NEW secret as pending (not yet enforced at login). Overwrites
    any prior pending secret; refuses to overwrite an ENABLED one — the user
    must disable first (with a live code) so a hijacked session cannot
    silently swap the authenticator."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET totp_secret=%s WHERE id=%s AND totp_enabled_at IS NULL",
            (crypto.encrypt_value(secret_b32), user_id))
        if cursor.rowcount == 0:
            cursor.execute("SELECT totp_enabled_at FROM users WHERE id=%s", (user_id,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                raise ValueError("MFA is already enabled; disable it before re-enrolling")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def enable_user_totp(user_id, actor, org_id=None):
    """Flip a pending enrollment to enabled; journals mfa_enrolled in the
    same transaction."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET totp_enabled_at=NOW() "
            "WHERE id=%s AND totp_secret IS NOT NULL AND totp_enabled_at IS NULL",
            (user_id,))
        if cursor.rowcount:
            log_auth_event("mfa_enrolled", actor, org_id=org_id, user_id=user_id,
                           detail={"method": "totp"}, cursor=cursor)
        conn.commit()
        return bool(cursor.rowcount)
    finally:
        cursor.close()
        conn.close()


def disable_user_totp(user_id, actor, org_id=None):
    """Remove the secret entirely; journals mfa_disabled in the same
    transaction. Caller is responsible for verifying authority (live code
    for self-service, admin role for resets)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET totp_secret=NULL, totp_enabled_at=NULL "
            "WHERE id=%s AND totp_secret IS NOT NULL", (user_id,))
        if cursor.rowcount:
            log_auth_event("mfa_disabled", actor, org_id=org_id, user_id=user_id,
                           detail={"method": "totp"}, cursor=cursor)
        conn.commit()
        return bool(cursor.rowcount)
    finally:
        cursor.close()
        conn.close()


def create_org_invitation(org_id, email, role, invited_by, expires_days=14):
    """Create (or refresh a pending) invitation. Journals member_invited."""
    if role not in ("admin", "editor", "auditor", "member"):
        raise ValueError("invalid role")
    email = (email or "").strip().lower()
    if "@" not in email:
        raise ValueError("valid email required")
    invite_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # A verified domain is authoritative over its own people (backlog 75).
        # Without this, inviting someone at another org's verified domain before
        # they ever sign in would place them in the INVITING org: no data of
        # theirs leaks, but their turns would then be governed by the wrong
        # charter and land in the wrong audit trail, and the domain owner would
        # never see them. Refuse at the door instead. The login path enforces the
        # same rule again, since invitations can outlive a domain verification.
        invited_domain = email.split("@")[-1]
        cursor.execute(
            "SELECT id, name FROM organizations "
            "WHERE domain_verified=TRUE AND LOWER(domain_to_verify)=%s LIMIT 1",
            (invited_domain,),
        )
        owner = cursor.fetchone()
        if owner and str(owner[0]) != str(org_id):
            raise ValueError(
                f"{invited_domain} is a verified domain of another organization. "
                "Its members join that organization directly."
            )

        cursor.execute(
            "INSERT INTO org_invitations (id, org_id, email, role, invited_by, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL %s DAY)) "
            "ON DUPLICATE KEY UPDATE role=VALUES(role), invited_by=VALUES(invited_by), "
            "expires_at=VALUES(expires_at), accepted_at=NULL, revoked_at=NULL",
            (invite_id, org_id, email, role, invited_by, int(expires_days)),
        )
        # A re-invite to the same (org_id, email) hits uq_org_email and takes
        # the ON DUPLICATE KEY UPDATE branch, which keeps the EXISTING row's
        # id — the invite_id generated above is never actually written
        # anywhere in that case. Re-reading it here is what makes the
        # returned id trustworthy either way; backlog 51's claim-link token
        # is minted against this value, and a stale, never-persisted id
        # silently produced an unclaimable link on every re-invite.
        cursor.execute("SELECT id FROM org_invitations WHERE org_id=%s AND email=%s", (org_id, email))
        invite_id = cursor.fetchone()[0]
        # Flag invites outside the org's verified domain (contractor case).
        cursor.execute("SELECT domain_to_verify FROM organizations WHERE id=%s AND domain_verified=TRUE", (org_id,))
        row = cursor.fetchone()
        external = bool(row and row[0] and not email.endswith("@" + row[0].lower()))
        log_auth_event("member_invited", invited_by, org_id=org_id,
                       detail={"email": email, "role": role, "external_domain": external},
                       cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return {"id": invite_id, "org_id": org_id, "email": email, "role": role,
            "external_domain": external}


def list_org_invitations(org_id, pending_only=True):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q = "SELECT * FROM org_invitations WHERE org_id=%s"
        if pending_only:
            q += " AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > NOW()"
        q += " ORDER BY created_at DESC"
        cursor.execute(q, (org_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def revoke_org_invitation(org_id, invite_id, actor):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE org_invitations SET revoked_at=NOW() "
            "WHERE id=%s AND org_id=%s AND accepted_at IS NULL AND revoked_at IS NULL",
            (invite_id, org_id),
        )
        ok = cursor.rowcount > 0
        if ok:
            log_auth_event("invite_revoked", actor, org_id=org_id,
                           detail={"invite_id": invite_id}, cursor=cursor)
        conn.commit()
        return ok
    finally:
        cursor.close()
        conn.close()


def match_pending_invitation(email):
    """Most recent live invitation for this (verified) email, if any."""
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM org_invitations WHERE email=%s AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND expires_at > NOW() ORDER BY created_at DESC LIMIT 1",
            (email,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def accept_invitation(invite_id, user_id, actor):
    """Accept: stamp the invite, set the user's org/role, journal — one txn.
    Returns {org_id, role} or None if the invite is no longer live."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM org_invitations WHERE id=%s AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND expires_at > NOW() FOR UPDATE",
            (invite_id,),
        )
        inv = cursor.fetchone()
        if not inv:
            conn.rollback()
            return None
        cursor.execute("UPDATE org_invitations SET accepted_at=NOW() WHERE id=%s", (invite_id,))
        cursor.execute("UPDATE users SET org_id=%s, role=%s WHERE id=%s",
                       (inv["org_id"], inv["role"], user_id))
        log_auth_event("invite_accepted", actor, org_id=inv["org_id"], user_id=user_id,
                       detail={"invite_id": invite_id, "role": inv["role"],
                               "join_method": "invite"}, cursor=cursor)
        conn.commit()
        return {"org_id": inv["org_id"], "role": inv["role"]}
    finally:
        cursor.close()
        conn.close()


def claim_invitation_with_password(invite_id, email, password, name=None):
    """Backlog 51: the user-account half of an SMTP-delivered invite claim.
    Creates a password-login account for the invited email (or adds a
    password to one that already exists, e.g. from a prior Google login),
    without touching org membership — that stays accept_invitation's job,
    called separately right after this by the caller, so both paths through
    an invitation set org/role in exactly one place.

    name is always applied when given, new row or existing. Originally this
    only filled in an EMPTY name, to avoid clobbering a real Google/Microsoft
    display name — but there is no way to tell a real name apart from a
    leftover fallback (this function's own email-local-part default, from
    before this parameter existed), and silently discarding what someone just
    typed is worse than the risk that guard was for: whoever fills in the
    claim form is already trusted enough to set the account's PASSWORD, so
    trusting the same form for the display name is the same trust boundary,
    not a new one. Falls back to the email's local part only when no name is
    given at all.

    Re-checks the invitation is still live by id AND email rather than
    trusting the caller's decoded token: revoking or letting an invite
    expire must kill its claim link immediately, and matching email too is
    a cheap belt-and-suspenders against the two ever disagreeing.

    Returns {"user_id": ...} or None if the invitation is no longer live."""
    from werkzeug.security import generate_password_hash
    email = (email or "").strip().lower()
    name = (name or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id FROM org_invitations WHERE id=%s AND email=%s AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND expires_at > NOW()",
            (invite_id, email),
        )
        if not cursor.fetchone():
            return None

        cursor.execute("SELECT id, name FROM users WHERE email=%s", (email,))
        existing = cursor.fetchone()
        password_hash = generate_password_hash(password)
        if existing:
            user_id = existing["id"]
            if name:
                cursor.execute("UPDATE users SET password_hash=%s, name=%s WHERE id=%s",
                               (password_hash, name, user_id))
            else:
                cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s",
                               (password_hash, user_id))
        else:
            user_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO users (id, email, name, password_hash) VALUES (%s, %s, %s, %s)",
                (user_id, email, name or email.split("@")[0], password_hash),
            )
        conn.commit()
        return {"user_id": user_id}
    finally:
        cursor.close()
        conn.close()


def get_policy_id_by_api_key(raw_key):
    # Never log the key, any prefix of it, or its hash. This used to emit
    # `logging.error("DEBUG_KEY_CHECK: Input: <first 15 chars>, Hash: <10>")` on
    # EVERY call, under a comment calling it temporary — so partial live
    # credentials were being written into the journal at error level, where they
    # are the most likely thing to be shipped to an aggregator or pasted into a
    # bug report. A failed lookup logs that a lookup failed, and nothing else.
    if not raw_key:
        return None
    try:
        h = hashlib.sha256(raw_key.encode()).hexdigest()
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT policy_id FROM api_keys WHERE key_hash=%s", (h,))
            row = cursor.fetchone()
            if row:
                # Update usage stats
                cursor.execute("UPDATE api_keys SET last_used_at=NOW() WHERE key_hash=%s", (h,))
                conn.commit()
                return row[0]
            
            logging.warning(f"API key verification failed (no hash match).")
            return None
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logging.error(f"API key verification error: {e}")
        return None

def delete_policy_keys(pid):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM api_keys WHERE policy_id=%s", (pid,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# OAUTH TOKEN MANAGEMENT
# -------------------------------------------------------------------------
# Token values are Fernet-encrypted here so every caller (auth callbacks,
# MCP connectors) reads and writes plaintext transparently.

def upsert_oauth_token(user_id, provider, access_token, refresh_token=None, expires_at=None, scope=None,
                       org_id=None):
    """Store a member's delegated token for a data source.

    Pass org_id to record the link in org_compliance_log **in the same
    transaction**. Linking a corporate data source to a governed agent is a
    governance act and belongs next to provider-policy and retention changes;
    writing it in the same transaction is what stops a connection existing with
    no evidence that it was made. org_id=None (single-user install with no org)
    simply skips the evidence row — there is no org log to write to."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            INSERT INTO oauth_tokens (user_id, provider, access_token, refresh_token, expires_at, scope)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                access_token = VALUES(access_token),
                refresh_token = VALUES(refresh_token),
                expires_at = VALUES(expires_at),
                scope = VALUES(scope)
        """
        cursor.execute(sql, (user_id, provider, crypto.encrypt_value(access_token),
                             crypto.encrypt_value(refresh_token), expires_at, scope))
        if org_id:
            append_compliance_log(org_id, "connector_connected", f"user:{user_id}",
                                  {"provider": provider, "scope": scope or ""},
                                  cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_oauth_token(user_id, provider):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM oauth_tokens WHERE user_id=%s AND provider=%s", (user_id, provider))
        return crypto.decrypt_fields(cursor.fetchone(), ("access_token", "refresh_token"))
    finally:
        cursor.close()
        conn.close()

def delete_oauth_token(user_id, provider, org_id=None):
    """Remove a member's delegated token. Pass org_id to evidence-log the
    disconnect in the same transaction — see upsert_oauth_token.

    The evidence row is written only when a token actually existed, so a repeat
    disconnect (or a probe for a provider that was never linked) does not
    manufacture history that did not happen."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM oauth_tokens WHERE user_id=%s AND provider=%s", (user_id, provider))
        if org_id and cursor.rowcount:
            append_compliance_log(org_id, "connector_disconnected", f"user:{user_id}",
                                  {"provider": provider}, cursor=cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_connected_providers(user_id):
    """Returns a list of provider names that the user has connected."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT provider FROM oauth_tokens WHERE user_id=%s", (user_id,))
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    finally:
        cursor.close()
        conn.close()

def cleanup_orphaned_public_users():
    """Removes `public_*` user rows that no longer have a conversation.

    The public widget mints one user row per CONVERSATION
    (`conversations.py`: `public_{conversation_id}`), so a page reload creates
    another. Nothing ever removed them: `cleanup_old_demo_users` matches
    `demo_%` only, and the retention purge deletes conversations rather than
    the user rows that pointed at them. The rows therefore accumulated forever
    and counted as registered users in every query anyone would naturally run.

    Deliberately narrow: a row is removed ONLY when it has no conversation
    left. Anything with a conversation, a message or a governance record is
    evidence of a governed turn, and destroying that belongs to the retention
    engine — which respects each org's retention period, checks legal holds and
    writes its own evidence. This function must never become a second, quieter
    destruction path.

    Returns the number of rows removed.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT u.id FROM users u
             WHERE u.id LIKE 'public\\_%'
               AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.user_id = u.id)
               AND NOT EXISTS (SELECT 1 FROM governance_records g WHERE g.user_id = u.id)
            """
        )
        ids = [r[0] for r in cursor.fetchall()]
        if not ids:
            return 0
        marks = ",".join(["%s"] * len(ids))
        cursor.execute(f"DELETE FROM users WHERE id IN ({marks})", tuple(ids))
        conn.commit()
        return len(ids)
    finally:
        cursor.close()
        conn.close()


def cleanup_old_demo_users():
    """
    Deletes demo users AND their private organizations created more than 24 hours ago.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Identify Expired Demo Users and their Orgs
        # We need to explicitly find orgs created by these users (or linked to them)
        # Since we create a unique org per demo user, we can just grab their org_id.
        select_sql = "SELECT id, org_id FROM users WHERE id LIKE 'demo_%' AND created_at < NOW() - INTERVAL 24 HOUR"
        cursor.execute(select_sql)
        expired_users = cursor.fetchall() # List of tuples (user_id, org_id)
        
        if not expired_users:
            return

        expired_user_ids = [u[0] for u in expired_users]
        expired_org_ids = [u[1] for u in expired_users if u[1]] # Filter None
        
        # 2. Delete Users (Cascades to history)
        if expired_user_ids:
            format_strings = ','.join(['%s'] * len(expired_user_ids))
            tuple_ids = tuple(expired_user_ids)
            
            # --- MANUALLY DELETE DEPENDENCIES TO PREVENT FK ERRORS ---
            # Even if CASCADE is set, strict SQL modes or missing permissions can block it.
            
            # A0. Governance records — demo sandboxes are disposable fixtures,
            # so ALL their records go (governance_records has no FK by
            # design, see init_db). Matched by the record's own user
            # attribution, NOT via conversations: records whose conversation
            # the demo user already deleted would escape a join.
            cursor.execute(
                f"DELETE FROM governance_records WHERE user_id IN ({format_strings})",
                tuple_ids)

            # A. Conversations (Cascades to chat_history usually, but good to be sure)
            cursor.execute(f"DELETE FROM conversations WHERE user_id IN ({format_strings})", tuple_ids)
            
            # B. Prompt Usage
            cursor.execute(f"DELETE FROM prompt_usage WHERE user_id IN ({format_strings})", tuple_ids)
            
            # C. OAuth Tokens
            cursor.execute(f"DELETE FROM oauth_tokens WHERE user_id IN ({format_strings})", tuple_ids)

            # D. User Profiles
            cursor.execute(f"DELETE FROM user_profiles WHERE user_id IN ({format_strings})", tuple_ids)
            
            # E. Agents (Created by these users)
            cursor.execute(f"DELETE FROM agents WHERE created_by IN ({format_strings})", tuple_ids)

            # ---------------------------------------------------------

            delete_users_sql = f"DELETE FROM users WHERE id IN ({format_strings})"
            cursor.execute(delete_users_sql, tuple_ids)
            logging.info(f"Cleaned up {cursor.rowcount} expired demo users.")
            
        # 3. Delete their Organizations
        # We only delete orgs that were gathered from these specific expiring users.
        if expired_org_ids:
            format_strings = ','.join(['%s'] * len(expired_org_ids))
            # Any remaining demo-org governance records (e.g. gateway turns
            # attributed to the org but not a demo user id) go with the org.
            cursor.execute(
                f"DELETE FROM governance_records WHERE org_id IN ({format_strings})",
                tuple(expired_org_ids))
            delete_orgs_sql = f"DELETE FROM organizations WHERE id IN ({format_strings})"
            cursor.execute(delete_orgs_sql, tuple(expired_org_ids))
            logging.info(f"Cleaned up {cursor.rowcount} expired demo organizations.")

        conn.commit()
    except Exception as e:
        logging.error(f"Failed to cleanup demo users/orgs: {e}")
    finally:
        cursor.close()
        conn.close()
