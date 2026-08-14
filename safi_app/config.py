import json
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
    # Conscience defaults to gpt-oss-120b rather than gemma-4-31b. The old note
    # here claimed gemma "must not audit" — that dated from the free Cerebras
    # tier, whose context limits made long audit prompts fail; it is not a
    # property of the model, and operators run gemma as Conscience today.
    # 120b stays the default simply as the stronger auditor of the two.
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


DEPLOYMENT_MODES = ("production", "trial", "showcase")

# Set when SAFI_DEPLOYMENT_MODE is present but not a recognised mode, so
# Config.validate() can surface it at startup instead of leaving the operator
# to wonder why the mode they set had no effect.
_INVALID_DEPLOYMENT_MODE: str = ""


def _resolve_deployment_mode(raw: str) -> str:
    """Normalise SAFI_DEPLOYMENT_MODE, falling back to the safe mode.

    Fails toward 'production' rather than raising: an unparseable mode should
    cost an operator their demo login button, never quietly hand a customer
    deployment the promotional UI.
    """
    global _INVALID_DEPLOYMENT_MODE
    mode = (raw or "").strip().lower()
    if mode in DEPLOYMENT_MODES:
        return mode
    if mode:
        _INVALID_DEPLOYMENT_MODE = mode
    return "production"


def _env_bool(name: str, default: bool) -> bool:
    """Explicit env var wins over a mode-derived default, so pre-existing .env
    files keep behaving exactly as they did before deployment modes existed."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _load_mcp_servers() -> dict:
    """Read the operator's MCP server definitions. Never raises.

    Every failure here returns an empty mapping, which means "no MCP tools this
    boot". That is the only safe direction: a half-parsed server file must not
    leave a deployment believing it has a governed tool it does not have. The
    Will then blocks anything the model names, because nothing was expanded into
    any profile's allowed_tools.
    """
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
        # The shipped file is empty on purpose, and an install with no MCP
        # servers is the normal case. Not worth a warning.
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
    """
    Central configuration class for SAFi.
    Loads settings from environment variables with sensible defaults.
    Now loads from a .env file first.
    """

    # --- Environment-Aware URL Setup ---
    
    # 1. Determine the environment.
    #
    # NOTE — there are TWO independent switches and both use the word
    # "production". They are orthogonal and every combination is valid:
    #
    #   FLASK_ENV            controls STRICTNESS. 'production' makes validate()
    #                        refuse to start without FLASK_SECRET_KEY,
    #                        DB_PASSWORD, Google OAuth credentials and
    #                        SAFI_ENCRYPTION_KEY. Anything else skips those
    #                        checks — which also means encryption at rest can
    #                        be silently absent. Read by APP_ENV below.
    #
    #   SAFI_DEPLOYMENT_MODE controls AUDIENCE. production | trial | showcase:
    #                        whether demo login and the showcase UI framing are
    #                        on. See DEPLOYMENT_MODE further down.
    #
    # The public demo runs FLASK_ENV=production with
    # SAFI_DEPLOYMENT_MODE=showcase — strict validation, promotional UI. A
    # customer runs production/production. A laptop runs development/trial.
    APP_ENV = os.environ.get('FLASK_ENV', 'production')

    # 2. Base URL and allowed origins.
    #
    # Defaults to localhost, NOT to any particular deployment's hostname. These
    # previously defaulted to the selfalignmentframework.com hosts, which meant
    # every self-hoster who did not set WEB_BASE_URL silently inherited someone
    # else's domain as their CORS origin and OAuth callback base — a
    # configuration that cannot work for them and fails in ways (blocked
    # cross-origin calls, callbacks redirecting off-site) that give no clue as
    # to the cause. Any real deployment, including the public demo, sets
    # WEB_BASE_URL explicitly in its own .env.
    #
    # The capacitor:// and ionic:// origins stay in the default list because the
    # mobile shell serves bundled assets from a spoofed local origin and cannot
    # set them per-deployment.
    _default_base_url = "http://localhost:5000"
    _default_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "capacitor://localhost",
        "http://localhost",
        "ionic://localhost",
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

    # --- Deployment mode ----------------------------------------------------
    #
    # One declaration of what this instance IS, so an operator states intent
    # once instead of reasoning about several independent demo switches and
    # their interactions:
    #
    #   production (default) — demo login off, showcase framing off.
    #   trial                — demo login on, showcase framing off. The Quick
    #                          Start experience: evaluate locally without
    #                          configuring OAuth, but nothing promotional in
    #                          the UI, because a trial can become a deployment
    #                          without anyone revisiting the config.
    #   showcase             — demo login on, showcase framing on. Only the
    #                          public demo instance should ever be this.
    #
    # Note these are two concepts, not one: demo LOGIN is an auth convenience
    # that is legitimate locally and publicly, while the showcase FRAMING is
    # promotional and belongs only on the public instance. 'trial' exists
    # precisely so the useful half is available without the promotional half.
    #
    # Unrecognised values fall back to production and are reported by validate().
    # A typo must never be the reason someone's deployment starts advertising.
    DEPLOYMENT_MODE = _resolve_deployment_mode(
        os.environ.get("SAFI_DEPLOYMENT_MODE", "production")
    )

    # Show or hide the "Try Demo (Admin)" button on the login page.
    # Derived from the mode; SAFI_ENABLE_DEMO still wins if set explicitly, so
    # existing .env files keep working unchanged.
    ENABLE_DEMO_LOGIN = _env_bool(
        "SAFI_ENABLE_DEMO", DEPLOYMENT_MODE in ("trial", "showcase")
    )

    # Showcase framing in the chat UI — naming the running model and explaining
    # that SAFi is the governance layer, not the intelligence. That argument is
    # aimed at someone evaluating SAFi; inside a customer's deployment the staff
    # using the agent are not the audience, the model choice is an internal
    # detail, and telling them "the intelligence isn't ours" only erodes trust
    # in the tool.
    #
    # Derived ONLY from mode == showcase, never from ENABLE_DEMO_LOGIN: the
    # shipped .env.example enables demo login and the Quick Start tells every
    # new user to copy that file, so keying off it would switch promotional copy
    # on for exactly the self-hosted deployments that must never show it.
    PUBLIC_DEMO_UI = _env_bool("SAFI_PUBLIC_DEMO_UI", DEPLOYMENT_MODE == "showcase")

    # Default Intellect model for fresh demo sandbox accounts. Stored as the
    # user-level selection, so demo guests can still switch models in Settings.
    # Empty = inherit the global INTELLECT_MODEL default. Only the Intellect is
    # demo-overridable; the Conscience stays on the instance's global default.
    #
    # Not folded into DEPLOYMENT_MODE: this is a value, not a switch, and it is
    # simply unused when demo login is off. Nothing to derive.
    #
    # The default is empty on purpose. It used to be "gemma-4-31b", which
    # routes to Cerebras, so every install configured with a different
    # provider gave guests a model it could not serve. A model name set here
    # is also ignored at guest creation unless its provider has a key (see
    # auth.py). Showcase hosts that want a specific demo model set it in .env.
    DEMO_INTELLECT_MODEL = os.environ.get("SAFI_DEMO_INTELLECT_MODEL", "").strip()

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
    # Provider: "edge-tts" (free), "voxtral-*" (Mistral), "gpt-4o-mini-tts"
    # (OpenAI), or "gemini-*"
    TTS_MODEL = os.environ.get("SAFI_TTS_MODEL", "voxtral-mini-tts-2603")
    # edge-tts voices: en-US-AvaMultilingualNeural, en-US-AndrewNeural, en-US-AriaNeural
    TTS_VOICE = os.environ.get("SAFI_TTS_VOICE", "en-US-AvaMultilingualNeural")
    # Mistral preset voice slug — GET https://api.mistral.ai/v1/audio/voices
    # lists them (en_paul_*, gb_jane_*, gb_oliver_*, fr_marie_*).
    MISTRAL_TTS_VOICE = os.environ.get("SAFI_MISTRAL_TTS_VOICE", "en_paul_neutral")
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

    # Default profile to use when none is specified.
    #
    # The Fiduciary leads because it demonstrates what SAFi is for in a single
    # interaction: a regulated-domain agent declining to give personalised
    # financial advice. It is also the agent the published domain-compliance
    # benchmark measures, and it needs no knowledge base — no index, no
    # embedding model, nothing to download on first boot.
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "fiduciary").strip().lower()

    # Org that turns from /api/public/process_prompt are attributed to. Anonymous
    # public users carry no org of their own, so without this their governance
    # records land with org_id = NULL — and `org_id = NULL` matches nothing in
    # SQL, which makes them invisible to every Audit Hub read and both exports.
    # Unset is allowed (the endpoint warns rather than refusing: breaking the
    # embedded widget would be worse than an unauditable turn), but any operator
    # who wants the public bot auditable must set it.
    PUBLIC_ORG_ID = (os.environ.get("SAFI_PUBLIC_ORG_ID") or "").strip() or None

    # Which built-in demo agents to register and seed. Comma-separated agent
    # keys (see core/faculties/synderesis.py AGENTS), or "all" for the full
    # demo suite.
    #
    # The default three all run with zero extra setup. Fiduciary and Tutor
    # carry no rag_knowledge_base at all; the Steward has a small one that
    # auto-builds in Docker. The Bible Scholar is excluded from the default
    # precisely because it DOES require an index to be built first.
    BUILTIN_AGENTS = [
        a.strip().lower()
        for a in os.environ.get("SAFI_BUILTIN_AGENTS", "fiduciary,tutor,safi").split(",")
        if a.strip()
    ] or ["fiduciary", "tutor", "safi"]

    @classmethod
    def builtin_agent_enabled(cls, key: str) -> bool:
        return "all" in cls.BUILTIN_AGENTS or key in cls.BUILTIN_AGENTS

    # --- MCP SERVERS ---
    # Operator-installed tool servers, read from the JSON file MCP_SERVERS_JSON
    # names. The variable and the file have shipped since v1.0 and nothing read
    # either of them until now (GOVERNANCE_BACKLOG 47b); MCP_CONFIG is what
    # orchestrator.py has always passed to MCPManager via getattr.
    #
    # The file is the ONLY way to install a server, deliberately. A stdio server
    # is an arbitrary command this process executes, so defining one is
    # deployment-level trust, the same as SAFI_EXTENSIONS_DIR. No API route, no
    # admin screen and no organization setting can reach it. What an org admin
    # controls is the connector allow-list, one rung up.
    #
    # Accepts either the bare mapping of servers or a {"mcp_servers": {...}}
    # wrapper, because both shapes appear in MCP documentation elsewhere and
    # guessing wrong should not cost anyone an afternoon.
    MCP_SERVERS_JSON = os.environ.get("MCP_SERVERS_JSON", "").strip()

    # MCPManager reads config["mcp_servers"], and orchestrator.py has always
    # passed getattr(config, "MCP_CONFIG", {}) into it, so this is the shape.
    MCP_CONFIG = {"mcp_servers": _load_mcp_servers()}

    # What an admin may install from the browser (backlog 48):
    #   off     nothing; the file above is the only way in
    #   remote  hosted endpoints only (DEFAULT). Installing one runs no
    #           third-party code on this host, so a button press cannot become
    #           shell access on a machine other organizations share.
    #   all     also package/stdio servers, i.e. `npx -y ...` at boot. Correct
    #           ONLY where the admins and the operator are the same people (a
    #           single-tenant self-hosted install). Not implemented yet; treated
    #           as `remote` until stage 2 ships.
    MCP_INSTALL_MODE = (os.environ.get("SAFI_MCP_INSTALL_MODE", "remote") or "remote").strip().lower()

    # Point at a private mirror if you run one. The default is the official
    # registry, which verifies namespace ownership and reviews no code.
    MCP_REGISTRY_URL = os.environ.get(
        "SAFI_MCP_REGISTRY_URL", "https://registry.modelcontextprotocol.io"
    ).strip()

       # --- CONFIGURATION: AUTOMATIC PROFILE EXTRACTION ---
    # Set to False to disable the AI from silently adding facts to the user profile.
    ENABLE_PROFILE_EXTRACTION = False 

    # This list is sent to the frontend.
    AVAILABLE_MODELS = [
        # Groq Models
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},

        # OpenAI Models. Ids must keep the "gpt-5" prefix exactly as OpenAI
        # writes them: llm_provider.py switches on it to send
        # max_completion_tokens and drop temperature/top_p, which the whole
        # gpt-5.x family requires. Siblings gpt-5.6-sol and gpt-5.6-terra also
        # exist and are deliberately not listed.
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna"},

        # Anthropic (Claude) Models
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},

        # Google Models
        {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Lite"},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash"},

        # Mistral Models
        {"id": "mistral-medium-latest", "label": "Mistral-Medium-3.5"},

        # DeepSeek Models
        {"id": "deepseek-v4-flash", "label": "DeepSeek-v4-flash"},
        {"id": "deepseek-v4-pro", "label": "DeepSeek-v4-pro"},

        # Zhipu (Z.ai) Models
        {"id": "glm-5.2", "label": "GLM-5.2"},

        # Cerebras Models (bare ids, unlike Groq's "openai/"-prefixed ones)
        {"id": "zai-glm-4.7", "label": "GLM 4.7"},
        {"id": "gemma-4-31b", "label": "Gemma 4 31B"},
    ]

    # --- DOCUMENT UPLOAD CONFIGURATION ---
    MAX_UPLOAD_SIZE_MB = int(os.environ.get("SAFI_MAX_UPLOAD_MB", "10"))
    MAX_DOCUMENT_CHARS = int(os.environ.get("SAFI_MAX_DOC_CHARS", "50000"))
    ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx', '.xlsx', '.csv',
                                 '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp', '.bmp']

    # --- CONVERSATION MEMORY ---
    # How much of the conversation is replayed verbatim to the faculties each
    # turn, in USER/ASSISTANT PAIRS. 3 was hardcoded in the orchestrator; some
    # agents need the whole thread, so 0 (or "all") means unlimited turns.
    #
    # Unlimited is bounded by characters, not left unbounded, because the window
    # is sent to the Intellect AND fenced into the Conscience's audit material,
    # and the Conscience has no context budget of its own. Uncapped, a long
    # thread carrying one 50k-char attachment re-sends it on every subsequent
    # turn, twice — cost and context grow with the square of the conversation.
    #
    # A per-agent override may be set on the agent as `history_turns` /
    # `history_max_chars`; both survive the governance compile untouched because
    # synderesis deep-copies the agent.
    _raw_history_turns = os.environ.get("SAFI_HISTORY_TURNS", "3").strip().lower()
    HISTORY_TURNS = 0 if _raw_history_turns in ("all", "unlimited", "-1") else int(_raw_history_turns or 3)
    HISTORY_MAX_CHARS = int(os.environ.get("SAFI_HISTORY_MAX_CHARS", "40000"))

    @classmethod
    def validate(cls) -> None:
        """
        Called once at app startup. Raises ValueError listing all missing required
        variables so operators see every problem in a single deploy, not one at a time.
        """
        _log = logging.getLogger(__name__)
        errors: List[str] = []

        if _INVALID_DEPLOYMENT_MODE:
            _log.warning(
                "SAFI_DEPLOYMENT_MODE=%r is not a recognised mode (%s) — falling back to "
                "'production'. Demo login and showcase framing are OFF.",
                _INVALID_DEPLOYMENT_MODE, "|".join(DEPLOYMENT_MODES),
            )

        if cls.APP_ENV == 'production':
            if cls.SECRET_KEY == "dev-secret-key-should-be-changed":
                errors.append("FLASK_SECRET_KEY must be set to a strong random value in production")
            if not cls.DB_PASSWORD:
                errors.append("DB_PASSWORD is required")
            # At least one WAY IN must be configured — not Google specifically.
            # Requiring Google forced anyone standardised on Microsoft Entra
            # (a first-class option, see /api/login/microsoft) or running purely
            # on the local admin account to register a Google OAuth app they
            # would never use, just to boot.
            _logins = {
                "Google (GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET)":
                    bool(cls.GOOGLE_CLIENT_ID and cls.GOOGLE_CLIENT_SECRET),
                "Microsoft (MICROSOFT_CLIENT_ID + MICROSOFT_CLIENT_SECRET)":
                    bool(cls.MICROSOFT_CLIENT_ID and cls.MICROSOFT_CLIENT_SECRET),
                "Local admin (SAFI_LOCAL_ADMIN_EMAIL + SAFI_LOCAL_ADMIN_PASSWORD)":
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
