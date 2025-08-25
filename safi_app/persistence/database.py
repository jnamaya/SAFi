# safi_app/persistence/database.py
import sqlite3
import json
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

def init_db(db_name: str):
    """Initializes the database and creates all necessary tables if they don't exist."""
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spirit_memory (
            profile_name TEXT PRIMARY KEY, turn INTEGER, mu TEXT
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

    # --- CHANGE: Added the audit_snapshots table ---
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

# --- CHANGE: Added the missing upsert_audit_snapshot function ---
def upsert_audit_snapshot(db_name: str, turn: int, user_id: str, snap_hash: str, snapshot: Dict[str, Any]):
    """Saves the audit snapshot for a given turn."""
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
    """Inserts a new user or updates their info on login (compatible with older SQLite)."""
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

def delete_user(db_name: str, user_id: str):
    """Deletes a user and all of their associated data."""
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM prompt_usage WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_spirit_memory(db_name: str, profile_name: str, memory: Dict[str, Any]):
    """Saves the Spirit memory state for a given profile."""
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
    """Loads the Spirit memory state for a given profile."""
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
    """Records a new prompt usage for a given user."""
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
    """Counts how many prompts a user has sent today (in UTC)."""
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
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM conversations WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    conversations = [{"id": row[0], "title": row[1]} for row in cursor.fetchall()]
    conn.close()
    return conversations

def create_conversation(db_name: str, user_id: str) -> Dict[str, str]:
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    new_id = str(uuid.uuid4())
    cursor.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)", (new_id, user_id, "New Conversation"))
    conn.commit()
    conn.close()
    return {"id": new_id, "title": "New Conversation"}

def fetch_chat_history_for_conversation(db_name: str, conversation_id: str) -> List[Dict[str, str]]:
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, timestamp FROM chat_history WHERE conversation_id = ? ORDER BY timestamp ASC", (conversation_id,))
    history = [{"role": row[0], "content": row[1], "timestamp": row[2]} for row in cursor.fetchall()]
    conn.close()
    return history

def insert_memory_entry(db_name: str, conversation_id: str, role: str, content: str):
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (conversation_id, role, content) VALUES (?, ?, ?)",
        (conversation_id, role, content)
    )
    conn.commit()
    conn.close()

def set_conversation_title_from_first_message(db_name: str, conversation_id: str, message: str) -> str:
    new_title = (message[:50] + '...') if len(message) > 50 else message
    rename_conversation(db_name, conversation_id, new_title)
    return new_title

def fetch_recent_user_memory(db_name: str, conversation_id: str, limit: int = 5) -> str:
    # Placeholder for more complex memory summarization logic
    return ""

def rename_conversation(db_name: str, conversation_id: str, new_title: str):
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conversation_id))
    conn.commit()
    conn.close()

def delete_conversation(db_name: str, conversation_id: str):
    conn = sqlite3.connect(db_name, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()
