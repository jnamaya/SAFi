from __future__ import annotations
import re
import json
import hashlib
import unicodedata

DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    for d in DASHES:
        s = s.replace(d, "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def dict_sha256(d: dict) -> str:
    try:
        s = json.dumps(d, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(str(d).encode("utf-8")).hexdigest()