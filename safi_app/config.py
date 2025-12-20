import os
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
    if APP_ENV == 'development':
        # Development URLs (Dev Server)
        WEB_BASE_URL = "https://chat.selfalignmentframework.com"
        ALLOWED_ORIGINS = [
            "https://chat.selfalignmentframework.com",
            "capacitor://localhost",
            "http://localhost",
            "ionic://localhost"
        ]
    else:
        # Production URLs (Live Server)
        WEB_BASE_URL = "https://safi.selfalignmentframework.com"
        ALLOWED_ORIGINS = [
            "https://safi.selfalignmentframework.com",
            "https://selfalignmentframework.com",
            "capacitor://localhost",
            "http://localhost",
            "ionic://localhost"
        ]

    # 3. Derive the callback URL
    WEB_CALLBACK_URL = f"{WEB_BASE_URL}/api/callback"

    # --- Session Security ---
    # FIX: Automatically enforce Secure cookies if the Base URL is HTTPS.
    SESSION_COOKIE_SECURE = WEB_BASE_URL.startswith("https")
    
    SESSION_COOKIE_NAME = 'safi_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax' 
    
    # Ensure Flask generates URLs with https if behind a proxy
    PREFERRED_URL_SCHEME = 'https'

    # --- Secrets & Keys ---

    # Secret key for Flask session management
    # CRITICAL SECURITY FIX: Fail in production if secret key is missing
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
    if APP_ENV == 'production' and not SECRET_KEY:
        raise ValueError("FATAL: FLASK_SECRET_KEY is not set in production environment.")
    if not SECRET_KEY:
        SECRET_KEY = "dev-secret-key-should-be-changed"

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
    
    # DEBUG STARTUP
    print(f"--- CONFIG STARTUP ---")
    print(f"Loading .env from: {dotenv_path}")
    print(f"GITHUB_CLIENT_ID found in env? { 'GITHUB_CLIENT_ID' in os.environ }")
    print(f"GITHUB_CLIENT_ID value: {GITHUB_CLIENT_ID}")
    print(f"----------------------")

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

    # Usage controls
    DAILY_PROMPT_LIMIT = int(os.environ.get("SAFI_DAILY_PROMPT_LIMIT", "0"))

    # Logging configuration
    LOG_DIR = os.environ.get("SAFI_LOG_DIR", "logs")
    LOG_FILE_TEMPLATE = os.environ.get("SAFI_LOG_TEMPLATE", "{profile}-%Y-%m-%d.jsonl")

    # Model assignments for each faculty (defaults)
    INTELLECT_MODEL = os.environ.get("SAFI_INTELLECT_MODEL", "openai/gpt-oss-120b")
    WILL_MODEL = os.environ.get("SAFI_WILL_MODEL", "llama-3.3-70b-versatile")
    CONSCIENCE_MODEL = os.environ.get("SAFI_CONSCIENCE_MODEL", "qwen/qwen3-32b")
    SUMMARIZER_MODEL = os.environ.get("SAFI_SUMMARIZER_MODEL", "llama-3.1-8b-instant")
    BACKEND_MODEL = os.environ.get("SAFI_BACKEND_MODEL", "llama-3.1-8b-instant")

    # --- TTS CONFIGURATION ---
    TTS_MODEL = os.environ.get("SAFI_TTS_MODEL", "gpt-4o-mini-tts") 
    TTS_VOICE = os.environ.get("SAFI_TTS_VOICE", "alloy") 
    TTS_CACHE_DIR = os.path.join(project_root, "tts_cache") 

    # Spirit computation parameters
    SPIRIT_BETA = float(os.environ.get("SAFI_SPIRIT_BETA", "0.9"))

    # Default profile to use when none is specified
    DEFAULT_PROFILE = os.environ.get("SAFI_PROFILE", "tutor").strip().lower()

       # --- CONFIGURATION: AUTOMATIC PROFILE EXTRACTION ---
    # Set to False to disable the AI from silently adding facts to the user profile.
    ENABLE_PROFILE_EXTRACTION = False 

    # This list is sent to the frontend.
    AVAILABLE_MODELS = [
        # Groq Models
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B (Fastest/good for most things)", "categories": ["intellect"]},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B (Efficient)", "categories": ["support"]},
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (Balanced)", "categories": ["support"]},
        {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B (Fastest)", "categories": ["support"]},
        {"id": "qwen/qwen3-32b", "label": "Qwen 3 32B (Strong Reasoning)", "categories": ["support"]},
        {"id": "openai/gpt-oss-safeguard-20b", "label": "Safety GPT OSS 20B (Safety Model)", "categories": ["support"]},

        # OpenAI Models
        {"id": "gpt-3.5-turbo", "label": "GPT-3.5 Turbo (Legacy)", "categories": ["support"]},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini (Cost Effective)", "categories": ["support", "intellect"]},
        {"id": "gpt-4o", "label": "GPT-4o (High Intelligence)", "categories": ["intellect"]},
        {"id": "gpt-4.1", "label": "GPT-4.1 (Complex Logic)", "categories": ["intellect"]},
        {"id": "gpt-5.1-2025-11-13", "label": "GPT-5.1 Preview (Next-Gen/Slow)", "categories": ["intellect"]},
        
        # Anthropic (Claude) Models
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (Creative/Slow)", "categories": ["intellect"]},
        {"id": "claude-3-7-sonnet-latest", "label": "Claude 3.7 Sonnet (Nuanced)", "categories": ["support"]},

        # Google Models
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (Speed & Context)", "categories": ["intellect"]},
        {"id": "gemini-3-pro-preview", "label": "Gemini 3 Pro (Deep Reasoning/Slow)", "categories": ["intellect"]},

         # Mistral Models
        {"id": "mistral-large-2512", "label": "Mistral Large 3 (Big and slow)", "categories": ["intellect"]},

         # DeekSeek Models
        {"id": "deepseek-chat", "label": "DeepSeek v3 (Experimental)", "categories": ["intellect"]},
    ]