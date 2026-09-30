"""
String normalisation and hashing shared by the orchestrator and faculties.

normalize_text exists so one value name compares equal however it was typed —
Unicode dashes, doubled spaces, case. It backs value-name matching, cache
keys and config lookups, so anything looser here silently splits a policy's
value from its ledger entry.
"""
from __future__ import annotations
import re
import json
import hashlib
import unicodedata

# Unicode dashes NFKC leaves alone; all collapse to a plain hyphen.
DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]  # hyphen, nb-hyphen, figure dash, en, em, minus

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
        # sort_keys keeps the hash reproducible across processes. The str()
        # fallback below is deliberately NOT a stable serialization — it only
        # keeps an unserializable value from breaking a cache lookup.
        s = json.dumps(d, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(str(d).encode("utf-8")).hexdigest()