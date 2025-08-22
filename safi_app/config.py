import os

class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-should-be-changed")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    DATABASE_NAME = "safi_memory.db"
    LOG_FILE = "saf-spirit-log.jsonl"
    INTELLECT_MODEL = "gpt-4o"
    WILL_MODEL = "gpt-4o"
    CONSCIENCE_MODEL = "gpt-4o"
    SPIRIT_BETA = 0.9
