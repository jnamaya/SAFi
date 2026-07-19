# safi_app/persistence/database.py
import mysql.connector
from mysql.connector import pooling
import json
import os
import re
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import logging
import hashlib
import secrets
from ..config import Config
from . import crypto

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_incident_org (org_id)
            )
        ''')

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
        # agents exist (one per persona)
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
    from ..core.governance.safi.policy import SAFI_DEFAULT_POLICY

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
    (one per persona; see core/governance/demo/policies.py). Idempotent: any
    policy id already present is left untouched, so operator edits made through
    the Governance tab survive restarts. Uses create_policy() so each seed also
    gets its version-1 history row, then flips is_demo so the policies are
    visible to every user.
    """
    from ..core.governance.demo.policies import DEMO_AGENT_POLICIES

    for pid, pol in DEMO_AGENT_POLICIES.items():
        try:
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
            # Create a dedicated persistent org for the local admin
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


def reset_spirit_memory(agent_id: str) -> bool:
    """
    Resets the Spirit memory for a specific agent.
    
    Use this when:
    - An agent's value structure has changed (added/removed values)
    - Spirit memory is corrupted (dimension mismatch)
    - You want to start fresh with a clean ethical baseline
    
    Args:
        agent_id: The profile_name/agent_key to reset (e.g., 'contoso_admin')
        
    Returns:
        True if a row was deleted, False if the agent had no Spirit memory.
        
    Example usage:
        python -c "from safi_app.persistence.database import reset_spirit_memory; print(reset_spirit_memory('contoso_admin'))"
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM spirit_memory WHERE profile_name = %s", (agent_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        if deleted:
            logging.info(f"Spirit memory reset for agent: {agent_id}")
        else:
            logging.info(f"No Spirit memory found for agent: {agent_id}")
        return deleted
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
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        cursor.execute("DELETE FROM prompt_usage WHERE user_id=%s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def fetch_user_conversations(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, title, is_pinned, project_id, created_at FROM conversations WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        return cursor.fetchall()
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
    payload = json.dumps(
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
        entries = cursor.fetchall()
        prev_hash = None
        for e in entries:
            payload = json.dumps(
                {
                    "message_pk": e["message_pk"],
                    "message_id": e["message_id"],
                    "conversation_id": e["conversation_id"],
                    "action": e["action"],
                    "actor": e["actor"],
                    "state": e["state"],
                    "event_at": e["event_at"],
                    "prev_hash": prev_hash,
                },
                sort_keys=True,
            )
            expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if e["prev_hash"] != prev_hash or e["entry_hash"] != expected:
                return {"entries": len(entries), "valid": False, "first_bad_id": e["id"]}
            prev_hash = e["entry_hash"]
        return {"entries": len(entries), "valid": True, "first_bad_id": None}
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
                         will_decision=None, will_stage=None):
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
                             json.dumps(pvals), json.dumps(prompts), msg_id))
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
            (json.dumps(prompts), msg_id),
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

def update_message_reasoning(msg_id, step_text, phase=None):
    """
    Appends a new reasoning step to the message's reasoning_log.
    phase: optional tag ("gather" for agentic tool-call steps) so the
    frontend loader can map the step to a pipeline stage without
    string-matching every tool label.
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
                """SELECT ch.audit_status, ch.conscience_ledger, ch.spirit_score, ch.drift, ch.spirit_note,
                          ch.profile_name, ch.policy_id, ch.policy_version,
                          ch.profile_values, ch.suggested_prompts, ch.reasoning_log
                   FROM chat_history ch
                   JOIN conversations c ON ch.conversation_id = c.id
                   WHERE ch.message_id=%s AND c.user_id=%s""",
                (msg_id, user_id),
            )
        else:
            cursor.execute(
                """SELECT audit_status, conscience_ledger, spirit_score, drift, spirit_note,
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
                "suggested_prompts": row['suggested_prompts'],
                "reasoning_log": row['reasoning_log']
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

def rename_conversation(cid, title, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # SECURITY: scope the write to the owning user when a user_id is supplied
        # (request paths) so one user cannot rename another user's conversation.
        if user_id is not None:
            cursor.execute("UPDATE conversations SET title=%s WHERE id=%s AND user_id=%s", (title, cid, user_id))
        else:
            cursor.execute("UPDATE conversations SET title=%s WHERE id=%s", (title, cid))
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
            cursor.execute("DELETE FROM conversations WHERE id=%s AND user_id=%s", (cid, user_id))
        else:
            _chat_trail_snapshot_delete(
                cursor, "WHERE ch.conversation_id=%s", (cid,), "system",
            )
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
        
        logging.info(f"Listing agents for user={user_id}, org={org_id}, role={user_role}")
        cursor.execute(sql, (user_id, org_id, user_role, user_role, user_role))
        rows = cursor.fetchall()
        logging.info(f"Found {len(rows)} agents")
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
# NEW: ORG & POLICY MANAGEMENT
# -------------------------------------------------------------------------

def create_organization_atomic(org_name, user_id):
    from ..core.governance.safi.policy import SAFI_DEFAULT_POLICY

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
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Filter by Demo, Creator, OR Organization
        cursor.execute("""
            SELECT * FROM policies 
            WHERE is_demo=TRUE 
            OR created_by=%s 
            OR (org_id IS NOT NULL AND org_id=%s)
            ORDER BY created_at DESC
        """, (user_id, org_id))
        
        rows = cursor.fetchall()
        for row in rows:
            row['will_rules'] = json.loads(row['will_rules']) if isinstance(row['will_rules'], str) else row['will_rules']
            row['values_weights'] = json.loads(row['values_weights']) if isinstance(row['values_weights'], str) else row['values_weights']
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
        # Check for EXACT match on domain_to_verify AND domain_verified=TRUE
        cursor.execute("SELECT * FROM organizations WHERE domain_verified=TRUE AND domain_to_verify=%s", (domain,))
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
]
_INCIDENT_JSON_COLS = ("data_types", "affected_user_ids")
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

def append_incident_event(org_id, incident_id, event_type, detail, actor_id, actor_email):
    """Manual event log entry. 'notification_sent' also stamps
    customers_notified_at (first notice stops the 30-day clock)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT customers_notified_at FROM security_incidents "
                       "WHERE id=%s AND org_id=%s FOR UPDATE", (incident_id, org_id))
        row = cursor.fetchone()
        if not row:
            return False
        if event_type == "notification_sent" and row[0] is None:
            cursor.execute("UPDATE security_incidents SET customers_notified_at=UTC_TIMESTAMP() "
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
    for key in ("hard_gate_block", "gateway_violation", "low_alignment", "drift_spike"):
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
    persona redirects, so the trigger keys on will_stage alone (it also
    catches gateway hard-gate violations)."""
    trig_cfg = cfg.get("triggers", {})
    triggers, detail = [], {}
    if trig_cfg.get("hard_gate_block") and will_stage == "hard_gate":
        triggers.append("hard_gate_block")
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

    Returns the updated queue row, or None when the row doesn't exist in this
    org. Raises ValueError on invalid action, missing override reason, or a
    row that is no longer pending."""
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

def update_member_role(user_id, org_id, new_role, actor="system"):
    """Role change revokes the target's live sessions in the SAME transaction
    and journals the change — a demoted admin must not keep an admin session
    (fresh role is re-read per request, but revocation forces a clean re-auth
    and provides the examiner-facing event)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role FROM users WHERE id=%s AND org_id=%s", (user_id, org_id))
        row = cursor.fetchone()
        prior_role = row[0] if row else None
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
    and journals member_removed — off-boarding evidence (design §3.4)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
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
        cursor.execute(
            "INSERT INTO org_invitations (id, org_id, email, role, invited_by, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL %s DAY)) "
            "ON DUPLICATE KEY UPDATE role=VALUES(role), invited_by=VALUES(invited_by), "
            "expires_at=VALUES(expires_at), accepted_at=NULL, revoked_at=NULL",
            (invite_id, org_id, email, role, invited_by, int(expires_days)),
        )
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

def get_policy_id_by_api_key(raw_key):
    # DEBUG LOGGING (Temporary)
    try:
        masked_input = raw_key[:15] + "..." if raw_key else "None"
        h = hashlib.sha256(raw_key.encode()).hexdigest()
        logging.error(f"DEBUG_KEY_CHECK: Input: {masked_input}, Hash: {h[:10]}...")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT policy_id FROM api_keys WHERE key_hash=%s", (h,))
            row = cursor.fetchone()
            if row:
                logging.error(f"DEBUG_KEY_CHECK: Match Found! Policy ID: {row[0]}")
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

def upsert_oauth_token(user_id, provider, access_token, refresh_token=None, expires_at=None, scope=None):
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

def delete_oauth_token(user_id, provider):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM oauth_tokens WHERE user_id=%s AND provider=%s", (user_id, provider))
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
            delete_orgs_sql = f"DELETE FROM organizations WHERE id IN ({format_strings})"
            cursor.execute(delete_orgs_sql, tuple(expired_org_ids))
            logging.info(f"Cleaned up {cursor.rowcount} expired demo organizations.")

        conn.commit()
    except Exception as e:
        logging.error(f"Failed to cleanup demo users/orgs: {e}")
    finally:
        cursor.close()
        conn.close()
