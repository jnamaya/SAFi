"""Configuration resolver and persistence for the SAFi CLI."""

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

try:  # Optional: OS keychain storage for API keys, falls back to config.json
    import keyring
    from keyring.errors import KeyringError
except Exception:  # pragma: no cover - keyring simply unavailable
    keyring = None
    KeyringError = Exception

KEYRING_SERVICE = "safi-cli"

CONFIG_DIR = Path.home() / ".config" / "safi"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"
HISTORY_FILE = CONFIG_DIR / "history"
INVENTORY_FILE = CONFIG_DIR / "inventory.json"


def load_inventory() -> Dict[str, Any]:
    """Load managed infrastructure hosts from ~/.config/safi/inventory.json."""
    if not INVENTORY_FILE.exists():
        return {}
    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_inventory_targets() -> list[str]:
    """Return list of host alias names defined in the SAFi inventory."""
    return list(load_inventory().keys())


def get_agent_history_file(agent: Optional[str] = None) -> Path:
    """Return an agent-scoped history file path so prompt histories and suggestions stay isolated."""
    if not agent:
        return HISTORY_FILE
    import re
    safe_agent = re.sub(r"[^A-Za-z0-9_-]", "_", agent.strip())
    return CONFIG_DIR / f"history_{safe_agent}"


def _keyring_get(agent: str) -> Optional[str]:
    if keyring is None:
        return None
    try:
        val = keyring.get_password(KEYRING_SERVICE, agent)
        return val.strip() if isinstance(val, str) and val.strip() else None
    except KeyringError:
        return None


def _keyring_set(agent: str, key: str) -> bool:
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, agent, key)
        return True
    except KeyringError:
        return False


def _keyring_delete(agent: str) -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, agent)
    except KeyringError:
        pass


def keyring_available() -> bool:
    """True when an OS keyring backend is usable for secret storage."""
    return keyring is not None and _keyring_get("__probe__") is None


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
    """Resolve the Policy API key for a specific agent."""
    if explicit_key:
        return explicit_key.strip()

    env_var_name = f"SAFI_API_KEY_{agent.upper()}"
    env_key = os.environ.get(env_var_name)
    if env_key:
        return env_key.strip()

    cfg = load_config()
    agent_keys = cfg.get("agent_keys") or {}
    if isinstance(agent_keys, dict) and agent in agent_keys and agent_keys[agent]:
        stored = _keyring_get(agent) or str(agent_keys[agent]).strip()
        return stored
    stored = _keyring_get(agent)
    if stored:
        return stored

    if agent == "software_engineer":
        gen_env = os.environ.get("SAFI_API_KEY") or os.environ.get("SAFI_POLICY_API_KEY")
        if gen_env:
            return gen_env.strip()
        if cfg.get("api_key"):
            return str(cfg.get("api_key")).strip()

    return None


def save_agent_api_key(agent: str, key: str) -> None:
    """Save a Policy API key specifically for an agent."""
    ensure_config_dir()
    cfg = load_config()
    agent_keys = cfg.get("agent_keys") or {}
    if not isinstance(agent_keys, dict):
        agent_keys = {}
    clean_key = key.strip()
    # Prefer the OS keyring; fall back to config.json when unavailable.
    if _keyring_set(agent, clean_key):
        agent_keys = cfg.get("agent_keys") or {}
        if isinstance(agent_keys, dict):
            agent_keys.pop(agent, None)
            cfg["agent_keys"] = agent_keys
        cfg.pop("api_key", None)
        save_config(cfg)
        return
    agent_keys[agent] = clean_key
    cfg["agent_keys"] = agent_keys
    cfg.pop("api_key", None)
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
    """Resolve the backend URL from the explicit flag or config.json ONLY.

    Environment variables and implicit localhost defaults are deliberately
    ignored so the CLI never silently targets a shadowing local instance.
    """
    if explicit_url:
        return explicit_url.rstrip("/")
    cfg = load_config()
    url = str(cfg.get("api_url") or "").strip().rstrip("/")
    if not url:
        raise SystemExit(
            "No SAFi backend URL configured.\n"
            "Run:  safi --set-url http://<host>:5000\n"
            "(or pass -u/--api-url explicitly for a one-off override)"
        )
    return url


def has_configured_api_url() -> bool:
    """Return True if an API URL has been explicitly configured in config.json."""
    return bool(str(load_config().get("api_url") or "").strip())


def get_default_agent() -> Optional[str]:
    """Return configured default agent if set."""
    cfg = load_config()
    val = cfg.get("default_agent")
    return str(val).strip() if val else None


def set_default_agent(agent: str) -> None:
    """Save default agent to config."""
    save_config({"default_agent": agent.strip()})


def _workspace_key(workspace_root: str) -> str:
    norm = str(Path(workspace_root).resolve())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


SESSIONS_PATH_MAP_KEY = "_paths"
SESSIONS_NAME_MAP_KEY = "_names"
SESSIONS_AGENT_MAP_KEY = "_agents"
SESSIONS_WS_AGENT_MAP_KEY = "_workspace_agents"


def _load_sessions() -> Dict[str, Any]:
    if SESSIONS_FILE.exists():
        try:
            data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def list_sessions() -> Dict[str, str]:
    """Return the workspace-key -> conversation-id session map (metadata keys excluded)."""
    return {k: str(v) for k, v in _load_sessions().items() if not k.startswith("_") and isinstance(v, str)}


def session_paths() -> Dict[str, str]:
    """Return the conversation-id -> workspace-path map for friendly /sessions display."""
    data = _load_sessions()
    paths = data.get(SESSIONS_PATH_MAP_KEY)
    return paths if isinstance(paths, dict) else {}


def session_names() -> Dict[str, str]:
    """Return the conversation-id -> friendly name map."""
    data = _load_sessions()
    names = data.get(SESSIONS_NAME_MAP_KEY)
    return names if isinstance(names, dict) else {}


def session_agents() -> Dict[str, str]:
    """Return the conversation-id -> agent-name map."""
    data = _load_sessions()
    agents = data.get(SESSIONS_AGENT_MAP_KEY)
    return agents if isinstance(agents, dict) else {}


def session_agent(conversation_id: str) -> Optional[str]:
    """Return the agent name associated with a conversation ID, if known."""
    data = _load_sessions()
    agents = data.get(SESSIONS_AGENT_MAP_KEY)
    if isinstance(agents, dict):
        val = agents.get(conversation_id)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def get_workspace_agent(workspace_root: str) -> Optional[str]:
    """Return the last active agent used in this workspace, if any."""
    data = _load_sessions()
    ws_key = _workspace_key(workspace_root)
    ws_agents = data.get(SESSIONS_WS_AGENT_MAP_KEY)
    if isinstance(ws_agents, dict) and ws_key in ws_agents:
        val = ws_agents[ws_key]
        if isinstance(val, str) and val.strip():
            return val.strip()

    active_conv = session_for_workspace(workspace_root)
    if active_conv:
        conv_agents = data.get(SESSIONS_AGENT_MAP_KEY)
        if isinstance(conv_agents, dict) and active_conv in conv_agents:
            val = conv_agents[active_conv]
            if isinstance(val, str) and val.strip():
                return val.strip()

    return None


def set_workspace_agent(workspace_root: str, agent: str, conversation_id: Optional[str] = None) -> None:
    """Record the last active agent for a workspace (and optionally its session ID)."""
    ensure_config_dir()
    sessions = _load_sessions()
    ws_key = _workspace_key(workspace_root)
    clean_agent = agent.strip()

    ws_agents = dict(sessions.get(SESSIONS_WS_AGENT_MAP_KEY) or {})
    ws_agents[ws_key] = clean_agent
    sessions[SESSIONS_WS_AGENT_MAP_KEY] = ws_agents

    conv_id = conversation_id or session_for_workspace(workspace_root)
    if conv_id:
        conv_agents = dict(sessions.get(SESSIONS_AGENT_MAP_KEY) or {})
        conv_agents[conv_id] = clean_agent
        sessions[SESSIONS_AGENT_MAP_KEY] = conv_agents

    try:
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    except OSError:
        pass


def set_session_name(conversation_id: str, name: str) -> None:
    """Assign a human-friendly name/title to a session ID."""
    ensure_config_dir()
    sessions = _load_sessions()
    names = dict(sessions.get(SESSIONS_NAME_MAP_KEY) or {})
    names[conversation_id] = name.strip()
    sessions[SESSIONS_NAME_MAP_KEY] = names
    try:
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    except OSError:
        pass


def session_for_workspace(workspace_root: str) -> Optional[str]:
    """Return the conversation id currently bound to a workspace, if any."""
    val = _load_sessions().get(_workspace_key(workspace_root))
    return str(val) if isinstance(val, str) else None


def set_workspace_session(workspace_root: str, conversation_id: str) -> None:
    """Bind a workspace to an existing conversation id so /sessions can resume it."""
    ensure_config_dir()
    sessions = _load_sessions()
    sessions[_workspace_key(workspace_root)] = conversation_id
    paths = dict(sessions.get(SESSIONS_PATH_MAP_KEY) or {})
    paths[conversation_id] = str(Path(workspace_root).resolve())
    sessions[SESSIONS_PATH_MAP_KEY] = paths
    conv_agents = sessions.get(SESSIONS_AGENT_MAP_KEY)
    if isinstance(conv_agents, dict) and conversation_id in conv_agents:
        ws_agents = dict(sessions.get(SESSIONS_WS_AGENT_MAP_KEY) or {})
        ws_agents[_workspace_key(workspace_root)] = conv_agents[conversation_id]
        sessions[SESSIONS_WS_AGENT_MAP_KEY] = ws_agents
    try:
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    except OSError:
        pass


def resolve_session_id(workspace_root: str, new_session: bool = False, agent: Optional[str] = None) -> str:
    ensure_config_dir()
    sessions = _load_sessions()
    ws_key = _workspace_key(workspace_root)

    if not new_session:
        existing = sessions.get(ws_key)
        if isinstance(existing, str) and existing:
            if agent:
                conv_agents = dict(sessions.get(SESSIONS_AGENT_MAP_KEY) or {})
                conv_agents[existing] = agent.strip()
                sessions[SESSIONS_AGENT_MAP_KEY] = conv_agents
                try:
                    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
                except OSError:
                    pass
            return existing

    new_id = str(uuid.uuid4())
    sessions[ws_key] = new_id
    paths = dict(sessions.get(SESSIONS_PATH_MAP_KEY) or {})
    paths[new_id] = str(Path(workspace_root).resolve())
    sessions[SESSIONS_PATH_MAP_KEY] = paths
    if agent:
        conv_agents = dict(sessions.get(SESSIONS_AGENT_MAP_KEY) or {})
        conv_agents[new_id] = agent.strip()
        sessions[SESSIONS_AGENT_MAP_KEY] = conv_agents
        ws_agents = dict(sessions.get(SESSIONS_WS_AGENT_MAP_KEY) or {})
        ws_agents[ws_key] = agent.strip()
        sessions[SESSIONS_WS_AGENT_MAP_KEY] = ws_agents
    try:
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    except OSError:
        pass
    return new_id


def resolve_user_id() -> str:
    """Safely resolve the CLI user identifier across TTY, container, and headless environments."""
    env_id = os.environ.get("SAFI_USER_ID")
    if env_id and env_id.strip():
        return env_id.strip()
    try:
        login = os.getlogin()
    except Exception:
        login = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return f"cli_{login or 'user'}"


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
        login = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return login.capitalize() if login else "User"


def save_user_name(name: str) -> None:
    """Save default user name to config."""
    save_config({"user_name": name.strip()})


def resolve_intellect_model(agent: Optional[str] = None, explicit_model: Optional[str] = None) -> Optional[str]:
    """Resolve the preferred LLM model powering the agent."""
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()

    if agent:
        env_agent = os.environ.get(f"SAFI_MODEL_{agent.upper()}") or os.environ.get(f"SAFI_INTELLECT_MODEL_{agent.upper()}")
        if env_agent and env_agent.strip():
            return env_agent.strip()
    env_global = os.environ.get("SAFI_MODEL") or os.environ.get("SAFI_INTELLECT_MODEL")
    if env_global and env_global.strip():
        return env_global.strip()

    cfg = load_config()
    if agent:
        agent_models = cfg.get("agent_models") or {}
        if isinstance(agent_models, dict) and agent in agent_models and agent_models[agent]:
            return str(agent_models[agent]).strip()
    if cfg.get("model"):
        return str(cfg.get("model")).strip()
    if cfg.get("intellect_model"):
        return str(cfg.get("intellect_model")).strip()
    return None


REASONING_LEVELS = ("low", "medium", "high")


def resolve_reasoning_effort(explicit: Optional[str] = None) -> str:
    """Resolve the preferred reasoning/thinking level ('' = provider default)."""
    candidate = (explicit or os.environ.get("SAFI_REASONING_EFFORT") or "").strip().lower()
    if candidate in REASONING_LEVELS:
        return candidate
    cfg = load_config()
    saved = str(cfg.get("reasoning_effort") or "").strip().lower()
    return saved if saved in REASONING_LEVELS else ""


def save_reasoning_effort(level: str) -> None:
    """Persist the default reasoning level; '' clears it (provider default)."""
    clean = (level or "").strip().lower()
    if clean and clean not in REASONING_LEVELS:
        raise ValueError(f"Reasoning level must be one of {REASONING_LEVELS}")
    save_config({"reasoning_effort": clean})


def save_intellect_model(model: str, agent: Optional[str] = None) -> None:
    """Save default AI model preference."""
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
        cfg["model"] = clean_model
        cfg["intellect_model"] = clean_model
    save_config(cfg)


# Modern developer aliases
resolve_model = resolve_intellect_model
save_model = save_intellect_model
