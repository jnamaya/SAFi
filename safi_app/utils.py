import json
import hashlib
from typing import Dict, Any

def normalize_text(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()

def dict_sha256(d: Dict[str, Any]) -> str:
    payload = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
