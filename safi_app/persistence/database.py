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
    """
    Gets a connection from the pool, creating the pool if it doesn't exist.
    """
    global db_pool
    if db_pool is None:
        try:
            logging.info("Connection pool not found. Attempting to create a new one...")
            logging.info(f"Using DB_HOST={Config.DB_HOST}, DB_USER={Config.DB_USER}, DB_NAME={Config.DB_NAME}")
            db_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="safi_pool",
                pool_size=5,
                host=Config.DB_HOST,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME
            )
            logging.info("MySQL connection pool created successfully.")
        except mysql.connector.Error as err:
            logging.exception("FATAL: A database error occurred while creating the connection pool.")
            raise err
    
    return db_pool.get_connection()


def init_db():
    """
    Initialize the MySQL schema.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        logging.info("Initializing database schema...")
        
        # --- MODEL COLUMNS ---
        cursor.execute("SHOW COLUMNS FROM users LIKE 'intellect_model'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN intellect_model VARCHAR(255) DEFAULT NULL")
            logging.info("Added 'intellect_model' column to 'users' table.")
            
        cursor.execute("SHOW COLUMNS FROM users LIKE 'will_model'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN will_model VARCHAR(255) DEFAULT NULL")
            logging.info("Added 'will_model' column to 'users' table.")

        cursor.execute("SHOW COLUMNS FROM users LIKE 'conscience_model'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN conscience_model VARCHAR(255) DEFAULT NULL")
            logging.info("Added 'conscience_model' column to 'users' table.")
        
        # --- PINNED CONVERSATION COLUMN ---
        cursor.execute("SHOW COLUMNS FROM conversations LIKE 'is_pinned'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE")
            logging.info("Added 'is_pinned' column to 'conversations' table.")

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
                conscience_model VARCHAR(255) DEFAULT NULL
            )
        ''')

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

        # --- GOVERNANCE TABLES ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id CHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE SET NULL
            )
        ''')
        
        # Add column for global policy if not exists (circular dep handled by updating org later)
        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'global_policy_id'")
        if not cursor.fetchone():
             cursor.execute("ALTER TABLE organizations ADD COLUMN global_policy_id CHAR(36) NULL REFERENCES policies(id)")

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
        
        # --- MIGRATIONS ---
        cursor.execute("SHOW COLUMNS FROM policies LIKE 'created_by'")
        if not cursor.fetchone():
             cursor.execute("ALTER TABLE policies ADD COLUMN created_by VARCHAR(255) DEFAULT NULL")
             cursor.execute("ALTER TABLE policies ADD COLUMN is_demo BOOLEAN DEFAULT FALSE")
             logging.info("Added 'created_by' and 'is_demo' columns to 'policies' table.")
             
        # --- SEED DEFAULT CONTOSO POLICY ---
        # --- SEED / UPDATE DEFAULT CONTOSO POLICY ---
        # Look for existing ID to update, or create new if missing
        cursor.execute("SELECT id FROM policies WHERE is_demo = TRUE LIMIT 1")
        row = cursor.fetchone()
        
        logging.info("Syncing Default Contoso Policy from JSON...")
        
        # Path to the JSON file
        json_path = os.path.join(os.path.dirname(__file__), '..', 'core', 'governance', 'custom', 'contoso.json')
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                policy_data = json.load(f)
            
            # Map JSON keys to DB columns
            demo_name = policy_data.get("name", "Contoso Global Standard")
            demo_worldview = policy_data.get("global_worldview", "")
            demo_rules = json.dumps(policy_data.get("global_will_rules", []))
            demo_values = json.dumps(policy_data.get("global_values", []))

            if row:
                # UPDATE existing
                demo_id = row[0]
                cursor.execute("""
                    UPDATE policies 
                    SET name=%s, worldview=%s, will_rules=%s, values_weights=%s
                    WHERE id=%s
                """, (demo_name, demo_worldview, demo_rules, demo_values, demo_id))
                logging.info(f"Updated existing demo policy: {demo_name}")
            else:
                # INSERT new
                demo_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO policies (id, name, worldview, will_rules, values_weights, is_demo)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                """, (demo_id, demo_name, demo_worldview, demo_rules, demo_values))
                logging.info(f"Inserted new demo policy: {demo_name}")
            
        except FileNotFoundError:
            logging.error(f"Could not find seeding file at {json_path}. Skipping default policy sync.")
        except Exception as e:
            logging.error(f"Error syncing default policy: {e}")



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


        # --- suggested_prompts column ---
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'suggested_prompts'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN suggested_prompts JSON DEFAULT NULL")
            logging.info("Added 'suggested_prompts' column to 'chat_history' table.")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prompt_usage (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id VARCHAR(255) NOT NULL,
                timestamp TIMESTAMP NOT NULL
            )
        ''')

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
        
        # --- user_profiles table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id VARCHAR(255) NOT NULL,
                profile_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id)
            )
        ''')
        logging.info("Checked/Created 'user_profiles' table.")
        
        logging.info("MySQL database schema checked/initialized successfully.")
        conn.commit()
    except mysql.connector.Error as err:
        logging.exception("Database initialization failed.")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def upsert_audit_snapshot(snap_hash: str, snapshot: Dict[str, Any], turn: int, user_id: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        snapshot_json = json.dumps(snapshot)
        sql = """
            INSERT INTO audit_snapshots (hash, snapshot, turn, user_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE snapshot = VALUES(snapshot), turn = VALUES(turn), user_id = VALUES(user_id)
        """
        cursor.execute(sql, (snap_hash, snapshot_json, turn, user_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def upsert_user(user_info: Dict[str, Any]):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        user_id = user_info.get('sub') or user_info.get('id')
        last_login_ts = datetime.now(timezone.utc)
        sql = """
            INSERT INTO users (id, email, name, picture, last_login)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                name = VALUES(name),
                picture = VALUES(picture),
                last_login = VALUES(last_login)
        """
        cursor.execute(sql, (user_id, user_info.get('email'), user_info.get('name'), user_info.get('picture'), last_login_ts))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_user_details(user_id: str) -> Optional[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, email, name, picture, active_profile, 
                   intellect_model, will_model, conscience_model 
            FROM users 
            WHERE id = %s
        """, (user_id,))
        return cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        return cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def update_user_profile(user_id: str, profile_name: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET active_profile = %s WHERE id = %s", (profile_name, user_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def update_user_models(user_id: str, intellect_model: str, will_model: str, conscience_model: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET intellect_model = %s, will_model = %s, conscience_model = %s 
            WHERE id = %s
        """, (intellect_model, will_model, conscience_model, user_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def delete_user(user_id: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        cursor.execute("DELETE FROM prompt_usage WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
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

def load_spirit_memory(profile_name: str) -> Optional[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT turn, mu FROM spirit_memory WHERE profile_name = %s", (profile_name,))
        row = cursor.fetchone()
        if row:
            turn, mu_json = row
            mu_list = json.loads(mu_json) if mu_json else []
            return {"turn": turn, "mu": np.array(mu_list)}
        return None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def record_prompt_usage(user_id: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc)
        cursor.execute("INSERT INTO prompt_usage (user_id, timestamp) VALUES (%s, %s)", (user_id, timestamp))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def get_todays_prompt_count(user_id: str) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM prompt_usage WHERE user_id = %s AND DATE(timestamp) = %s", (user_id, today_utc))
        return cursor.fetchone()[0]
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def fetch_user_conversations(user_id: str) -> List[Dict[str, str]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Select the new is_pinned column
        cursor.execute("SELECT id, title, is_pinned, created_at FROM conversations WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        user_convos = cursor.fetchall()
        
        if not user_convos:
            return []

        # Get the latest timestamp for each conversation
        convo_ids = [c['id'] for c in user_convos]
        
        placeholders = ', '.join(['%s'] * len(convo_ids))
        
        timestamp_query = f"""
            SELECT conversation_id, MAX(timestamp) as last_updated
            FROM chat_history
            WHERE conversation_id IN ({placeholders})
            GROUP BY conversation_id
        """
        
        cursor.execute(timestamp_query, tuple(convo_ids))
        timestamps = {row['conversation_id']: row['last_updated'] for row in cursor.fetchall()}
        
        # Combine the data
        for convo in user_convos:
            convo['last_updated'] = timestamps.get(convo['id'], convo['created_at'])
        
        return user_convos
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def create_conversation(user_id: str) -> Dict[str, str]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        new_id = str(uuid.uuid4())
        new_title = "New Conversation"
        # The new is_pinned column defaults to FALSE
        cursor.execute("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)", (new_id, user_id, new_title))
        conn.commit()
        return {"id": new_id, "title": new_title, "is_pinned": False}
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# --- SECURITY FIX: Added user_id parameter to prevent IDOR ---
def fetch_chat_history_for_conversation(conversation_id: str, limit: int = 50, offset: int = 0, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT ch.role, ch.content, ch.timestamp, ch.message_id, ch.conscience_ledger, 
                   ch.spirit_score, ch.spirit_note, ch.profile_name, ch.profile_values,
                   ch.suggested_prompts 
            FROM chat_history ch
        """
        params = []
        
        if user_id:
            query += " JOIN conversations c ON ch.conversation_id = c.id WHERE ch.conversation_id = %s AND c.user_id = %s "
            params = [conversation_id, user_id]
        else:
            # Legacy/Internal call without user verification
            query += " WHERE ch.conversation_id = %s "
            params = [conversation_id]
            
        query += " ORDER BY ch.id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cursor.execute(query, tuple(params))
        results = cursor.fetchall()
        return list(reversed(results))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def insert_memory_entry(conversation_id: str, role: str, content: str, message_id: Optional[str] = None, audit_status: Optional[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) VALUES (%s, %s, %s, %s, %s)",
            (conversation_id, role, content, message_id, audit_status)
        )
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def update_audit_results(message_id: str, ledger: List[Dict[str, Any]], spirit_score: int, spirit_note: str, profile_name: str, profile_values: List[Dict[str, Any]], suggested_prompts: List[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ledger_json = json.dumps(ledger)
        values_json = json.dumps(profile_values)
        prompts_json = json.dumps(suggested_prompts) if suggested_prompts else None
        
        sql = """
            UPDATE chat_history 
            SET conscience_ledger = %s, audit_status = 'complete', spirit_score = %s, 
                spirit_note = %s, profile_name = %s, profile_values = %s,
                suggested_prompts = %s
            WHERE message_id = %s
        """
        cursor.execute(sql, (ledger_json, spirit_score, spirit_note, profile_name, values_json, prompts_json, message_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def get_audit_result(message_id: str) -> Optional[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT audit_status, conscience_ledger, spirit_score, spirit_note, 
                   profile_name, profile_values, suggested_prompts
            FROM chat_history WHERE message_id = %s
            """,
            (message_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "status": row.get('audit_status'),
                "ledger": row.get('conscience_ledger'),
                "spirit_score": row.get('spirit_score'),
                "spirit_note": row.get('spirit_note'),
                "profile": row.get('profile_name'), 
                "values": row.get('profile_values'),
                "suggested_prompts": row.get('suggested_prompts')
            }
        return None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# --- SECURITY FIX: Added user_id check ---
def fetch_conversation_summary(conversation_id: str, user_id: Optional[str] = None) -> str:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("SELECT memory_summary FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
        else:
            cursor.execute("SELECT memory_summary FROM conversations WHERE id = %s", (conversation_id,))
        
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def update_conversation_summary(conversation_id: str, new_summary: str, user_id: Optional[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("UPDATE conversations SET memory_summary = %s WHERE id = %s AND user_id = %s", (new_summary, conversation_id, user_id))
        else:
            cursor.execute("UPDATE conversations SET memory_summary = %s WHERE id = %s", (new_summary, conversation_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def rename_conversation(conversation_id: str, new_title: str, user_id: Optional[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("UPDATE conversations SET title = %s WHERE id = %s AND user_id = %s", (new_title, conversation_id, user_id))
        else:
            cursor.execute("UPDATE conversations SET title = %s WHERE id = %s", (new_title, conversation_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def toggle_conversation_pin(conversation_id: str, is_pinned: bool, user_id: Optional[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        is_pinned_int = 1 if is_pinned else 0
        if user_id:
            cursor.execute("UPDATE conversations SET is_pinned = %s WHERE id = %s AND user_id = %s", (is_pinned_int, conversation_id, user_id))
        else:
            cursor.execute("UPDATE conversations SET is_pinned = %s WHERE id = %s", (is_pinned_int, conversation_id))
        conn.commit()
        return {"id": conversation_id, "is_pinned": is_pinned}
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def delete_conversation(conversation_id: str, user_id: Optional[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
        else:
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def set_conversation_title_from_first_message(conversation_id: str, message: str, user_id: Optional[str] = None) -> str:
    new_title = (message[:50] + '...') if len(message) > 50 else message
    rename_conversation(conversation_id, new_title, user_id)
    return new_title

# --- NEW: Helper to verify ownership BEFORE processing ---
def verify_conversation_ownership(user_id: str, conversation_id: str) -> bool:
    """
    Returns True if the user owns the conversation, False otherwise.
    Used by the backend to guard processing.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
        return cursor.fetchone() is not None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def fetch_user_profile_memory(user_id: str) -> str:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) 
        
        query = "SELECT profile_json FROM user_profiles WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        
        row = cursor.fetchone()
        
        if row and row.get('profile_json'):
            return row['profile_json']
        else:
            return "{}"
            
    except Exception as e:
        print(f"ERROR: Failed to fetch user profile for {user_id}: {e}", flush=True)
        return "{}" 
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def upsert_user_profile_memory(user_id: str, profile_json: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            INSERT INTO user_profiles (user_id, profile_json)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE profile_json = VALUES(profile_json)
        """
        
        cursor.execute(query, (user_id, profile_json))
        conn.commit()
            
    except Exception as e:
        print(f"ERROR: Failed to update user profile for {user_id}: {e}", flush=True)
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def upsert_external_conversation(conversation_id: str, user_id: str, title: str = "External Chat"):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s", (conversation_id,))
        if cursor.fetchone():
            return 

        cursor.execute(
            "INSERT INTO conversations (id, user_id, title, created_at) VALUES (%s, %s, %s, NOW())",
            (conversation_id, user_id, title)
        )
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# -------------------------------------------------------------------------
# GOVERNANCE & POLICY MANAGEMENT
# -------------------------------------------------------------------------

def create_policy(name: str, worldview: str, will_rules: List[str], values: List[Dict], org_id: str = None, created_by: str = None) -> str:
    """
    Creates a new Policy in the database.
    Returns: policy_id (str)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    policy_id = str(uuid.uuid4())
    will_json = json.dumps(will_rules)
    values_json = json.dumps(values)
    
    # Simple default Org if none provided (Single Tenant Mode for now)
    # in multi-tenant, org_id would be mandatory
    
    sql = """
        INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(sql, (policy_id, org_id, name, worldview, will_json, values_json, created_by))
    conn.commit()
    cursor.close()
    conn.close()
    
    return policy_id

def update_policy(policy_id: str, name: str = None, worldview: str = None, will_rules: List[str] = None, values: List[Dict] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    fields = []
    params = []
    
    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if worldview is not None:
        fields.append("worldview = %s")
        params.append(worldview)
    if will_rules is not None:
        fields.append("will_rules = %s")
        params.append(json.dumps(will_rules))
    if values is not None:
        fields.append("values_weights = %s")
        params.append(json.dumps(values))
        
    if not fields:
        return
        
    params.append(policy_id)
    sql = f"UPDATE policies SET {', '.join(fields)} WHERE id = %s"
    
    cursor.execute(sql, tuple(params))
    conn.commit()
    cursor.close()
    conn.close()

def get_policy(policy_id: str) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM policies WHERE id = %s", (policy_id,))
    row = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    if row:
        if isinstance(row['will_rules'], str):
            row['will_rules'] = json.loads(row['will_rules'])
        if isinstance(row['values_weights'], str):
            row['values_weights'] = json.loads(row['values_weights'])
    return row

def list_policies(org_id: str = None, user_id: str = None) -> List[Dict]:
    """
    Lists policies. Filtered by ownership or demo status.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # List:
    # 1. Demo policies (is_demo = TRUE)
    # 2. Policies created by the user (created_by = user_id)
    # 3. (Optional) Policies matching org (if we were strictly enforcing orgs)
    
    sql = """
        SELECT * FROM policies 
        WHERE is_demo = TRUE 
           OR created_by = %s
        ORDER BY is_demo DESC, created_at DESC
    """
    cursor.execute(sql, (user_id,))
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    for row in rows:
        if isinstance(row['will_rules'], str):
            row['will_rules'] = json.loads(row['will_rules'])
        if isinstance(row['values_weights'], str):
            row['values_weights'] = json.loads(row['values_weights'])
            
    return rows

def delete_policy(policy_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Also delete associated API keys due to CASCADE, but policies deletion might need checks
    cursor.execute("DELETE FROM policies WHERE id = %s", (policy_id,))
    conn.commit()
    cursor.close()
    conn.close()

# -------------------------------------------------------------------------
# API KEY MANAGEMENT
# -------------------------------------------------------------------------

def create_api_key(policy_id: str, label: str) -> str:
    """
    Generates a new secure API Key, hashes it, stores the hash, and returns the RAW key.
    The raw key is known ONLY at this moment.
    """
    # 1. Generate Raw Key
    # Prefix 'sk-safi-' for easy identification
    random_part = secrets.token_urlsafe(32)
    raw_key = f"sk-safi-{random_part}"
    
    # 2. Hash it
    key_hash = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
    
    # 3. Store Hash
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sql = "INSERT INTO api_keys (key_hash, policy_id, label) VALUES (%s, %s, %s)"
    cursor.execute(sql, (key_hash, policy_id, label))
    conn.commit()
    cursor.close()
    conn.close()
    
    # 4. Return Raw Key (One-time)
    return raw_key

def verify_api_key(raw_key: str) -> Optional[Dict]:
    """
    Verifies an incoming API Key.
    Returns the associated Policy if valid, else None.
    """
    # 1. Hash the incoming key
    key_hash = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 2. Lookup
    sql = """
        SELECT k.policy_id, p.name as policy_name, p.worldview, p.will_rules, p.values_weights
        FROM api_keys k
        JOIN policies p ON k.policy_id = p.id
        WHERE k.key_hash = %s
    """
    cursor.execute(sql, (key_hash,))
    result = cursor.fetchone()
    
    # 3. Update Usage Stats (Async/Fire-and-forget in production, sync here is fine for prototype)
    if result:
         cursor.execute("UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = %s", (key_hash,))
         conn.commit()
         
    cursor.close()
    conn.close()
    
    if result:
        # Parse JSON fields
        if isinstance(result['will_rules'], str):
            result['will_rules'] = json.loads(result['will_rules'])
        if isinstance(result['values_weights'], str):
            result['values_weights'] = json.loads(result['values_weights'])
            
    return result

def get_policy_keys(policy_id: str) -> List[Dict]:
    """Lists keys for a policy (masked)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    sql = "SELECT label, created_at, last_used_at, key_hash FROM api_keys WHERE policy_id = %s ORDER BY created_at DESC"
    cursor.execute(sql, (policy_id,))
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return rows