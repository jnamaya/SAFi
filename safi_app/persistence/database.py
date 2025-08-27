# safi_app/persistence/database.py
import sqlite3
import json
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List


def _add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """
    Add a column to a table if it doesn't already exist.
    """
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        print(f"Adding column '{column_name}' to table '{table_name}'...")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_db(db_name: str):
    """
    Initialize schema. Create tables and ensure columns exist.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _add_column_if_not_exists(cursor, 'conversations', 'memory_summary', 'TEXT')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
        )
    ''')
    _add_column_if_not_exists(cursor, 'chat_history', 'message_id', 'TEXT')
    _add_column_if_not_exists(cursor, 'chat_history', 'conscience_ledger', 'TEXT')
    _add_column_if_not_exists(cursor, 'chat_history', 'audit_status', 'TEXT')
    _add_column_if_not_exists(cursor, 'chat_history', 'spirit_score', 'INTEGER')
    _add_column_if_not_exists(cursor, 'chat_history', 'spirit_note', 'TEXT')
    # --- CHANGE: Added columns to store the profile used for each message ---
    _add_column_if_not_exists(cursor, 'chat_history', 'profile_name', 'TEXT')
    _add_column_if_not_exists(cursor, 'chat_history', 'profile_values', 'TEXT')


    cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_id ON chat_history (message_id)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spirit_memory (
            profile_name TEXT PRIMARY KEY,
            turn INTEGER,
            mu TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            picture TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        )
    ''')
    _add_column_if_not_exists(cursor, 'users', 'active_profile', 'TEXT')


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_snapshots (
            turn INTEGER,
            user_id TEXT,
            hash TEXT PRIMARY KEY,
            snapshot TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()


def upsert_audit_snapshot(db_name: str, turn: int, user_id: str, snap_hash: str, snapshot: Dict[str, Any]):
    """
    Insert or replace an audit snapshot keyed by hash.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    snapshot_json = json.dumps(snapshot)
    cursor.execute(
        "INSERT OR REPLACE INTO audit_snapshots (turn, user_id, hash, snapshot) VALUES (?, ?, ?, ?)",
        (turn, user_id, snap_hash, snapshot_json)
    )
    conn.commit()
    conn.close()


def upsert_user(db_name: str, user_info: Dict[str, Any]):
    """
    Insert or update a user record and last login timestamp.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    user_id = user_info.get('sub') or user_info.get('id')
    last_login_ts = datetime.now(timezone.utc).isoformat()

    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    user_exists = cursor.fetchone()

    if user_exists:
        cursor.execute(
            'UPDATE users SET email = ?, name = ?, picture = ?, last_login = ? WHERE id = ?',
            (user_info.get('email'), user_info.get('name'), user_info.get('picture'), last_login_ts, user_id)
        )
    else:
        cursor.execute(
            'INSERT INTO users (id, email, name, picture, last_login) VALUES (?, ?, ?, ?, ?)',
            (user_id, user_info.get('email'), user_info.get('name'), user_info.get('picture'), last_login_ts)
        )
    
    conn.commit()
    conn.close()

def get_user_details(db_name: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a user's details, including their active_profile.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, picture, active_profile FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "email": row[1], "name": row[2], 
            "picture": row[3], "active_profile": row[4]
        }
    return None

def update_user_profile(db_name: str, user_id: str, profile_name: str):
    """
    Update the active_profile for a given user.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET active_profile = ? WHERE id = ?", (profile_name, user_id))
    conn.commit()
    conn.close()


def delete_user(db_name: str, user_id: str):
    """
    Delete a user and all related records.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM prompt_usage WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def save_spirit_memory(db_name: str, profile_name: str, memory: Dict[str, Any]):
    """
    Save spirit memory for a profile.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    mu_list = memory.get('mu', np.array([])).tolist()
    mu_json = json.dumps(mu_list)
    turn = memory.get('turn', 0)
    cursor.execute(
        "INSERT OR REPLACE INTO spirit_memory (profile_name, turn, mu) VALUES (?, ?, ?)",
        (profile_name, turn, mu_json)
    )
    conn.commit()
    conn.close()


def load_spirit_memory(db_name: str, profile_name: str) -> Optional[Dict[str, Any]]:
    """
    Load spirit memory for a profile, if present.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT turn, mu FROM spirit_memory WHERE profile_name = ?", (profile_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        turn, mu_json = row
        mu_list = json.loads(mu_json)
        return {"turn": turn, "mu": np.array(mu_list)}
    return None


def record_prompt_usage(db_name: str, user_id: str):
    """
    Record one prompt usage event for a user.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO prompt_usage (user_id, timestamp) VALUES (?, ?)",
        (user_id, timestamp)
    )
    conn.commit()
    conn.close()


def get_todays_prompt_count(db_name: str, user_id: str) -> int:
    """
    Count prompts used today (UTC) by a user.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cursor.execute(
        "SELECT COUNT(*) FROM prompt_usage WHERE user_id = ? AND DATE(timestamp) = ?",
        (user_id, today_utc)
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def fetch_user_conversations(db_name: str, user_id: str) -> List[Dict[str, str]]:
    """
    Fetch conversations for a user, newest first.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM conversations WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    conversations = [{"id": row[0], "title": row[1]} for row in cursor.fetchall()]
    conn.close()
    return conversations


def create_conversation(db_name: str, user_id: str) -> Dict[str, str]:
    """
    Create a new conversation and return its id and title.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    new_id = str(uuid.uuid4())
    cursor.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)", (new_id, user_id, "New Conversation"))
    conn.commit()
    conn.close()
    return {"id": new_id, "title": "New Conversation"}


def fetch_chat_history_for_conversation(db_name: str, conversation_id: str) -> List[Dict[str, str]]:
    """
    Return the ordered chat history for a conversation.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    # --- CHANGE: Select the historical profile name and values ---
    cursor.execute(
        "SELECT role, content, timestamp, message_id, conscience_ledger, spirit_score, spirit_note, profile_name, profile_values "
        "FROM chat_history WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,)
    )
    history = []
    for row in cursor.fetchall():
        role, content, timestamp, message_id, ledger_json, spirit_score, spirit_note, profile_name, values_json = row
        ledger = json.loads(ledger_json) if ledger_json else []
        values = json.loads(values_json) if values_json else []
        history.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "message_id": message_id,
            "conscience_ledger": ledger,
            "spirit_score": spirit_score,
            "spirit_note": spirit_note,
            "profile_name": profile_name,
            "profile_values": values
        })
    conn.close()
    return history


def insert_memory_entry(db_name: str, conversation_id: str, role: str, content: str, message_id: Optional[str] = None, audit_status: Optional[str] = None):
    """
    Insert a chat message.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (conversation_id, role, content, message_id, audit_status) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, role, content, message_id, audit_status)
    )
    conn.commit()
    conn.close()


# --- CHANGE: Added profile_name and profile_values to the function signature ---
def update_audit_results(db_name: str, message_id: str, ledger: List[Dict[str, Any]], spirit_score: int, spirit_note: str, profile_name: str, profile_values: List[Dict[str, Any]]):
    """
    Update audit results for a specific message, including the profile snapshot.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    ledger_json = json.dumps(ledger)
    values_json = json.dumps(profile_values)
    # --- CHANGE: Update the new profile columns in the database ---
    cursor.execute(
        "UPDATE chat_history SET conscience_ledger = ?, audit_status = 'complete', spirit_score = ?, spirit_note = ?, profile_name = ?, profile_values = ? WHERE message_id = ?",
        (ledger_json, spirit_score, spirit_note, profile_name, values_json, message_id)
    )
    conn.commit()
    conn.close()


def get_audit_result(db_name: str, message_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch audit status and results for a message.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    # --- CHANGE: Select the historical profile name and values ---
    cursor.execute(
        "SELECT audit_status, conscience_ledger, spirit_score, spirit_note, profile_name, profile_values FROM chat_history WHERE message_id = ?",
        (message_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        status, ledger_json, spirit_score, spirit_note, profile_name, values_json = row
        ledger = json.loads(ledger_json) if ledger_json else []
        values = json.loads(values_json) if values_json else []
        return {
            "status": status, 
            "ledger": ledger, 
            "spirit_score": spirit_score, 
            "spirit_note": spirit_note,
            "profile": profile_name, # Renamed for consistency
            "values": values
        }
    return None


def set_conversation_title_from_first_message(db_name: str, conversation_id: str, message: str) -> str:
    """
    Set conversation title from the first user message.
    """
    new_title = (message[:50] + '...') if len(message) > 50 else message
    rename_conversation(db_name, conversation_id, new_title)
    return new_title


def fetch_recent_user_memory(db_name: str, conversation_id: str, limit: int = 5) -> str:
    """
    Deprecated.
    """
    return ""


def fetch_conversation_summary(db_name: str, conversation_id: str) -> str:
    """
    Return the current memory summary for a conversation.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT memory_summary FROM conversations WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def update_conversation_summary(db_name: str, conversation_id: str, new_summary: str):
    """
    Update the stored memory summary for a conversation.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET memory_summary = ? WHERE id = ?", (new_summary, conversation_id))
    conn.commit()
    conn.close()


def rename_conversation(db_name: str, conversation_id: str, new_title: str):
    """
    Rename a conversation.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conversation_id))
    conn.commit()
    conn.close()


def delete_conversation(db_name: str, conversation_id: str):
    """
    Delete a conversation and its history.
    """
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()