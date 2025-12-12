"""
Shared utilities specifically for the faculties modules.
"""
from __future__ import annotations
import re
import unicodedata

# Define various Unicode dash characters for normalization.
DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]  # hyphen, nb-hyphen, figure dash, en, em, minus

def _norm_label(s: str) -> str:
    """
    Normalize labels for safe matching across Unicode variants and spacing.
    
    This function is used to safely compare value names from the config
    with value names returned by the LLM.
    
    Args:
        s: The string to normalize.
        
    Returns:
        A normalized, lowercased, and space-standardized string.
    """
    if s is None:
        return ""
    # NFKC normalization handles different character representations
    s = unicodedata.normalize("NFKC", str(s))
    # Replace all Unicode dashes with a standard hyphen
    for d in DASHES:
        s = s.replace(d, "-")
    # Consolidate whitespace, strip, and lowercase
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s