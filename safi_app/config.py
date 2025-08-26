# safi_app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    DATABASE_NAME = os.environ.get("SAFI_DB", "safi_memory.db")

    # Set to 0 or a negative number for unlimited prompts.
    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "10"))

    # legacy single-file log path still supported
    LOG_FILE = os.environ.get("SAFI_LOG", "saf-spirit-log.jsonl")

    # new date-sharded logging
    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-spirit-%Y-%m-%d.jsonl")

    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", "gpt-4o")
    WILL_MODEL = os.environ.get("SAFI_WILL_MODEL", "gpt-4o")
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", "gpt-4o")
    # --- NEW: Added a specific model for summarization ---
    SUMMARIZER_MODEL = os.environ.get("SAFI_SUMMARIZER_MODEL", "gpt-3.5-turbo")


    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # default values profile key
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "secular").strip().lower()
