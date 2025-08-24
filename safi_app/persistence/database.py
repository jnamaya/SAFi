import sqlite3
import uuid
import json
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

def init_db(db_name: str):
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute('''CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT, name TEXT)''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, user_id TEXT, title TEXT, created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, timestamp TEXT,
                type TEXT, content TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, user_id TEXT,
            snapshot_hash TEXT UNIQUE, payload_json TEXT
        )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS spirit_memory (
                profile_name TEXT PRIMARY KEY,
                turn INTEGER,
                mu_vector_json TEXT
            )''')
        con.commit()

def upsert_user(db_name: str, user_info: Dict[str, Any]):
    user_id = user_info.get('sub') or user_info.get('id')
    if not user_id: raise ValueError("User info missing 'sub'/'id'.")
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO users (id, email, name) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET email=excluded.email, name=excluded.name",
            (user_id, user_info.get('email'), user_info.get('name')),
        )
        con.commit()

def delete_user_data(db_name: str, user_id: str):
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        con.commit()

def create_conversation(db_name: str, user_id: str, title: str = "New Chat") -> Dict[str, str]:
    convo_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO conversations (id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
            (convo_id, user_id, title, timestamp)
        )
        con.commit()
    return {"id": convo_id, "title": title}

def rename_conversation(db_name: str, conversation_id: str, new_title: str):
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conversation_id))
        con.commit()

def delete_conversation(db_name: str, conversation_id: str):
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        con.commit()

def set_conversation_title_from_first_message(db_name: str, conversation_id: str, first_message: str) -> str:
    title = (first_message[:40] + '...') if len(first_message) > 40 else first_message
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("UPDATE conversations SET title = ? WHERE id = ? AND title = 'New Chat'", (title, conversation_id))
        con.commit()
    return title

def insert_memory_entry(db_name: str, conversation_id: str, entry_type: str, content: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO memory_entries (conversation_id, timestamp, type, content) VALUES (?, ?, ?, ?)",
            (conversation_id, timestamp, entry_type, content),
        )
        con.commit()

def fetch_recent_user_memory(db_name: str, conversation_id: str, limit: int = 10) -> str:
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT type, content FROM memory_entries WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT ?",
            (conversation_id, limit),
        )
        entries = cur.fetchall()
    return "\n".join([f"• ({etype}) {content}" for etype, content in reversed(entries)])

def fetch_chat_history_for_conversation(db_name: str, conversation_id: str) -> List[Dict[str, str]]:
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT type, content, timestamp FROM memory_entries WHERE conversation_id = ? AND (type = 'prompt' OR type = 'final_output') ORDER BY timestamp ASC", (conversation_id,)
        )
        entries = cur.fetchall()
    history = []
    for entry_type, content, timestamp in entries:
        role = "user" if entry_type == 'prompt' else "ai"
        history.append({"role": role, "content": content, "timestamp": timestamp})
    return history

def fetch_user_conversations(db_name: str, user_id: str) -> List[Dict[str, str]]:
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id, title FROM conversations WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        )
        conversations = [{"id": row[0], "title": row[1]} for row in cur.fetchall()]
    return conversations

def upsert_audit_snapshot(db_name: str, t: int, user_id: str, snapshot_hash: str, payload: Dict[str, Any]):
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO audits (t, user_id, snapshot_hash, payload_json) VALUES (?, ?, ?, ?)",
            (t, user_id, snapshot_hash, json.dumps(payload)),
        )
        con.commit()

def save_spirit_memory(db_name: str, profile_name: str, memory: Dict[str, Any]):
    turn = memory.get('turn', 0)
    mu_vector = memory.get('mu')
    if mu_vector is None:
        return
    mu_vector_json = json.dumps(mu_vector.tolist())
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO spirit_memory (profile_name, turn, mu_vector_json) VALUES (?, ?, ?)",
            (profile_name, turn, mu_vector_json)
        )
        con.commit()

def load_spirit_memory(db_name: str, profile_name: str) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(db_name) as con:
        cur = con.cursor()
        cur.execute("SELECT turn, mu_vector_json FROM spirit_memory WHERE profile_name = ?", (profile_name,))
        row = cur.fetchone()
        if row:
            turn, mu_vector_json = row
            mu_vector = np.array(json.loads(mu_vector_json))
            return {'turn': turn, 'mu': mu_vector}
    return None
