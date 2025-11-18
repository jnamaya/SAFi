"""
Shared utilities for the entire SAFi application.

This module contains common, stateless helper functions that are used
by multiple parts of the application, including the orchestrator and
various faculties.
"""
from __future__ import annotations
import re
import json
import hashlib
import unicodedata

# --- Normalization Utilities ---

# Define various Unicode dash characters for normalization.
DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]  # hyphen, nb-hyphen, figure dash, en, em, minus

def normalize_text(s: str) -> str:
    """
    Normalize strings for safe matching across Unicode variants and spacing.
    
    This function is used to safely compare value names, cache keys, etc.
    
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

# --- Hashing Utilities ---

def dict_sha256(d: dict) -> str:
    """
    Creates a reproducible SHA256 hash from a dictionary.

    This is used to create stable cache keys from complex objects.
    
    Args:
        d: The dictionary to hash.

    Returns:
        A SHA256 hash string.
    """
    try:
        # sort_keys=True ensures the JSON string is always the same
        s = json.dumps(d, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()
    except Exception:
        # Fallback for non-serializable objects
        return hashlib.sha256(str(d).encode("utf-8")).hexdigest()