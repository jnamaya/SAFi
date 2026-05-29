import os
import logging
from dotenv import load_dotenv
from typing import List

project_root = os.path.join(os.path.dirname(__file__), '..')
dotenv_path = os.path.join(project_root, '.env')

load_dotenv(dotenv_path=dotenv_path, override=True)

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

    # 4. External Services URLs
    DASHBOARD_URL = os.environ.get("SAFI_DASHBOARD_URL")

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

    # OAuth credentials for Google login
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

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

    # Model assignments for each faculty (defaults — apply to authenticated users and bots)
    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", "llama-3.1-8b-instant")
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", "gemini-3.1-flash-lite")

    # Models used exclusively by the public WordPress chatbot endpoint.
    # Falls back to the global defaults above if not set.
    PUBLIC_INTELLECT_MODEL = os.environ.get("SAFI_PUBLIC_INTELLECT_MODEL", INTELLECT_MODEL)
    PUBLIC_CONSCIENCE_MODEL = os.environ.get("SAFI_PUBLIC_CONSCIENCE_MODEL", CONSCIENCE_MODEL)
    SUMMARIZER_MODEL = os.environ.get("SAFI_SUMMARIZER_MODEL", "llama-3.1-8b-instant")
    BACKEND_MODEL = os.environ.get("SAFI_BACKEND_MODEL", "llama-3.1-8b-instant")

    # --- TTS CONFIGURATION ---
    # Provider: "edge-tts" (free), "gpt-4o-mini-tts" (OpenAI), or "gemini-*"
    TTS_MODEL = os.environ.get("SAFI_TTS_MODEL", "edge-tts")
    # edge-tts voices: en-US-AriaNeural, en-US-GuyNeural, en-US-JennyNeural
    TTS_VOICE = os.environ.get("SAFI_TTS_VOICE", "en-US-AndrewNeural")
    TTS_CACHE_DIR = os.path.join(project_root, "tts_cache")

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
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B"},
        {"id": "llama-3.1-8b-instant", "label": "llama-3.1-8b"},


        # OpenAI Models
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini"},
        {"id": "gpt-4o", "label": "GPT-4o"},

        # Anthropic (Claude) Models
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
        {"id": "claude-3-7-sonnet-latest", "label": "Claude 3.7 Sonnet"},

        # Google Models
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},

        # Mistral Models
        {"id": "mistral-small-2603", "label": "Mistral Small 4"},
        {"id": "ministral-3b-2512", "label": "Ministral 3 3B"},

        # DeepSeek Models
        {"id": "deepseek-v4-flash", "label": "DeepSeek-v4-flash"},
    ]

    # --- DOCUMENT UPLOAD CONFIGURATION ---
    MAX_UPLOAD_SIZE_MB = int(os.environ.get("SAFI_MAX_UPLOAD_MB", "10"))
    MAX_DOCUMENT_CHARS = int(os.environ.get("SAFI_MAX_DOC_CHARS", "50000"))
    ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx', '.csv']

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

        # At least one LLM provider key must be present in any environment
        llm_keys = [
            cls.GROQ_API_KEY, cls.OPENAI_API_KEY, cls.ANTHROPIC_API_KEY,
            cls.GEMINI_API_KEY, cls.MISTRAL_API_KEY, cls.DEEPSEEK_API_KEY,
        ]
        if not any(llm_keys):
            errors.append(
                "No LLM API key is configured — set at least one of: "
                "GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                "GEMINI_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY"
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
