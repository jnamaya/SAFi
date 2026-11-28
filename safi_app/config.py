import json
import os
import logging
import secrets
from dotenv import load_dotenv
from typing import List

project_root = os.path.join(os.path.dirname(__file__), '..')
dotenv_path = os.path.join(project_root, '.env')

load_dotenv(dotenv_path=dotenv_path, override=False)

_FACULTY_DEFAULTS_BY_PROVIDER = {
    "groq":      {"intellect": "openai/gpt-oss-20b",        "conscience": "openai/gpt-oss-120b",       "light": "openai/gpt-oss-20b"},
    "gemini":    {"intellect": "gemini-3.5-flash-lite",    "conscience": "gemini-3.8-flash",          "light": "gemini-3.5-flash-lite"},
    "anthropic": {"intellect": "claude-haiku-5-5",          "conscience": "claude-haiku-5-5",          "light": "claude-haiku-5-5"},
    "openai":    {"intellect": "gpt-6-luna",                "conscience": "gpt-5-mini",                "light": "gpt-5-nano"},
    "mistral":   {"intellect": "mistral-small-2603",         "conscience": "mistral-medium-latest",     "light": "mistral-small-2603"},
    "cerebras":  {"intellect": "qwen-3.8-27b",               "conscience": "qwen-3.8-27b",              "light": "qwen-3.8-27b"},
    "deepseek":  {"intellect": "deepseek-v4-flash",         "conscience": "deepseek-v4-pro",           "light": "deepseek-v4-flash"},
    "zhipu":     {"intellect": "glm-5.3",                   "conscience": "glm-5.3",                   "light": "glm-5.3"},
}

_PROVIDER_KEY_ENV_ORDER = [
    ("local", "SAFI_LOCAL_MODEL_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("zhipu", "ZHIPU_API_KEY"),
]


LOCAL_MODEL_STATUS_PATH = "/var/lib/safi/model-fetch.json"

LOCAL_MODEL_UNIT_PATH = "/etc/systemd/system/safi-llama-server.service"


def active_local_model() -> str:
    import re as _re

    try:
        with open(LOCAL_MODEL_UNIT_PATH, encoding="utf-8") as handle:
            unit = handle.read()
    except OSError:
        unit = ""
    if unit:
        match = _re.search(r"--alias\s+(\S+)", unit)
        if match:
            return match.group(1).split(",")[0].strip()
    return ""


def _detect_faculty_defaults() -> dict:
    for provider, env_var in _PROVIDER_KEY_ENV_ORDER:
        if not os.environ.get(env_var):
            continue
        if provider == "local":
            alias = active_local_model()
            if alias:
                return {"intellect": alias, "conscience": alias, "light": alias}
            continue
        return dict(_FACULTY_DEFAULTS_BY_PROVIDER[provider])
    return {"intellect": "", "conscience": "", "light": ""}


def _faculty_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


DEPLOYMENT_MODES = ("production", "trial", "showcase")

_INVALID_DEPLOYMENT_MODE: str = ""


def _resolve_deployment_mode(raw: str) -> str:
    global _INVALID_DEPLOYMENT_MODE
    mode = (raw or "").strip().lower()
    if mode in DEPLOYMENT_MODES:
        return mode
    if mode:
        _INVALID_DEPLOYMENT_MODE = mode
    return "production"


TENANCY_MODES = ("single", "multi")

_INVALID_TENANCY_MODE: str = ""


def _resolve_tenancy_mode(raw: str) -> str:
    global _INVALID_TENANCY_MODE
    mode = (raw or "").strip().lower()
    if mode in TENANCY_MODES:
        return mode
    if mode:
        _INVALID_TENANCY_MODE = mode
    return "single"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _load_mcp_servers() -> dict:
    path = os.environ.get("MCP_SERVERS_JSON", "").strip()
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except FileNotFoundError:
        logging.warning("MCP_SERVERS_JSON points at %s, which does not exist.", path)
        return {}
    except OSError as e:
        logging.warning("MCP_SERVERS_JSON at %s could not be read: %s", path, e)
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error("MCP_SERVERS_JSON at %s is not valid JSON: %s", path, e)
        return {}
    if isinstance(parsed, dict) and isinstance(parsed.get("mcp_servers"), dict):
        parsed = parsed["mcp_servers"]
    if not isinstance(parsed, dict):
        logging.error("MCP_SERVERS_JSON at %s must contain an object of servers.", path)
        return {}
    return parsed


class Config:

    APP_ENV = os.environ.get('FLASK_ENV', 'production')

    _default_base_url = "http://localhost:5000"
    _default_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost",
    ]

    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", _default_base_url)

    _origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or _default_origins

    WEB_CALLBACK_URL = f"{WEB_BASE_URL}/api/callback"

    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "True").lower() == "true" and WEB_BASE_URL.startswith("https")

    SESSION_COOKIE_NAME = 'safi_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax' 

    PREFERRED_URL_SCHEME = 'https'

    _env_secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    SECRET_KEY_CONFIGURED = bool(_env_secret_key)
    SECRET_KEY = _env_secret_key or secrets.token_hex(32)

    BOT_API_SECRET = os.environ.get("SAFI_BOT_API_SECRET", "")

    BOT_EMAIL_DOMAIN = os.environ.get("SAFI_BOT_EMAIL_DOMAIN", "bot.safi.local")
    GATEWAY_EMAIL_DOMAIN = os.environ.get("SAFI_GATEWAY_EMAIL_DOMAIN", "gateway.safi.local")

    ENCRYPTION_KEY = os.environ.get("SAFI_ENCRYPTION_KEY", "")

    LOG_RETENTION_DAYS = int(os.environ.get("SAFI_LOG_RETENTION_DAYS") or 0) or None

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    GOOGLE_MOBILE_CLIENT_IDS = tuple(
        c.strip() for c in os.environ.get("GOOGLE_MOBILE_CLIENT_IDS", "").split(",") if c.strip()
    )

    MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
    MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")

    CLOUD_EDITION = _env_bool("SAFI_CLOUD_EDITION", False)
    SSO_LOGIN_ENABLED = CLOUD_EDITION and _env_bool("SAFI_SSO_ENABLED", True)

    GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
    ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY")
    ZHIPU_BASE_URL = os.environ.get("ZHIPU_BASE_URL", "https://api.z.ai/api/coding/paas/v4").strip()
    CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
    LOCAL_MODEL_API_KEY = os.environ.get("SAFI_LOCAL_MODEL_API_KEY", "").strip()
    CONSCIENCE_BASE_URL = os.environ.get("SAFI_CONSCIENCE_BASE_URL", "").strip()
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "safi")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    DB_NAME = os.environ.get("DB_NAME", "safi")
    DB_POOL_SIZE = max(1, min(32, int(os.environ.get("SAFI_DB_POOL_SIZE", "10"))))

    SUPER_ADMIN_EMAILS = [e.strip() for e in os.environ.get("SAFI_SUPER_ADMINS", "").split(",") if e.strip()]

    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "0"))
    CLI_DEMO_TURN_LIMIT = int(os.environ.get("SAFI_CLI_DEMO_TURN_LIMIT", "0"))
    DAILY_TOKEN_LIMIT = int(os.environ.get("SAFI_DAILY_TOKEN_LIMIT", "0"))
    UNLIMITED_ORGS = [o.strip() for o in os.environ.get("SAFI_UNLIMITED_ORGS", "").split(",") if o.strip()]
    UNLIMITED_USERS = [u.strip().lower() for u in os.environ.get("SAFI_UNLIMITED_USERS", "").split(",") if u.strip()]

    SAFI_INTERNAL_KEYS = [k.strip() for k in
                          os.environ.get("SAFI_INTERNAL_KEYS", "").split(",")
                          if k.strip()]
    SAFI_ENFORCE_INTERNAL_KEY = os.environ.get(
        "SAFI_ENFORCE_INTERNAL_KEY", "0").strip() in ("1", "true", "yes")

    TENANCY_MODE = _resolve_tenancy_mode(os.environ.get("SAFI_TENANCY_MODE", "single"))

    SINGLE_TENANT_ORG_ID = os.environ.get("SAFI_SINGLE_TENANT_ORG_ID", "").strip() or None

    DEPLOYMENT_MODE = _resolve_deployment_mode(
        os.environ.get("SAFI_DEPLOYMENT_MODE", "production")
    )

    ENABLE_DEMO_LOGIN = (
        False if TENANCY_MODE == 'single'
        else _env_bool("SAFI_ENABLE_DEMO", DEPLOYMENT_MODE in ("trial", "showcase"))
    )

    PUBLIC_DEMO_UI = _env_bool("SAFI_PUBLIC_DEMO_UI", DEPLOYMENT_MODE == "showcase")

    DEMO_INTELLECT_MODEL = os.environ.get("SAFI_DEMO_INTELLECT_MODEL", "").strip()

    LOCAL_ADMIN_EMAIL    = os.environ.get("SAFI_LOCAL_ADMIN_EMAIL", "").strip()
    LOCAL_ADMIN_PASSWORD = os.environ.get("SAFI_LOCAL_ADMIN_PASSWORD", "").strip()
    LOCAL_ADMIN_USERNAME = os.environ.get("SAFI_LOCAL_ADMIN_USERNAME", "").strip().lower()
    ENABLE_LOCAL_LOGIN   = bool(LOCAL_ADMIN_PASSWORD
                                and (LOCAL_ADMIN_USERNAME or LOCAL_ADMIN_EMAIL))

    MAX_AGENT_TURNS = int(os.environ.get("SAFI_MAX_AGENT_TURNS", "5"))

    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-%Y-%m-%d.jsonl")

    DEBUG_JSONL_LOGS = os.environ.get("SAFI_DEBUG_JSONL_LOGS", "false").strip().lower() in ("1", "true", "yes")

    _faculty_defaults = _detect_faculty_defaults()
    INTELLECT_MODEL = _faculty_env("SAFI_INTELLECT_MODEL", _faculty_defaults["intellect"])
    CONSCIENCE_MODEL = _faculty_env("SAFI_CONSCIENCE_MODEL", _faculty_defaults["conscience"])

    PUBLIC_INTELLECT_MODEL = _faculty_env("SAFI_PUBLIC_INTELLECT_MODEL", INTELLECT_MODEL)
    PUBLIC_CONSCIENCE_MODEL = _faculty_env("SAFI_PUBLIC_CONSCIENCE_MODEL", CONSCIENCE_MODEL)
    _light_default = (
        CONSCIENCE_MODEL
        if CONSCIENCE_BASE_URL and CONSCIENCE_MODEL.lower().startswith("safi-")
        else _faculty_defaults["light"]
    )
    SUMMARIZER_MODEL = _faculty_env("SAFI_SUMMARIZER_MODEL", _light_default)
    BACKEND_MODEL = _faculty_env("SAFI_BACKEND_MODEL", _light_default)
    NOTETAKER_MODEL = _faculty_env("SAFI_NOTETAKER_MODEL", _light_default)

    AGENT_MEMORY_TEMPERATURE = float(os.environ.get("SAFI_AGENT_MEMORY_TEMPERATURE", "0.0"))
    AGENT_MEMORY_MAX_ITEMS_PER_KEY = int(os.environ.get("SAFI_AGENT_MEMORY_MAX_ITEMS", "80"))

    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    LDAP_URL = os.environ.get("SAFI_LDAP_URL", "").strip()
    LDAP_PORT = int(os.environ.get("SAFI_LDAP_PORT", "0") or 0) or None
    LDAP_BASE_DN = os.environ.get("SAFI_LDAP_BASE_DN", "").strip()
    LDAP_BIND_DN = os.environ.get("SAFI_LDAP_BIND_DN", "").strip()
    LDAP_BIND_PASSWORD = os.environ.get("SAFI_LDAP_BIND_PASSWORD", "")
    LDAP_USER_FILTER = os.environ.get("SAFI_LDAP_USER_FILTER",
                                      "(&(objectClass=user)(sAMAccountName={username}))")
    LDAP_EMAIL_ATTR = os.environ.get("SAFI_LDAP_EMAIL_ATTR", "mail")
    LDAP_NAME_ATTR = os.environ.get("SAFI_LDAP_NAME_ATTR", "displayName")
    LDAP_TIMEOUT = int(os.environ.get("SAFI_LDAP_TIMEOUT", "5"))
    LDAP_STARTTLS = os.environ.get("SAFI_LDAP_STARTTLS", "true").strip().lower() in ("1", "true", "yes", "on")
    LDAP_TLS_VERIFY = os.environ.get("SAFI_LDAP_TLS_VERIFY", "true").strip().lower() in ("1", "true", "yes", "on")
    LDAP_TLS_CA_FILE = os.environ.get("SAFI_LDAP_TLS_CA_FILE", "").strip()

    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()

    @classmethod
    def smtp_configured(cls) -> bool:
        return bool(cls.SMTP_HOST and cls.SMTP_FROM)

    @classmethod
    def password_login_available(cls) -> bool:
        return bool(cls.ENABLE_LOCAL_LOGIN or cls.smtp_configured())

    @classmethod
    def ldap_configured(cls) -> bool:
        return bool(cls.LDAP_URL and cls.LDAP_BASE_DN)

    AGENT_MEMORY_MAX_CHARS = int(os.environ.get("SAFI_AGENT_MEMORY_MAX_CHARS", "12000"))
    AGENT_MEMORY_SCHEMA = {
        "ongoing_projects": "name",
        "team_members": "name",
        "pending_decisions": None,
        "open_tasks": None,
        "vendors": "name",
        "key_dates": "event",
        "preferences": None,
        "notes": None,
    }

    TTS_ENABLED_ENV = os.environ.get("SAFI_TTS_ENABLED", "").strip().lower()
    TTS_MODEL = os.environ.get("SAFI_TTS_MODEL", "voxtral-mini-tts-2603")
    TTS_VOICE = os.environ.get("SAFI_TTS_VOICE", "en-US-AvaMultilingualNeural")
    MISTRAL_TTS_VOICE = os.environ.get("SAFI_MISTRAL_TTS_VOICE", "en_paul_neutral")
    MISTRAL_TTS_API_KEY = os.environ.get("SAFI_MISTRAL_TTS_API_KEY") or MISTRAL_API_KEY
    TTS_CACHE_DIR = os.path.join(project_root, "tts_cache")
    TTS_CACHE_TTL_DAYS = int(os.environ.get("SAFI_TTS_CACHE_TTL_DAYS", "7"))

    @classmethod
    def tts_enabled(cls) -> bool:
        if cls.TTS_ENABLED_ENV in ("false", "0", "no", "off", "disabled"):
            return False
        model = (cls.TTS_MODEL or "").strip().lower()
        if not model or model in ("none", "off", "false", "disabled"):
            return False
        if model.startswith(("voxtral-", "mistral-")):
            return bool(cls.MISTRAL_TTS_API_KEY or cls.MISTRAL_API_KEY)
        if model.startswith("gpt-"):
            return bool(cls.OPENAI_API_KEY)
        if model.startswith("gemini"):
            return bool(cls.GEMINI_API_KEY)
        if model == "edge-tts":
            return True
        return False

    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    SPIRIT_ALIGNMENT_THRESHOLD = float(os.environ.get("SAFI_SPIRIT_THRESHOLD", "0.5"))

    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "software_engineer").strip().lower()

    PUBLIC_ORG_ID = (os.environ.get("SAFI_PUBLIC_ORG_ID") or "").strip() or None

    BUILTIN_AGENTS = [
        a.strip().lower()
        for a in os.environ.get(
            "SAFI_BUILTIN_AGENTS", "software_engineer,sysadmin,security_engineer"
        ).split(",")
        if a.strip()
    ] or ["software_engineer", "sysadmin", "security_engineer"]

    @classmethod
    def builtin_agent_enabled(cls, key: str) -> bool:
        return "all" in cls.BUILTIN_AGENTS or key in cls.BUILTIN_AGENTS

    MCP_SERVERS_JSON = os.environ.get("MCP_SERVERS_JSON", "").strip()

    MCP_CONFIG = {"mcp_servers": _load_mcp_servers()}

    MCP_REGISTRY_URL = os.environ.get(
        "SAFI_MCP_REGISTRY_URL", "https://registry.modelcontextprotocol.io"
    ).strip()
    ENABLE_PROFILE_EXTRACTION = False 

    AVAILABLE_MODELS = [

        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},

        {"id": "gpt-6-luna", "label": "GPT Luna"},

        {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},

        {"id": "gemini-3.5-flash-lite", "label": "Gemini Flash Lite"},
        {"id": "gemini-3.8-flash", "label": "Gemini Flash"},
        {"id": "gemma-4-31b-it", "label": "Gemma 31B"},

        {"id": "mistral-small-2603", "label": "Mistral Small"},
        {"id": "mistral-medium-latest", "label": "Mistral Medium"},

        {"id": "deepseek-v4-flash", "label": "DeepSeek Flash"},
        {"id": "deepseek-v4-pro", "label": "DeepSeek Pro"},

        {"id": "glm-5.3", "label": "GLM"},

        {"id": "qwen-3.8-27b", "label": "Qwen"},
    ]

    MAX_UPLOAD_SIZE_MB = int(os.environ.get("SAFI_MAX_UPLOAD_MB", "10"))
    MAX_DOCUMENT_CHARS = int(os.environ.get("SAFI_MAX_DOC_CHARS", "50000"))
    ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx', '.xlsx', '.csv',
                                 '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp', '.bmp']

    VOICE_INPUT_ENABLED = os.environ.get("SAFI_VOICE_INPUT", "false").lower() == "true"
    WHISPER_CLI_PATH = os.environ.get("SAFI_WHISPER_BIN", "/opt/whisper.cpp/build/bin/whisper-cli")
    WHISPER_MODEL_PATH = os.environ.get("SAFI_WHISPER_MODEL", "/opt/whisper.cpp/models/ggml-base.en.bin")
    MAX_AUDIO_SIZE_MB = int(os.environ.get("SAFI_MAX_AUDIO_MB", "10"))
    WHISPER_TIMEOUT_SECONDS = int(os.environ.get("SAFI_WHISPER_TIMEOUT", "120"))

    _raw_history_turns = os.environ.get("SAFI_HISTORY_TURNS", "3").strip().lower()
    HISTORY_TURNS = 0 if _raw_history_turns in ("all", "unlimited", "-1") else int(_raw_history_turns or 3)
    HISTORY_MAX_CHARS = int(os.environ.get("SAFI_HISTORY_MAX_CHARS", "40000"))

    _raw_max_context = os.environ.get("SAFI_MAX_CONTEXT_CHARS", "unlimited").strip().lower()
    MAX_CONTEXT_CHARS = 0 if _raw_max_context in ("", "all", "unlimited", "-1") else int(_raw_max_context)

    @classmethod
    def validate(cls) -> None:
        _log = logging.getLogger(__name__)
        errors: List[str] = []

        if _INVALID_DEPLOYMENT_MODE:
            _log.warning(
                "SAFI_DEPLOYMENT_MODE=%r is not a recognised mode (%s) — falling back to "
                "'production'. Demo login and showcase framing are OFF.",
                _INVALID_DEPLOYMENT_MODE, "|".join(DEPLOYMENT_MODES),
            )

        if _INVALID_TENANCY_MODE:
            _log.warning(
                "SAFI_TENANCY_MODE=%r is not a recognised mode (%s) — falling back to "
                "'single'. Every login will join this deployment's one organization.",
                _INVALID_TENANCY_MODE, "|".join(TENANCY_MODES),
            )

        if cls.APP_ENV == 'production':
            if not cls.SECRET_KEY_CONFIGURED:
                errors.append("FLASK_SECRET_KEY must be set to a strong random value in production")
            if not cls.DB_PASSWORD:
                errors.append("DB_PASSWORD is required")
            _logins = {
                "Google (GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET)":
                    bool(cls.GOOGLE_CLIENT_ID and cls.GOOGLE_CLIENT_SECRET),
                "Microsoft (MICROSOFT_CLIENT_ID + MICROSOFT_CLIENT_SECRET)":
                    bool(cls.MICROSOFT_CLIENT_ID and cls.MICROSOFT_CLIENT_SECRET),
                "Local admin (SAFI_LOCAL_ADMIN_USERNAME or _EMAIL + _PASSWORD)":
                    cls.ENABLE_LOCAL_LOGIN,
            }
            if not any(_logins.values()):
                errors.append(
                    "No login method is configured — production needs at least one of:\n"
                    + "\n".join(f"      • {name}" for name in _logins)
                )
            if not cls.ENCRYPTION_KEY:
                errors.append(
                    "SAFI_ENCRYPTION_KEY is required in production — generate with: "
                    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )

        llm_keys = [
            cls.GROQ_API_KEY, cls.OPENAI_API_KEY, cls.ANTHROPIC_API_KEY,
            cls.GEMINI_API_KEY, cls.MISTRAL_API_KEY, cls.DEEPSEEK_API_KEY,
            cls.ZHIPU_API_KEY, cls.CEREBRAS_API_KEY, cls.LOCAL_MODEL_API_KEY,
        ]
        if not any(llm_keys):
            _log.warning(
                "No LLM API key configured in .env. Configure at least one provider key "
                "in .env or via Settings -> Models & Usage before running prompts."
            )

        if errors:
            msg = "SAFi startup aborted — fix the following configuration errors:\n" + \
                  "".join(f"\n  • {e}" for e in errors)
            raise ValueError(msg)

        if cls.BOT_API_SECRET in ("safi-bot-secret-123", "change-me"):
            _log.warning("SAFI_BOT_API_SECRET is using an insecure placeholder value — set a random secret in .env")
        if cls.APP_ENV != 'production' and not cls.SECRET_KEY_CONFIGURED:
            _log.warning("FLASK_SECRET_KEY is not set; using an ephemeral per-process key")
