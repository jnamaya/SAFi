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


def resolve_agent_api_key(agent: str, explicit_key: Optional[str] = None) -> Optional[str]:
    """Resolve the Policy API key for a specific agent persona."""
    if explicit_key:
        return explicit_key.strip()

    # 1. Environment variable: SAFI_API_KEY_<AGENT> (e.g. SAFI_API_KEY_FIDUCIARY)
    env_var_name = f"SAFI_API_KEY_{agent.upper()}"
    env_key = os.environ.get(env_var_name)
    if env_key:
        return env_key.strip()

    # 2. Config file under 'agent_keys' dict
    cfg = load_config()
    agent_keys = cfg.get("agent_keys") or {}
    if isinstance(agent_keys, dict) and agent in agent_keys and agent_keys[agent]:
        return str(agent_keys[agent]).strip()

    # 3. For software_engineer, fallback to the general SAFI_API_KEY or cfg["api_key"]
    if agent == "software_engineer":
        gen_env = os.environ.get("SAFI_API_KEY") or os.environ.get("SAFI_POLICY_API_KEY")
        if gen_env:
            return gen_env.strip()
        if cfg.get("api_key"):
            return str(cfg.get("api_key")).strip()

    return None


def save_agent_api_key(agent: str, key: str) -> None:
    """Save a Policy API key specifically for an agent persona."""
    ensure_config_dir()
    cfg = load_config()
    agent_keys = cfg.get("agent_keys") or {}
    if not isinstance(agent_keys, dict):
        agent_keys = {}
    clean_key = key.strip()
    agent_keys[agent] = clean_key
    cfg["agent_keys"] = agent_keys
    # Keep top-level api_key in sync for software_engineer or if unset
    if agent == "software_engineer" or not cfg.get("api_key"):
        cfg["api_key"] = clean_key
    save_config(cfg)


def list_configured_agent_keys() -> Dict[str, str]:
    """Return dictionary of configured agent keys."""
    cfg = load_config()
    agent_keys = dict(cfg.get("agent_keys") or {})
    if cfg.get("api_key") and "software_engineer" not in agent_keys:
        agent_keys["software_engineer"] = str(cfg["api_key"]).strip()
    return agent_keys


def resolve_api_key(explicit_key: Optional[str] = None, agent: str = "software_engineer") -> Optional[str]:
    return resolve_agent_api_key(agent, explicit_key=explicit_key)




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


def resolve_user_name(explicit_name: Optional[str] = None) -> str:
    """Resolve display name for the CLI user."""
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()
    env_name = os.environ.get("SAFI_USER_NAME")
    if env_name and env_name.strip():
        return env_name.strip()
    cfg = load_config()
    if cfg.get("user_name"):
        return str(cfg.get("user_name")).strip()
    try:
        login = os.getlogin()
    except Exception:
        login = os.environ.get("USER", "user")
    return login.capitalize() if login else "User"


def save_user_name(name: str) -> None:
    """Save default user name to config."""
    save_config({"user_name": name.strip()})


def resolve_intellect_model(agent: Optional[str] = None, explicit_model: Optional[str] = None) -> Optional[str]:
    """Resolve the preferred LLM model powering the Intellect faculty."""
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()

    # 1. Environment variable: SAFI_INTELLECT_MODEL_<AGENT> or SAFI_INTELLECT_MODEL
    if agent:
        env_agent = os.environ.get(f"SAFI_INTELLECT_MODEL_{agent.upper()}")
        if env_agent and env_agent.strip():
            return env_agent.strip()
    env_global = os.environ.get("SAFI_INTELLECT_MODEL")
    if env_global and env_global.strip():
        return env_global.strip()

    # 2. Config file under 'agent_models' or top-level 'intellect_model'
    cfg = load_config()
    if agent:
        agent_models = cfg.get("agent_models") or {}
        if isinstance(agent_models, dict) and agent in agent_models and agent_models[agent]:
            return str(agent_models[agent]).strip()
    if cfg.get("intellect_model"):
        return str(cfg.get("intellect_model")).strip()
    return None


def save_intellect_model(model: str, agent: Optional[str] = None) -> None:
    """Save default Intellect AI model preference."""
    ensure_config_dir()
    cfg = load_config()
    clean_model = model.strip()
    if agent:
        agent_models = cfg.get("agent_models") or {}
        if not isinstance(agent_models, dict):
            agent_models = {}
        agent_models[agent] = clean_model
        cfg["agent_models"] = agent_models
    else:
        cfg["intellect_model"] = clean_model
    save_config(cfg)
