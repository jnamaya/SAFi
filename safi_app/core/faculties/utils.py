from __future__ import annotations
import re
import unicodedata

DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]

def _norm_label(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    for d in DASHES:
        s = s.replace(d, "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s
