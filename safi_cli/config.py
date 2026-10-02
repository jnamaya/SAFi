"""Configuration resolver and persistence for the SAFi CLI."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".config" / "safi"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"
HISTORY_FILE = CONFIG_DIR / "history"


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    return CONFIG_DIR


def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_config(values: Dict[str, Any]) -> None:
    ensure_config_dir()
    existing = load_config()
    existing.update(values)
    CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def resolve_api_key(explicit_key: Optional[str] = None) -> Optional[str]:
    if explicit_key:
        return explicit_key.strip()
    env_key = os.environ.get("SAFI_API_KEY") or os.environ.get("SAFI_POLICY_API_KEY")
    if env_key:
        return env_key.strip()
    cfg = load_config()
    return cfg.get("api_key")


def resolve_api_url(explicit_url: Optional[str] = None) -> str:
    if explicit_url:
        return explicit_url.rstrip("/")
    env_url = os.environ.get("SAFI_API_URL")
    if env_url:
        return env_url.rstrip("/")
    cfg = load_config()
    return cfg.get("api_url", "http://localhost:5000").rstrip("/")


def resolve_session_id(workspace_root: str, new_session: bool = False) -> str:
    import hashlib
    import uuid

    ensure_config_dir()
    norm = str(Path(workspace_root).resolve())
    h = hashlib.sha256(norm.encode()).hexdigest()[:16]

    sessions: Dict[str, str] = {}
    if SESSIONS_FILE.exists():
        try:
            sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sessions = {}

    if not new_session and h in sessions:
        return sessions[h]

    new_id = str(uuid.uuid4())
    sessions[h] = new_id
    try:
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    except OSError:
        pass
    return new_id
