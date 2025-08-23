import os

class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    DATABASE_NAME = os.environ.get("SAFI_DB", "safi_memory.db")
    LOG_FILE = os.environ.get("SAFI_LOG", "saf-spirit-log.jsonl")

    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", "gpt-4o")
    WILL_MODEL = os.environ.get("SAFI_WILL_MODEL", "gpt-4o")
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", "gpt-4o")

    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # Default worldview profile key: 'catholic' or 'guardian'
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "catholic").strip().lower()