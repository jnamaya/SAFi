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
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _code_at(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32.upper().replace(" ", ""))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** DIGITS)).zfill(DIGITS)


def verify_code(secret_b32: str, code: str, window: int = 1, at_time: float | None = None) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    try:
        counter = int((at_time if at_time is not None else time.time()) // STEP_SECONDS)
        ok = False
        for offset in range(-window, window + 1):
            expected = _code_at(secret_b32, counter + offset)
            ok = hmac.compare_digest(expected, code) or ok
        return ok
    except Exception:
        return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = "SAFi") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({
        "secret": secret_b32, "issuer": issuer,
        "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS,
    })
    return f"otpauth://totp/{label}?{query}"
