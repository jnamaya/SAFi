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
    # No "local" entry on purpose. The appliance's local alias is whatever the
    # operator downloaded (safi-qwen3-8b, safi-qwen3-32b, ...), so it cannot be
    # a constant here. A hardcoded one shipped "safi-demo", a name the model
    # server never served -- every faculty defaulted to a model that 404s. It is
    # resolved from the live model at startup instead; see active_local_model.
    "groq":      {"intellect": "openai/gpt-oss-20b",        "conscience": "openai/gpt-oss-120b",       "light": "openai/gpt-oss-20b"},
    "gemini":    {"intellect": "gemini-3.5-flash-lite",    "conscience": "gemini-3.8-flash",          "light": "gemini-3.5-flash-lite"},
    "anthropic": {"intellect": "claude-haiku-4-5-20251001", "conscience": "claude-haiku-4-5-20251001", "light": "claude-haiku-4-5-20251001"},
    "openai":    {"intellect": "gpt-6-luna",                "conscience": "gpt-5-mini",                "light": "gpt-5-nano"},
    # Conscience keeps Medium while Intellect and the background tier drop to
    # Small: auditing is the one role where a weaker model changes what the
    # framework can block, so it does not get cut alongside the answering path.
    # This also pins the former floating "mistral-small-latest" alias to a
    # concrete release, and puts it in AVAILABLE_MODELS so light no longer
    # names a model the picker never offers.
    "mistral":   {"intellect": "mistral-small-2603",         "conscience": "mistral-medium-latest",     "light": "mistral-small-2603"},
    # Keep faculties on distinct available models while retaining the stronger
    # GPT-OSS 120B model for Conscience.
    # Cerebras is inference-only and carries no chat vendor of its own: what it
    # serves is other people's models. All three faculties land on the same one
    # because it is the only Cerebras model in the catalogue — unlike Cerebras
    # before it, Conscience gives up its stronger auditing tier here.
    "cerebras":  {"intellect": "qwen-3.8-27b",               "conscience": "qwen-3.8-27b",              "light": "qwen-3.8-27b"},
    "deepseek":  {"intellect": "deepseek-v4-flash",         "conscience": "deepseek-v4-pro",           "light": "deepseek-v4-flash"},
    "zhipu":     {"intellect": "glm-5.2",                   "conscience": "glm-5.2",                   "light": "glm-5.2"},
}

# Groq first preserves the historical default when several keys are present.
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


# Written by safi-model-fetch (STATUS_PATH) once a download is verified and the
# server unit points at the model. Keep in step with that script.
LOCAL_MODEL_STATUS_PATH = "/var/lib/safi/model-fetch.json"

# The unit safi-model-fetch writes at activation. Its --alias is the ONLY
# truthful answer to "what is the server actually serving": the status file
# records a completed download even when that download was deliberately not
# activated (fetching a second model must not disturb the first), so trusting
# it made the catalog advertise "Serving" for a model no server was running.
LOCAL_MODEL_UNIT_PATH = "/etc/systemd/system/safi-llama-server.service"


def active_local_model() -> str:
    """Alias of the local model the appliance is actually serving, or "".

    Read from the model server unit's --alias, because that is what the running
    server answers to. The fetch status file is deliberately NOT trusted for
    this: a download that was verified but not activated still writes
    state="done" with its own alias, and reading that reported a freshly
    downloaded model as serving while the server was still on the old one (or
    absent entirely). Falls back to the status file only for the first-boot
    case, where the unit is written in the same run and is normally present.

    Deliberately stdlib-only and dependency-free. It is called during Config
    class construction, long before the app's service layer is importable.
    """
    import re as _re

    try:
        with open(LOCAL_MODEL_UNIT_PATH, encoding="utf-8") as handle:
            unit = handle.read()
    except OSError:
        unit = ""
    if unit:
        match = _re.search(r"--alias\s+(\S+)", unit)
        if match:
            return match.group(1).strip()
    return ""


def _detect_faculty_defaults() -> dict:
    for provider, env_var in _PROVIDER_KEY_ENV_ORDER:
        if not os.environ.get(env_var):
            continue
        if provider == "local":
            # "local" is first in the detection order and the appliance sets the
            # local key as soon as setup is deferred, so it must be skipped
            # until a model is genuinely live. Otherwise a deferred install
            # defaults every faculty to a model nothing is serving.
            alias = active_local_model()
            if alias:
                defaults = {"intellect": alias, "conscience": alias, "light": alias}
                if os.environ.get("TYPESAFE_API_KEY", "").strip():
                    defaults["conscience"] = "jev-1.13.0"
                return defaults
            continue
        defaults = dict(_FACULTY_DEFAULTS_BY_PROVIDER[provider])
        if os.environ.get("TYPESAFE_API_KEY", "").strip():
            defaults["conscience"] = "jev-1.13.0"
        return defaults
    # No provider we can name a real model for. SAFI_*_MODEL may still be set
    # explicitly, and Config.validate() refuses to start when no provider key
    # exists at all, so this shape only has to exist.
    return {"intellect": "", "conscience": "", "light": ""}


def _faculty_env(name: str, default: str) -> str:
    """Read a SAFI_*_MODEL var, treating a blank assignment as unset.

    .env.example ships every faculty line present-but-empty so operators can see
    the knob without setting it, and the appliance wizard leaves Conscience
    empty on purpose so a TypeSafe key added later is auto-promoted to Jev.
    load_dotenv() turns that blank line into an empty string, and
    os.environ.get(name, default) would hand the empty string straight back,
    shadowing the detected default with no model at all.
    """
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


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


TENANCY_MODES = ("single", "multi")

# Set when SAFI_TENANCY_MODE is present but not "single" or "multi", so
# Config.validate() can surface it the same way as an invalid deployment mode.
_INVALID_TENANCY_MODE: str = ""


def _resolve_tenancy_mode(raw: str) -> str:
    """Normalise SAFI_TENANCY_MODE, falling back to 'single'.

    Fails toward 'single' rather than raising, and for the same reason
    _resolve_deployment_mode fails toward 'production': a typo must never be
    the reason a deployment meant to serve one organization starts minting a
    fresh org for every unrecognised email domain that logs in. Only the
    literal value 'multi' opts out.
    """
    global _INVALID_TENANCY_MODE
    mode = (raw or "").strip().lower()
    if mode in TENANCY_MODES:
        return mode
    if mode:
        _INVALID_TENANCY_MODE = mode
    return "single"


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
    Every setting, resolved once at import from environment variables and
    defaults, with .env loaded first (override=True, so the file wins over an
    inherited shell environment). These are class attributes, so they are
    read at import time and cannot change for the life of the process: a
    setting whose behaviour depends on it changing later must be re-read from
    the environment by the code that needs it, not from here.

    validate() runs once from create_app() and is the startup gate. It raises
    listing every problem at once, so an operator fixes one deploy rather than
    one missing variable per attempt.
    """

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

    # Base URL and allowed origins default to localhost, NOT to any particular
    # deployment's hostname. These previously defaulted to the
    # selfalignmentframework.com hosts, which meant every self-hoster who did
    # not set WEB_BASE_URL silently inherited someone else's domain as their
    # CORS origin and OAuth callback base — a configuration that cannot work
    # for them and fails in ways (blocked cross-origin calls, callbacks
    # redirecting off-site) that give no clue as to the cause. Any real
    # deployment, including the public demo, sets WEB_BASE_URL explicitly in
    # its own .env.
    #
    # The official device client is the PWA (served same-origin), so no native
    # shell origins are needed (Capacitor retired 2026-08-19).
    _default_base_url = "http://localhost:5000"
    _default_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost",
    ]

    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", _default_base_url)

    # Comma-separated, e.g. ALLOWED_ORIGINS=http://localhost:5000,https://yourdomain.com
    _origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or _default_origins

    WEB_CALLBACK_URL = f"{WEB_BASE_URL}/api/callback"

    # Secure cookies follow the base URL's scheme; SESSION_COOKIE_SECURE
    # overrides it for local testing over HTTP.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "True").lower() == "true" and WEB_BASE_URL.startswith("https")

    SESSION_COOKIE_NAME = 'safi_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax' 

    # Ensure Flask generates URLs with https if behind a proxy
    PREFERRED_URL_SCHEME = 'https'

    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")

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

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    # Native-app Google Sign-In uses its own OAuth client id(s) — its ID tokens
    # carry a different audience than the web client above. List them here
    # (comma-separated) so mobile login tokens are accepted as valid audiences.
    GOOGLE_MOBILE_CLIENT_IDS = tuple(
        c.strip() for c in os.environ.get("GOOGLE_MOBILE_CLIENT_IDS", "").split(",") if c.strip()
    )

    MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
    MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")

    # Whether Google/Microsoft sign-in is offered at all. Defaults to True so
    # hosted deployments are untouched. The appliance sets this false: it is
    # air-gapped, so neither IdP is reachable and the buttons can only fail.
    # Enforced in auth.py by refusing the endpoints themselves, not just by
    # hiding the buttons -- an unauthenticated /api/login/google would
    # otherwise remain a working (if unreachable) entry point.
    SSO_LOGIN_ENABLED = _env_bool("SAFI_SSO_ENABLED", True)

    GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
    ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY")
    CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
    TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "").strip()
    # The appliance uses the harmless value "local". It remains an
    # API-key-shaped setting because the existing OpenAI client uses the same
    # initialization path for every OpenAI-compatible endpoint.
    LOCAL_MODEL_API_KEY = os.environ.get("SAFI_LOCAL_MODEL_API_KEY", "").strip()
    # There is deliberately no LOCAL_JEV_PATH field here. The directory of a
    # verified Laya bundle is read straight from the environment by jev_local,
    # because that lookup has to tell "absent" (probe the default location) from
    # "set to empty" (local Jev deliberately off, for comparison against hosted).
    # Any value resolved through Config collapses both to "" and loses the
    # distinction, which is the only part of it that carries meaning.
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

    # Comma-separated list of emails with super-admin access to the Audit Hub
    # (can see all orgs' logs). Blank disables super-admin access entirely.
    SUPER_ADMIN_EMAILS = [e.strip() for e in os.environ.get("SAFI_SUPER_ADMINS", "").split(",") if e.strip()]

    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "0"))

    # --- Tenancy mode --------------------------------------------------------
    #
    # single (default) — this deployment serves exactly one organization.
    #                     Every login joins that org directly: whoever signs
    #                     in first founds it and becomes its admin, everyone
    #                     after joins it as a member. No domain verification,
    #                     no absorption, no per-domain Founder Flow — there is
    #                     only ever one org to resolve to, so a fresh clone is
    #                     single-tenant with zero configuration.
    # multi               — the online demo's mode, and any self-hosted
    #                       instance meant to serve more than one
    #                       organization. Restores the original behavior: an
    #                       unaffiliated login with no invitation and no
    #                       verified domain founds its own personal org.
    #
    # An unrecognised value falls back to 'single', reported by validate().
    TENANCY_MODE = _resolve_tenancy_mode(os.environ.get("SAFI_TENANCY_MODE", "single"))

    # Advanced/migration override for single-tenant mode: pin to a specific
    # existing org id instead of auto-detecting the deployment's oldest org.
    # Leave unset in the normal case — a fresh install has no org yet to pin.
    SINGLE_TENANT_ORG_ID = os.environ.get("SAFI_SINGLE_TENANT_ORG_ID", "").strip() or None

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
    #
    # ...except on a single-tenant deployment, where guest login is refused
    # whatever SAFI_ENABLE_DEMO says. A guest does not join the deployment's one
    # organization: /api/login/demo calls db.create_organization() and mints a
    # second one named "SAFi Demo (xxxx)" (api/auth.py). That contradicts the
    # contract of single mode — one organization, served as a whole — and it has
    # a live side effect beyond the button: a second org row makes the
    # deployment-key guard see a multi-tenant install and lock the ordinary
    # admin out of the provider-key pane. SAFI_ENABLE_DEMO is therefore NOT an
    # override here, unlike every other flag in this file.
    ENABLE_DEMO_LOGIN = (
        False if TENANCY_MODE == 'single'
        else _env_bool("SAFI_ENABLE_DEMO", DEPLOYMENT_MODE in ("trial", "showcase"))
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
    # Username alternative to an email address. An air-gapped appliance has no
    # mail domain and no third-party identity to borrow an address from, so the
    # local admin is identified by a name it chose. Optional: a deployment that
    # still sets only SAFI_LOCAL_ADMIN_EMAIL keeps working exactly as before,
    # which is why the flag below accepts either one.
    LOCAL_ADMIN_USERNAME = os.environ.get("SAFI_LOCAL_ADMIN_USERNAME", "").strip().lower()
    # Password is the only hard requirement; either identifier is enough. Note
    # this must not require a username specifically, or every existing
    # email-based deployment would silently lose local login on upgrade.
    ENABLE_LOCAL_LOGIN   = bool(LOCAL_ADMIN_PASSWORD
                                and (LOCAL_ADMIN_USERNAME or LOCAL_ADMIN_EMAIL))

    # Maximum number of sequential tool-call turns the orchestrator will take
    # before forcing a final synthesis response. Raise this if your tools
    # need more hops to complete a task.
    MAX_AGENT_TURNS = int(os.environ.get("SAFI_MAX_AGENT_TURNS", "5"))

    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-%Y-%m-%d.jsonl")

    # Plaintext JSONL governance logs on disk — a DEBUG sink only, default
    # OFF. The system of record is the encrypted governance_records table,
    # written atomically with each turn and served by the native Audit Hub.
    DEBUG_JSONL_LOGS = os.environ.get("SAFI_DEBUG_JSONL_LOGS", "false").strip().lower() in ("1", "true", "yes")

    # Faculty model assignments, applied to authenticated users and bots.
    # Explicit SAFI_*_MODEL vars win; otherwise defaults follow the first
    # configured provider key so a fresh install works with any single key
    # (see _detect_faculty_defaults at module level).
    _faculty_defaults = _detect_faculty_defaults()
    INTELLECT_MODEL = _faculty_env("SAFI_INTELLECT_MODEL", _faculty_defaults["intellect"])
    CONSCIENCE_MODEL = _faculty_env("SAFI_CONSCIENCE_MODEL", _faculty_defaults["conscience"])

    # Models used exclusively by the public WordPress chatbot endpoint.
    # Falls back to the global defaults above if not set.
    PUBLIC_INTELLECT_MODEL = _faculty_env("SAFI_PUBLIC_INTELLECT_MODEL", INTELLECT_MODEL)
    PUBLIC_CONSCIENCE_MODEL = _faculty_env("SAFI_PUBLIC_CONSCIENCE_MODEL", CONSCIENCE_MODEL)
    SUMMARIZER_MODEL = _faculty_env("SAFI_SUMMARIZER_MODEL", _faculty_defaults["light"])
    # General-purpose background model (suggestions, etc.).
    BACKEND_MODEL = _faculty_env("SAFI_BACKEND_MODEL", _faculty_defaults["light"])
    # Dedicated note-taker (agent work-context) model — separate from BACKEND_MODEL so
    # note-taking can run on a different provider than suggestions/summaries.
    NOTETAKER_MODEL = _faculty_env("SAFI_NOTETAKER_MODEL", _faculty_defaults["light"])

    # --- Agent work-context ("note-taker") memory tuning ---
    # Sampling temperature for the background extraction call (deterministic by default).
    AGENT_MEMORY_TEMPERATURE = float(os.environ.get("SAFI_AGENT_MEMORY_TEMPERATURE", "0.0"))
    # Max entries retained per memory key after the code-side merge (bounds growth).
    AGENT_MEMORY_MAX_ITEMS_PER_KEY = int(os.environ.get("SAFI_AGENT_MEMORY_MAX_ITEMS", "80"))

    # --- Outbound email (Scheduled Updates, backlog 54) ---
    # SAFi sends email in exactly one place: delivering a scheduled task's
    # APPROVED output to its owner's account address. Unset = the feature
    # reports "email not configured" and schedules simply don't fire mail.
    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()

    @classmethod
    def smtp_configured(cls) -> bool:
        return bool(cls.SMTP_HOST and cls.SMTP_FROM)

    @classmethod
    def password_login_available(cls) -> bool:
        """Whether /login/local should even be reachable: the persistent
        local-admin account (ENABLE_LOCAL_LOGIN), or an invite-claim account
        (backlog 51) — which can only ever have been created while SMTP was
        configured to deliver its claim link, so smtp_configured() stands in
        for "a password account might exist" without a DB round trip. Not
        used by Config.validate()'s "at least one login method" check: an
        invite-claim account still needs a pre-existing admin to invite it,
        so SMTP alone can never bootstrap a deployment's first login."""
        return bool(cls.ENABLE_LOCAL_LOGIN or cls.smtp_configured())

    # Character budget for the work-context memory injected into the prompt each
    # turn (the RAG equivalent is MAX_CONTEXT_CHARS above).
    # Read-side only: the stored memory is never truncated, oldest entries are
    # simply left out of the injection and the model is told so. 0 disables.
    AGENT_MEMORY_MAX_CHARS = int(os.environ.get("SAFI_AGENT_MEMORY_MAX_CHARS", "12000"))
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

    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # Minimum alignment score Will requires before approving a response.
    # Overridable per-agent via
    # will_rules.structural_requirements.alignment_score_threshold.
    SPIRIT_ALIGNMENT_THRESHOLD = float(os.environ.get("SAFI_SPIRIT_THRESHOLD", "0.5"))

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

    # The registry scripts/safi_mcp.py searches. Nothing in a request path reads
    # it: installation is an operator action on the host (backlog 48d).
    MCP_REGISTRY_URL = os.environ.get(
        "SAFI_MCP_REGISTRY_URL", "https://registry.modelcontextprotocol.io"
    ).strip()
    # Set to False to disable the AI from silently adding facts to the user profile.
    ENABLE_PROFILE_EXTRACTION = False 

    # This list is sent to the frontend.
    #
    # LABELS ARE VERSIONLESS BY DESIGN; the "id" is the only version signal, and
    # the id is what actually gets sent. A label that carries a version has to be
    # rewritten every release, which churns saved UI state and every doc that
    # names a model. Two consequences worth knowing:
    #   - Sizes (120B, 20B) are KEPT. They are parameter counts, not versions,
    #     and dropping them would collapse both GPT-OSS rows into one label.
    #   - Uniqueness is NOT automatic. "GLM" and "Qwen" are family names, so a
    #     second model from either family reintroduces a duplicate that renders
    #     as two identical rows in the picker. test_built_in_labels_are_unique
    #     is the guard; keep the disambiguator when adding a second one.
    AVAILABLE_MODELS = [
        # NOTE: local (on-appliance) models are NOT listed here. They are
        # whatever the operator downloaded, so they are read from the appliance
        # catalogue at request time -- see provider_governance.installed_local_models.
        # The old hardcoded {"id": "safi-demo"} entry is gone: the ISO no longer
        # ships a model, and llama-server serves one --alias, so "safi-demo" was
        # an id nothing answered to.

        # Groq Models
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},

        # OpenAI Models. Ids must keep the "gpt-" prefix exactly as OpenAI
        # writes them: detect_provider routes on it to reach the openai client,
        # and llm_provider._is_openai_flagship keys on it to send
        # max_completion_tokens and drop temperature/top_p, which the whole
        # first-party line requires. Siblings gpt-5.6-sol, gpt-5.6-terra,
        # gpt-6-sol and gpt-6-astra also exist and are deliberately not listed.
        {"id": "gpt-6-luna", "label": "GPT Luna"},

        # Anthropic (Claude) Models
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku"},

        # Google Models. "Flash Lite" and "Flash" stay distinct on the tier
        # word alone, so neither needs its version back.
        {"id": "gemini-3.5-flash-lite", "label": "Gemini Flash Lite"},
        {"id": "gemini-3.8-flash", "label": "Gemini Flash"},
        {"id": "gemma-4-31b-it", "label": "Gemma 31B"},

        # Mistral Models
        {"id": "mistral-small-2603", "label": "Mistral Small"},
        {"id": "mistral-medium-latest", "label": "Mistral Medium"},

        # DeepSeek Models. "Flash"/"Pro" are the capability tier, like Mini/Pro
        # on OpenAI's line, so they survive the version being dropped.
        {"id": "deepseek-v4-flash", "label": "DeepSeek Flash"},
        {"id": "deepseek-v4-pro", "label": "DeepSeek Pro"},

        # Zhipu (Z.ai) Models
        {"id": "glm-5.2", "label": "GLM"},

        # Cerebras Models (bare ids, unlike Groq's "openai/"-prefixed ones).
        # Cerebras is inference-only and publishes no first-party model, so
        # every id here is someone else's: "qwen-" belongs to Cerebras purely
        # because Cerebras is what serves it. detect_provider claims that prefix
        # for the same reason -- see the cerebras branch there.
        {"id": "qwen-3.8-27b", "label": "Qwen"},
    ]

    MAX_UPLOAD_SIZE_MB = int(os.environ.get("SAFI_MAX_UPLOAD_MB", "10"))
    MAX_DOCUMENT_CHARS = int(os.environ.get("SAFI_MAX_DOC_CHARS", "50000"))
    ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx', '.xlsx', '.csv',
                                 '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp', '.bmp']

    # --- VOICE INPUT (speech to text) ---
    # Governed transcribe-then-govern: audio is transcribed locally by whisper.cpp
    # to text, and the TEXT enters the normal governed pipeline through the
    # composer, so Phase Zero scans it and it lands in the audit record. Raw audio
    # never reaches a reasoning model and is not stored. Off by default; turn it on
    # only where the whisper.cpp binary and model exist (an install that ran the
    # setup, not a stock Docker image). Same shape as the image OCR path.
    VOICE_INPUT_ENABLED = os.environ.get("SAFI_VOICE_INPUT", "false").lower() == "true"
    WHISPER_CLI_PATH = os.environ.get("SAFI_WHISPER_BIN", "/opt/whisper.cpp/build/bin/whisper-cli")
    WHISPER_MODEL_PATH = os.environ.get("SAFI_WHISPER_MODEL", "/opt/whisper.cpp/models/ggml-base.en.bin")
    MAX_AUDIO_SIZE_MB = int(os.environ.get("SAFI_MAX_AUDIO_MB", "10"))
    WHISPER_TIMEOUT_SECONDS = int(os.environ.get("SAFI_WHISPER_TIMEOUT", "120"))

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

    # --- RAG RETRIEVAL CONTEXT ---
    # Ceiling on the assembled retrieval context handed to the Intellect, in
    # characters. The Conscience audits against the same block, so this is paid
    # for twice a turn.
    #
    # Default is UNLIMITED. Truncation is not merely a token cost: the dropped
    # evidence makes the Conscience's claims unverifiable, and the truncation
    # notice tells the model the passage is incomplete and not to fill the gap
    # from memory. Both suppress confidence on exactly the grounding-fidelity
    # values the notice was written to protect. k on the retriever remains the
    # backstop against a runaway corpus; this is the operator's override.
    _raw_max_context = os.environ.get("SAFI_MAX_CONTEXT_CHARS", "unlimited").strip().lower()
    MAX_CONTEXT_CHARS = 0 if _raw_max_context in ("", "all", "unlimited", "-1") else int(_raw_max_context)

    @classmethod
    def validate(cls) -> None:
        """
        The startup gate. Raises ValueError listing every missing or invalid
        required variable at once, so an operator fixes one deploy rather than
        discovering one problem per attempt.
        """
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

        # Check LLM provider keys
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

        # Non-fatal warnings
        if cls.BOT_API_SECRET == "safi-bot-secret-123":
            _log.warning("SAFI_BOT_API_SECRET is using the insecure default value — set it in .env")
        if cls.APP_ENV != 'production' and cls.SECRET_KEY == "dev-secret-key-should-be-changed":
            _log.warning("FLASK_SECRET_KEY is using the insecure default value")
