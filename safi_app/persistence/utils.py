import json
import hashlib
from typing import Dict, Any


def normalize_text(s: str) -> str:
    """
    Normalize a string for consistent comparison.
    - Strips leading/trailing whitespace
    - Collapses multiple spaces into one
    - Converts to lowercase
    """
    return " ".join((s or "").split()).strip().lower()


def dict_sha256(d: Dict[str, Any]) -> str:
    """
    Compute a SHA-256 hash of a dictionary.
    - Serializes dict into JSON with sorted keys
    - Preserves non-ASCII characters
    - Returns a hex digest string
    Useful for caching, deduplication, and unique keys.
    """
    payload = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
