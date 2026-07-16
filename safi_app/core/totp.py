"""
RFC 6238 TOTP — stdlib only (hmac/sha1, 30s step, 6 digits).

Deliberately dependency-free: this is ~40 lines of well-specified HMAC
arithmetic, and every byte that touches MFA should be reviewable in one
screen. Secrets are generated here but stored encrypted (Fernet) by the
persistence layer; this module never touches the database.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP_SECONDS = 30
DIGITS = 6


def generate_secret() -> str:
    """160-bit random secret, Base32 (the alphabet authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _code_at(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32.upper().replace(" ", ""))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** DIGITS)).zfill(DIGITS)


def verify_code(secret_b32: str, code: str, window: int = 1, at_time: float | None = None) -> bool:
    """Accept the current step ±window (clock skew). Constant-time compares;
    never raises on malformed input — malformed just fails verification."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    try:
        counter = int((at_time if at_time is not None else time.time()) // STEP_SECONDS)
        ok = False
        for offset in range(-window, window + 1):
            expected = _code_at(secret_b32, counter + offset)
            # No early exit: every candidate is compared so timing does not
            # reveal which step matched.
            ok = hmac.compare_digest(expected, code) or ok
        return ok
    except Exception:
        return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = "SAFi") -> str:
    """otpauth:// URI — scannable/pastable into any authenticator app."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({
        "secret": secret_b32, "issuer": issuer,
        "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS,
    })
    return f"otpauth://totp/{label}?{query}"
