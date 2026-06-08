# safi_app/persistence/database.py
import mysql.connector
from mysql.connector import pooling
import json
import os
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import logging
import hashlib
import secrets
from ..config import Config

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

        # --- Conversations ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id CHAR(36) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                title VARCHAR(255),
                memory_summary TEXT,
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
                UNIQUE KEY uniq_policy_version (policy_id, version),
                FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE
            )
        ''')
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
                content TEXT,
                audit_status VARCHAR(20),
                conscience_ledger JSON,
                spirit_score INT,
                spirit_note TEXT,
                profile_name VARCHAR(50),
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
            cursor.execute("ALTER TABLE chat_history ADD COLUMN reasoning_log JSON DEFAULT NULL")

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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id VARCHAR(255) NOT NULL,
                profile_json TEXT,
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
                context_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, agent_id)
            )
        ''')

        # --- OAuth Tokens (NEW) ---
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

        # --- OAuth Tokens (NEW) ---
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

        conn.commit()
        logging.info("Database initialized.")

        # Ensure the SAFi default policy template exists (system-wide seed)
        _ensure_safi_policy_exists()

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

def fetch_chat_history_for_conversation(cid, limit=50, offset=0, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM chat_history WHERE conversation_id = %s ORDER BY id DESC LIMIT %s OFFSET %s"
        params = [cid, limit, offset]
        cursor.execute(sql, tuple(params))
        return list(reversed(cursor.fetchall()))
    finally:
        cursor.close()
        conn.close()

def insert_memory_entry(cid, role, content, message_id=None, audit_status=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) VALUES (%s, %s, %s, %s, %s)", (cid, role, content, message_id, audit_status))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def cancel_message(msg_id):
    """Marks a message as cancelled so the pipeline skips further processing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE chat_history SET audit_status='cancelled' WHERE message_id=%s", (msg_id,))
        conn.commit()
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

def update_audit_results(msg_id, ledger, score, note, pname, pvals, prompts=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """UPDATE chat_history SET conscience_ledger=%s, audit_status='complete', spirit_score=%s, spirit_note=%s, profile_name=%s, profile_values=%s, suggested_prompts=%s WHERE message_id=%s"""
        cursor.execute(sql, (json.dumps(ledger), score, note, pname, json.dumps(pvals), json.dumps(prompts), msg_id))
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
        if audit_status:
            sql = "UPDATE chat_history SET content=%s, audit_status=%s WHERE message_id=%s"
            cursor.execute(sql, (content, audit_status, msg_id))
        else:
            sql = "UPDATE chat_history SET content=%s WHERE message_id=%s"
            cursor.execute(sql, (content, msg_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_message_reasoning(msg_id, step_text):
    """
    Appends a new reasoning step to the message's reasoning_log.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Fetch existing log
        cursor.execute("SELECT reasoning_log FROM chat_history WHERE message_id=%s", (msg_id,))
        row = cursor.fetchone()
        if not row: return
        
        current_log = row['reasoning_log']
        if isinstance(current_log, str): 
            current_log = json.loads(current_log)
        if not isinstance(current_log, list):
            current_log = []
            
        # 2. Append new step with timestamp
        new_step = {
            "step": step_text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        current_log.append(new_step)
        
        # 3. Save back
        cursor.execute("UPDATE chat_history SET reasoning_log=%s WHERE message_id=%s", (json.dumps(current_log), msg_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_audit_result(msg_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Only the columns this endpoint returns — it's polled frequently, so
        # avoid pulling the full row (content + large JSON blobs) every time.
        cursor.execute(
            """SELECT audit_status, conscience_ledger, spirit_score, spirit_note,
                      profile_name, profile_values, suggested_prompts, reasoning_log
               FROM chat_history WHERE message_id=%s""",
            (msg_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "status": row['audit_status'],
                "ledger": row['conscience_ledger'],
                "spirit_score": row['spirit_score'],
                "spirit_note": row['spirit_note'],
                "profile": row['profile_name'],
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
        return row[0] if row else ""
    finally:
        cursor.close()
        conn.close()

def update_conversation_summary(cid, summary, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE conversations SET memory_summary=%s WHERE id=%s", (summary, cid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def rename_conversation(cid, title, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE conversations SET title=%s WHERE id=%s", (title, cid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def toggle_conversation_pin(cid, is_pinned, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE conversations SET is_pinned=%s WHERE id=%s", (1 if is_pinned else 0, cid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def delete_conversation(cid, user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM conversations WHERE id=%s", (cid,))
        conn.commit()
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
        return row['profile_json'] if row else "{}"
    finally:
        cursor.close()
        conn.close()

def upsert_user_profile_memory(uid, data):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO user_profiles (user_id, profile_json) VALUES (%s, %s) ON DUPLICATE KEY UPDATE profile_json=VALUES(profile_json)", (uid, data))
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
        return row['context_json'] if row and row['context_json'] else "{}"
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
            (user_id, agent_id, context_json)
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

def update_member_role(user_id, org_id, new_role):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET role=%s WHERE id=%s AND org_id=%s", (new_role, user_id, org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def remove_member_from_org(user_id, org_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # We simply set org_id to NULL and role to 'member' (resetting them)
        cursor.execute("UPDATE users SET org_id=NULL, role='member' WHERE id=%s AND org_id=%s", (user_id, org_id))
        conn.commit()
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

def update_memory_audit(message_id, audit_status, ledger, spirit_score, spirit_note, profile_name=None, profile_values=None, suggested_prompts=None):
    """
    Updates a chat history record with the results of the Conscience Audit.
    Similar to update_audit_results but kept for compatibility.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            UPDATE chat_history 
            SET audit_status=%s, 
                conscience_ledger=%s, 
                spirit_score=%s, 
                spirit_note=%s,
                profile_name=%s,
                profile_values=%s,
                suggested_prompts=%s
            WHERE message_id=%s
        """
        cursor.execute(sql, (
            audit_status, 
            json.dumps(ledger), 
            spirit_score, 
            spirit_note,
            profile_name,
            json.dumps(profile_values) if profile_values else None,
            json.dumps(suggested_prompts) if suggested_prompts else None,
            message_id
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------------------
# OAUTH TOKEN MANAGEMENT
# -------------------------------------------------------------------------

def upsert_oauth_token(user_id, provider, access_token, refresh_token, expires_at, scope):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            INSERT INTO oauth_tokens (user_id, provider, access_token, refresh_token, expires_at, scope)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                access_token=VALUES(access_token),
                refresh_token=VALUES(refresh_token),
                expires_at=VALUES(expires_at),
                scope=VALUES(scope)
        """
        cursor.execute(sql, (user_id, provider, access_token, refresh_token, expires_at, scope))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_oauth_token(user_id, provider):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM oauth_tokens WHERE user_id=%s AND provider=%s", (user_id, provider))
        return cursor.fetchone()
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
        cursor.execute(sql, (user_id, provider, access_token, refresh_token, expires_at, scope))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_oauth_token(user_id, provider):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM oauth_tokens WHERE user_id=%s AND provider=%s", (user_id, provider))
        return cursor.fetchone()
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
