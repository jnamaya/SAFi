# safi_app/config.py
import os

class Config:
    """
    Central configuration class for SAFi.
    Loads settings from environment variables with sensible defaults.
    Used by the main app and orchestrator to determine runtime behavior.
    """

    # Secret key for Flask session management
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")

    # OAuth credentials for Google login
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # API keys for model providers
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

    # MySQL connection details ---
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "safi")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "@CCion56admin")
    DB_NAME = os.environ.get("DB_NAME", "safi")

    # Usage controls
    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "50"))

    # Logging configuration
    LOG_FILE = os.environ.get("SAFI_LOG", "saf-spirit-log.jsonl")
    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-%Y-%m-%d.jsonl")

    # Model assignments for each faculty
    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", "claude-sonnet-4-20250514")
    WILL_MODEL = os.environ.get("SAFI_WILL_MODEL", "gpt-4o")
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", "gpt-4o")
    SUMMARIZER_MODEL = os.environ.get("SAFI_SUMMARIZER_MODEL", "gpt-4o-mini")

    # Spirit computation parameters
    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # Default profile to use when none is specified
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "virtue_ethics").strip().lower()

