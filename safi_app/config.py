import os
import logging
from dotenv import load_dotenv
from typing import List

project_root = os.path.join(os.path.dirname(__file__), '..')
dotenv_path = os.path.join(project_root, '.env')

load_dotenv(dotenv_path=dotenv_path, override=True)

# ── Faculty model auto-detection ──────────────────────────────────────────────
# A fresh install should work with whichever single provider key the operator
# has — not silently require Groq. When a SAFI_*_MODEL env var is unset, the
# faculty default follows the first configured provider key (detection order
# below). Explicit SAFI_*_MODEL values always win — set them to change models
# once you know which ones you want.
# "light" covers the background roles: summarizer, backend, and note-taker.
_FACULTY_DEFAULTS_BY_PROVIDER = {
    "groq":      {"intellect": "openai/gpt-oss-20b",        "conscience": "openai/gpt-oss-120b",       "light": "openai/gpt-oss-20b"},
    "gemini":    {"intellect": "gemini-3.6-flash",          "conscience": "gemini-3.6-flash",          "light": "gemini-3.5-flash-lite"},
    "anthropic": {"intellect": "claude-haiku-4-5-20251001", "conscience": "claude-haiku-4-5-20251001", "light": "claude-haiku-4-5-20251001"},
    "openai":    {"intellect": "gpt-5-mini",                "conscience": "gpt-5-mini",                "light": "gpt-5-nano"},
    "mistral":   {"intellect": "mistral-medium-latest",     "conscience": "mistral-medium-latest",     "light": "mistral-small-latest"},
    # gemma-4-31b is deliberately excluded from Conscience duty: its audits fail closed.
    "cerebras":  {"intellect": "gpt-oss-120b",              "conscience": "gpt-oss-120b",              "light": "gpt-oss-120b"},
    "deepseek":  {"intellect": "deepseek-v4-flash",         "conscience": "deepseek-v4-pro",           "light": "deepseek-v4-flash"},
    "zhipu":     {"intellect": "glm-5.2",                   "conscience": "glm-5.2",                   "light": "glm-5.2"},
}

# Groq first preserves the historical default when several keys are present.
_PROVIDER_KEY_ENV_ORDER = [
    ("groq", "GROQ_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("zhipu", "ZHIPU_API_KEY"),
]


def _detect_faculty_defaults() -> dict:
    for provider, env_var in _PROVIDER_KEY_ENV_ORDER:
        if os.environ.get(env_var):
            return _FACULTY_DEFAULTS_BY_PROVIDER[provider]
    # No key at all: Config.validate() aborts startup with a clear "no LLM API
    # key" error before any of these defaults is used; the shape just has to exist.
    return _FACULTY_DEFAULTS_BY_PROVIDER["groq"]


class Config:
    """
    Central configuration class for SAFi.
    Loads settings from environment variables with sensible defaults.
    Now loads from a .env file first.
    """

    # --- Environment-Aware URL Setup ---
    
    # 1. Determine the environment. 
    # IMPORTANT: Set FLASK_ENV=development on your Dev server.
    # Set FLASK_ENV=production on your Live server.
    APP_ENV = os.environ.get('FLASK_ENV', 'production')

    # 2. Set URLs based on the environment
    # WEB_BASE_URL can be overridden via env for Docker/self-hosted deployments.
    if APP_ENV == 'development':
        _default_base_url = "https://chat.selfalignmentframework.com"
        _default_origins = [
            "https://chat.selfalignmentframework.com",
            "capacitor://localhost",
            "http://localhost",
            "ionic://localhost"
        ]
    else:
        _default_base_url = "https://safi.selfalignmentframework.com"
        _default_origins = [
            "https://safi.selfalignmentframework.com",
            "https://selfalignmentframework.com",
            "capacitor://localhost",
            "http://localhost",
            "ionic://localhost"
        ]

    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", _default_base_url)

    # ALLOWED_ORIGINS can be a comma-separated list in the env variable.
    # e.g. ALLOWED_ORIGINS=http://localhost:5000,https://yourdomain.com
    _origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or _default_origins

    # 3. Derive the callback URL
    WEB_CALLBACK_URL = f"{WEB_BASE_URL}/api/callback"

    # --- Session Security ---
    # FIX: Automatically enforce Secure cookies if the Base URL is HTTPS.
    # Allow override via environment variable for local testing (HTTP)
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "True").lower() == "true" and WEB_BASE_URL.startswith("https")
    
    SESSION_COOKIE_NAME = 'safi_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax' 
    
    # Ensure Flask generates URLs with https if behind a proxy
    PREFERRED_URL_SCHEME = 'https'

    # --- Secrets & Keys ---

    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")

    # Bot API Secret
    # Moved from hardcoded string to environment variable
    BOT_API_SECRET = os.environ.get("SAFI_BOT_API_SECRET", "safi-bot-secret-123")

    # Master key for application-level encryption at rest (Fernet). Accepts a
    # comma-separated list: the FIRST key encrypts, ALL keys decrypt, so keys
    # can be rotated by prepending a new one. Unset = passthrough (plaintext)
    # mode, allowed only outside production.
    ENCRYPTION_KEY = os.environ.get("SAFI_ENCRYPTION_KEY", "")

    # Global retention for the per-profile JSONL orchestrator logs on disk
    # (days; unset/empty = keep forever). Files mix orgs, so this is global
    # rather than per-org; scripts/retention_purge.py enforces it and skips
    # entirely while any org has an active legal hold.
    LOG_RETENTION_DAYS = int(os.environ.get("SAFI_LOG_RETENTION_DAYS") or 0) or None

    # OAuth credentials for Google login
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    # Native-app Google Sign-In uses its own OAuth client id(s) — its ID tokens
    # carry a different audience than the web client above. List them here
    # (comma-separated) so mobile login tokens are accepted as valid audiences.
    GOOGLE_MOBILE_CLIENT_IDS = tuple(
        c.strip() for c in os.environ.get("GOOGLE_MOBILE_CLIENT_IDS", "").split(",") if c.strip()
    )

    # OAuth credentials for Microsoft login
    MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
    MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")

    # OAuth credentials for GitHub login
    GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
    

    # API keys for all providers
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
    ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY")
    CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

    # MySQL connection details
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "safi")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    DB_NAME = os.environ.get("DB_NAME", "safi")
    # Connections per worker process. Total app connections = this × gunicorn
    # workers, which must stay safely under MySQL's max_connections (default 151).
    # Default 10 → 3 workers = 30, leaving comfortable headroom. The old hardcoded
    # 32 (× workers) idled near the cap and exhausted it under any extra load.
    # MySQL connector caps pool_size at 32; values above that are clamped.
    DB_POOL_SIZE = max(1, min(32, int(os.environ.get("SAFI_DB_POOL_SIZE", "10"))))

    # Comma-separated list of emails that have super-admin access to the Audit Hub
    # (can see all orgs' logs). Leave blank to disable super-admin access entirely.
    SUPER_ADMIN_EMAILS = [e.strip() for e in os.environ.get("SAFI_SUPER_ADMINS", "").split(",") if e.strip()]

    # Usage controls
    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "0"))

    # Show or hide the "Try Demo (Admin)" button on the login page.
    # Set to false for private/self-hosted instances that don't need a public demo.
    ENABLE_DEMO_LOGIN = os.environ.get("SAFI_ENABLE_DEMO", "false").lower() == "true"

    # Local admin account for dev/self-hosted instances (no OAuth required).
    # When both vars are set, a persistent admin account is auto-created on startup.
    LOCAL_ADMIN_EMAIL    = os.environ.get("SAFI_LOCAL_ADMIN_EMAIL", "").strip()
    LOCAL_ADMIN_PASSWORD = os.environ.get("SAFI_LOCAL_ADMIN_PASSWORD", "").strip()
    ENABLE_LOCAL_LOGIN   = bool(LOCAL_ADMIN_EMAIL and LOCAL_ADMIN_PASSWORD)

    # Maximum number of sequential tool-call turns the orchestrator will take
    # before forcing a final synthesis response. Raise this if your tools
    # need more hops to complete a task.
    MAX_AGENT_TURNS = int(os.environ.get("SAFI_MAX_AGENT_TURNS", "5"))

    # Logging configuration
    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-%Y-%m-%d.jsonl")

    # Plaintext JSONL governance logs on disk — a DEBUG sink only, default
    # OFF. The system of record is the encrypted governance_records table,
    # written atomically with each turn and served by the native Audit Hub.
    DEBUG_JSONL_LOGS = os.environ.get("SAFI_DEBUG_JSONL_LOGS", "false").strip().lower() in ("1", "true", "yes")

    # Model assignments for each faculty (apply to authenticated users and bots).
    # Explicit SAFI_*_MODEL vars win; otherwise defaults follow the first
    # configured provider key so a fresh install works with any single key
    # (see _detect_faculty_defaults at module level).
    _faculty_defaults = _detect_faculty_defaults()
    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", _faculty_defaults["intellect"])
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", _faculty_defaults["conscience"])

    # Models used exclusively by the public WordPress chatbot endpoint.
    # Falls back to the global defaults above if not set.
    PUBLIC_INTELLECT_MODEL = os.environ.get("SAFI_PUBLIC_INTELLECT_MODEL", INTELLECT_MODEL)
    PUBLIC_CONSCIENCE_MODEL = os.environ.get("SAFI_PUBLIC_CONSCIENCE_MODEL", CONSCIENCE_MODEL)
    SUMMARIZER_MODEL = os.environ.get("SAFI_SUMMARIZER_MODEL", _faculty_defaults["light"])
    # General-purpose background model (suggestions, etc.).
    BACKEND_MODEL = os.environ.get("SAFI_BACKEND_MODEL", _faculty_defaults["light"])
    # Dedicated note-taker (agent work-context) model — separate from BACKEND_MODEL so
    # note-taking can run on a different provider than suggestions/summaries.
    NOTETAKER_MODEL = os.environ.get("SAFI_NOTETAKER_MODEL", _faculty_defaults["light"])

    # --- Agent work-context ("note-taker") memory tuning ---
    # Sampling temperature for the background extraction call (deterministic by default).
    AGENT_MEMORY_TEMPERATURE = float(os.environ.get("SAFI_AGENT_MEMORY_TEMPERATURE", "0.0"))
    # Max entries retained per memory key after the code-side merge (bounds growth).
    AGENT_MEMORY_MAX_ITEMS_PER_KEY = int(os.environ.get("SAFI_AGENT_MEMORY_MAX_ITEMS", "80"))
    # Memory structure: key -> identity field for dict items (None = list of strings).
    # Drives both the empty-context shape and the merge dedupe behavior.
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

    # --- TTS CONFIGURATION ---
    # Provider: "edge-tts" (free), "gpt-4o-mini-tts" (OpenAI), or "gemini-*"
    TTS_MODEL = os.environ.get("SAFI_TTS_MODEL", "edge-tts")
    # edge-tts voices: en-US-AvaMultilingualNeural, en-US-AndrewNeural, en-US-AriaNeural
    TTS_VOICE = os.environ.get("SAFI_TTS_VOICE", "en-US-AvaMultilingualNeural")
    TTS_CACHE_DIR = os.path.join(project_root, "tts_cache")
    # TTS audio is derived from (possibly sensitive) AI responses, so cached
    # MP3s must not persist on disk indefinitely: files older than the TTL
    # are swept opportunistically on cache access. 0 disables caching
    # entirely (synthesize every time, keep nothing on disk).
    TTS_CACHE_TTL_DAYS = int(os.environ.get("SAFI_TTS_CACHE_TTL_DAYS", "7"))

    # Spirit computation parameters
    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # Minimum alignment score Will requires before approving a response.
    # Can be overridden per-agent via will_rules.structural_requirements.alignment_score_threshold.
    SPIRIT_ALIGNMENT_THRESHOLD = float(os.environ.get("SAFI_SPIRIT_THRESHOLD", "0.5"))

    # Default profile to use when none is specified
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "tutor").strip().lower()

       # --- CONFIGURATION: AUTOMATIC PROFILE EXTRACTION ---
    # Set to False to disable the AI from silently adding facts to the user profile.
    ENABLE_PROFILE_EXTRACTION = False 

    # This list is sent to the frontend.
    AVAILABLE_MODELS = [
        # Groq Models
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},

        # Anthropic (Claude) Models
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},

        # Google Models
        {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Lite"},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash"},

        # DeepSeek Models
        {"id": "deepseek-v4-flash", "label": "DeepSeek-v4-flash"},
        {"id": "deepseek-v4-pro", "label": "DeepSeek-v4-pro"},

        # Zhipu (Z.ai) Models
        {"id": "glm-5.2", "label": "GLM-5.2"},

        # Cerebras Models (bare ids, unlike Groq's "openai/"-prefixed ones)
        {"id": "gpt-oss-120b", "label": "GPT-OSS 120B (Cerebras)"},
        {"id": "zai-glm-4.7", "label": "GLM 4.7 (Cerebras)"},
        {"id": "gemma-4-31b", "label": "Gemma 4 31B (Cerebras)"},
    ]

    # --- DOCUMENT UPLOAD CONFIGURATION ---
    MAX_UPLOAD_SIZE_MB = int(os.environ.get("SAFI_MAX_UPLOAD_MB", "10"))
    MAX_DOCUMENT_CHARS = int(os.environ.get("SAFI_MAX_DOC_CHARS", "50000"))
    ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx', '.xlsx', '.csv']

    @classmethod
    def validate(cls) -> None:
        """
        Called once at app startup. Raises ValueError listing all missing required
        variables so operators see every problem in a single deploy, not one at a time.
        """
        _log = logging.getLogger(__name__)
        errors: List[str] = []

        if cls.APP_ENV == 'production':
            if cls.SECRET_KEY == "dev-secret-key-should-be-changed":
                errors.append("FLASK_SECRET_KEY must be set to a strong random value in production")
            if not cls.DB_PASSWORD:
                errors.append("DB_PASSWORD is required")
            if not cls.GOOGLE_CLIENT_ID or not cls.GOOGLE_CLIENT_SECRET:
                errors.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required for user login")
            if not cls.ENCRYPTION_KEY:
                errors.append(
                    "SAFI_ENCRYPTION_KEY is required in production — generate with: "
                    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )

        # At least one LLM provider key must be present in any environment
        llm_keys = [
            cls.GROQ_API_KEY, cls.OPENAI_API_KEY, cls.ANTHROPIC_API_KEY,
            cls.GEMINI_API_KEY, cls.MISTRAL_API_KEY, cls.DEEPSEEK_API_KEY,
            cls.ZHIPU_API_KEY, cls.CEREBRAS_API_KEY,
        ]
        if not any(llm_keys):
            errors.append(
                "No LLM API key is configured — set at least one of: "
                "GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                "GEMINI_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY, "
                "ZHIPU_API_KEY, CEREBRAS_API_KEY"
            )

        if errors:
            msg = "SAFi startup aborted — fix the following configuration errors:\n" + \
                  "".join(f"\n  • {e}" for e in errors)
            raise ValueError(msg)

        # Non-fatal warnings
        if cls.BOT_API_SECRET == "safi-bot-secret-123":
            _log.warning("SAFI_BOT_API_SECRET is using the insecure default value — set it in .env")
        if cls.APP_ENV != 'production' and cls.SECRET_KEY == "dev-secret-key-should-be-changed":
            _log.warning("FLASK_SECRET_KEY is using the insecure default value")
