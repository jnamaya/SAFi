# safi_app/persistence/database.py
import mysql.connector
from mysql.connector import pooling
import json
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import logging
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
        
        # --- MODEL COLUMNS (from previous work) ---
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
        # --- PINNED CONVERSATION COLUMN (New for this feature) ---
        cursor.execute("SHOW COLUMNS FROM conversations LIKE 'is_pinned'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE")
            logging.info("Added 'is_pinned' column to 'conversations' table.")
        # --- END NEW COLUMN ---

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

        # --- MODIFICATION: Added suggested_prompts column ---
        cursor.execute("SHOW COLUMNS FROM chat_history LIKE 'suggested_prompts'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE chat_history ADD COLUMN suggested_prompts JSON DEFAULT NULL")
            logging.info("Added 'suggested_prompts' column to 'chat_history' table.")
        # --- END MODIFICATION ---

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
        
        # --- ADDED: Create the user_profiles table for long-term memory ---
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
        # --- END ADDITION ---
        
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
        # --- MODIFICATION ---
        # Updated select to include the new per-user model fields.
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

def update_user_profile(user_id: str, profile_name: str):
    """
    Updates the user's ACTIVE PROFILE (e.g., 'fiduciary', 'philosopher').
    This is separate from their profile_memory.
    """
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

# --- MODIFICATION: Updated to support per-user model fields ---
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
# --- END MODIFICATION ---

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
    """
    Loads spirit memory without a database lock. Used for read-only operations.
    """
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


# --- MODIFICATION: Fetch conversation list including 'is_pinned' ---
def fetch_user_conversations(user_id: str) -> List[Dict[str, str]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Select the new is_pinned column
        cursor.execute("SELECT id, title, is_pinned, created_at FROM conversations WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        # Renamed variable to avoid clash with built-in
        user_convos = cursor.fetchall()
        # --- FIX: We must get the last_updated time from chat_history ---
        
        if not user_convos:
            return []

        # Get the latest timestamp for each conversation
        convo_ids = [c['id'] for c in user_convos]
        
        # Use a placeholder string for the IN clause
        placeholders = ', '.join(['%s'] * len(convo_ids))
        
        # This query finds the MAX(id) for each conversation, which is the last message
        # It's much faster than sorting by timestamp on a large table
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
            # Use the latest message timestamp if it exists, otherwise use the convo creation time
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


def fetch_chat_history_for_conversation(conversation_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # --- FIX: Sort by the auto-incrementing `id` column ---
        # Sorting by `id` instead of `timestamp` guarantees correct message order
        # and is immune to clock skew issues between server processes.
        query = """
            SELECT role, content, timestamp, message_id, conscience_ledger, 
                   spirit_score, spirit_note, profile_name, profile_values,
                   suggested_prompts 
            FROM chat_history WHERE conversation_id = %s 
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (conversation_id, limit, offset))
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


# --- MODIFICATION: Added suggested_prompts ---
def update_audit_results(message_id: str, ledger: List[Dict[str, Any]], spirit_score: int, spirit_note: str, profile_name: str, profile_values: List[Dict[str, Any]], suggested_prompts: List[str] = None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ledger_json = json.dumps(ledger)
        values_json = json.dumps(profile_values)
        # Handle null or empty list for suggestions
        prompts_json = json.dumps(suggested_prompts) if suggested_prompts else None
        
        sql = """
            UPDATE chat_history 
            SET conscience_ledger = %s, audit_status = 'complete', spirit_score = %s, 
                spirit_note = %s, profile_name = %s, profile_values = %s,
                suggested_prompts = %s
            WHERE message_id = %s
        """
        cursor.execute(sql, (ledger_json, spirit_score, spirit_note, profile_name, values_json, prompts_json, message_id))
        # --- END MODIFICATION ---
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
                "suggested_prompts": row.get('suggested_prompts') # Add suggestions
            }
        return None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def fetch_conversation_summary(conversation_id: str) -> str:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT memory_summary FROM conversations WHERE id = %s", (conversation_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def update_conversation_summary(conversation_id: str, new_summary: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET memory_summary = %s WHERE id = %s", (new_summary, conversation_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def rename_conversation(conversation_id: str, new_title: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET title = %s WHERE id = %s", (new_title, conversation_id))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# --- NEW FUNCTION: Toggle the is_pinned status ---
def toggle_conversation_pin(conversation_id: str, is_pinned: bool):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # MySQL uses 1 for True, 0 for False
        is_pinned_int = 1 if is_pinned else 0
        cursor.execute("UPDATE conversations SET is_pinned = %s WHERE id = %s", (is_pinned_int, conversation_id))
        conn.commit()
        
        # Optional: return the new state if needed
        return {"id": conversation_id, "is_pinned": is_pinned}
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
# --- END NEW FUNCTION ---


def delete_conversation(conversation_id: str):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def set_conversation_title_from_first_message(conversation_id: str, message: str) -> str:
    new_title = (message[:50] + '...') if len(message) > 50 else message
    rename_conversation(conversation_id, new_title)
    return new_title

# --- ADDED: New functions for persistent User Profile Memory ---

def fetch_user_profile_memory(user_id: str) -> str:
    """
    Fetches the persistent user profile JSON string for a given user_id.
    Returns an empty JSON string ("{}") if not found or on error.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        # Assuming a dictionary cursor to get 'profile_json' by name
        cursor = conn.cursor(dictionary=True) 
        
        query = "SELECT profile_json FROM user_profiles WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        
        row = cursor.fetchone()
        
        if row and row.get('profile_json'):
            return row['profile_json']
        else:
            # No profile found, return empty JSON
            return "{}"
            
    except Exception as e:
        # Log the error if possible, but return safely
        print(f"ERROR: Failed to fetch user profile for {user_id}: {e}", flush=True)
        return "{}" # Always return a valid JSON string
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def upsert_user_profile_memory(user_id: str, profile_json: str):
    """
    Inserts or updates the persistent user profile JSON string for a given user_id.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Use INSERT ... ON DUPLICATE KEY UPDATE to handle both cases
        # This is for MySQL.
        query = """
            INSERT INTO user_profiles (user_id, profile_json)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE profile_json = VALUES(profile_json)
        """
        
        cursor.execute(query, (user_id, profile_json))
        conn.commit()
            
    except Exception as e:
        # Log the error
        print(f"ERROR: Failed to update user profile for {user_id}: {e}", flush=True)
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
# --- END ADDITION ---