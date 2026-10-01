from __future__ import annotations
import re
import unicodedata

DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]

def _norm_label(s: str) -> str:
    """Normalize a value label so config names and auditor-returned names compare
    equal across case, spacing and Unicode dash variants.

    Will fails closed on a hard gate whose label it cannot match, so every
    faculty that reads a ledger has to normalize the same way.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    for d in DASHES:
        s = s.replace(d, "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s
