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
            db_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="safi_pool",
                pool_size=20,
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
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        logging.info("Initializing database schema...")

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

        # --- Organizations ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id CHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                owner_id VARCHAR(255),
                domain_verified BOOLEAN DEFAULT FALSE,
                domain_to_verify VARCHAR(255),
                verification_token VARCHAR(255),
                global_policy_id CHAR(36),
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

        # --- Policies ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                id CHAR(36) PRIMARY KEY,
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

        # --- Check for AI Model Columns (Missing in initial migration) ---
        cursor.execute("SHOW COLUMNS FROM agents LIKE 'intellect_model'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE agents ADD COLUMN intellect_model VARCHAR(100)")
            cursor.execute("ALTER TABLE agents ADD COLUMN will_model VARCHAR(100)")
            cursor.execute("ALTER TABLE agents ADD COLUMN conscience_model VARCHAR(100)")

        # --- API Keys ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash VARCHAR(64) PRIMARY KEY,
                policy_id CHAR(36) NOT NULL,
                label VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP NULL,
                FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE
            )
        ''')
        
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

        conn.commit()
        logging.info("Database initialized.")
    except Exception as e:
        logging.error(f"DB Init Failed: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

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
            mu_list = json.loads(mu_json) if mu_json else []
            return {"turn": turn, "mu": np.array(mu_list)}
        return None
    finally:
        cursor.close()
        conn.close()

def save_spirit_memory_in_transaction(cursor, profile_name: str, memory: Dict[str, Any]):
    mu_list = memory.get('mu', np.array([])).tolist()
    mu_json = json.dumps(mu_list)
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
        mu_list = json.loads(mu_json) if mu_json else []
        return {"turn": turn, "mu": np.array(mu_list)}
    return None

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
        cursor.execute("SELECT id, title, is_pinned, created_at FROM conversations WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def create_conversation(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cid = str(uuid.uuid4())
        cursor.execute("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'New Conversation')", (cid, user_id))
        conn.commit()
        return {"id": cid, "title": "New Conversation", "is_pinned": False}
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

def get_audit_result(msg_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM chat_history WHERE message_id=%s", (msg_id,))
        row = cursor.fetchone()
        if row:
            return {
                "status": row['audit_status'],
                "ledger": row['conscience_ledger'],
                "spirit_score": row['spirit_score'],
                "spirit_note": row['spirit_note'],
                "profile": row['profile_name'],
                "values": row['profile_values'],
                "suggested_prompts": row['suggested_prompts']
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
                 intellect_model=None, will_model=None, conscience_model=None, rag_knowledge_base=None, rag_format_string=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not policy_id: policy_id = 'standalone'
        sql = """INSERT INTO agents (
            agent_key, name, description, avatar, worldview, style, values_json, will_rules_json, policy_id, created_by, org_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        cursor.execute(sql, (
            key, name, description, avatar, worldview, style, json.dumps(values), json.dumps(rules), policy_id, created_by, org_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_agent(key, name, description, avatar, worldview, style, values, rules, policy_id, visibility='private',
                 intellect_model=None, will_model=None, conscience_model=None, rag_knowledge_base=None, rag_format_string=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not policy_id: policy_id = 'standalone'
        sql = """UPDATE agents SET 
            name=%s, description=%s, avatar=%s, worldview=%s, style=%s, values_json=%s, will_rules_json=%s, policy_id=%s, visibility=%s,
            intellect_model=%s, will_model=%s, conscience_model=%s, rag_knowledge_base=%s, rag_format_string=%s
            WHERE agent_key=%s"""
        cursor.execute(sql, (
            name, description, avatar, worldview, style, json.dumps(values), json.dumps(rules), policy_id, visibility,
            intellect_model, will_model, conscience_model, rag_knowledge_base, rag_format_string,
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
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.start_transaction()
        oid = str(uuid.uuid4())
        
        # FIX: Include owner_id and settings
        cursor.execute("""
            INSERT INTO organizations (id, name, owner_id, settings, created_at) 
            VALUES (%s, %s, %s, %s, NOW())
        """, (oid, org_name, user_id, json.dumps({'allow_auto_join': False})))
        
        pid = str(uuid.uuid4())
        cursor.execute("INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by) VALUES (%s, %s, %s, %s, '[]', '[]', %s)", (pid, oid, "Default Policy", f"AI for {org_name}", user_id))
        
        cursor.execute("UPDATE organizations SET global_policy_id=%s WHERE id=%s", (pid, oid))
        conn.commit()
        return {"org_id": oid, "policy_id": pid}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def create_policy(name, worldview, will_rules, values, org_id=None, created_by=None, policy_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pid = policy_id or str(uuid.uuid4())
        cursor.execute("INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)", (pid, org_id, name, worldview, json.dumps(will_rules), json.dumps(values), created_by))
        conn.commit()
        return pid
    finally:
        cursor.close()
        conn.close()

def update_policy(policy_id, name=None, worldview=None, will_rules=None, values=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        fields, params = [], []
        if name: fields.append("name=%s"); params.append(name)
        if worldview: fields.append("worldview=%s"); params.append(worldview)
        if will_rules: fields.append("will_rules=%s"); params.append(json.dumps(will_rules))
        if values: fields.append("values_weights=%s"); params.append(json.dumps(values))
        params.append(policy_id)
        if fields:
            cursor.execute(f"UPDATE policies SET {', '.join(fields)} WHERE id=%s", tuple(params))
            conn.commit()
    finally:
        cursor.close()
        conn.close()

def get_policy(pid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM policies WHERE id=%s", (pid,))
        row = cursor.fetchone()
        if row:
            # FIX: Ensure list is returned even if NULL or None
            row['will_rules'] = json.loads(row['will_rules']) if isinstance(row['will_rules'], str) else row['will_rules'] or []
            row['values_weights'] = json.loads(row['values_weights']) if isinstance(row['values_weights'], str) else row['values_weights'] or []
        return row
    finally:
        cursor.close()
        conn.close()

def list_policies(user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM policies WHERE is_demo=TRUE OR created_by=%s ORDER BY created_at DESC", (user_id,))
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
        return cursor.fetchone()
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
        return None
    finally:
        cursor.close()
        conn.close()

