# safi_app/persistence/crypto.py
"""Application-level encryption at rest for sensitive columns.

Fernet (AES-128-CBC + HMAC) via SAFI_ENCRYPTION_KEY. The key accepts a
comma-separated list: the first key encrypts, all keys decrypt (MultiFernet),
so rotation is prepending a new key and re-running the backfill script.

Dual-read contract: decrypt_value() passes non-token values through unchanged,
so rows written before encryption was enabled keep working. Ciphertext is
recognizable — Fernet tokens are urlsafe-base64 and always start "gAAAA"
(version byte 0x80 + timestamp). A plaintext value starting with that prefix
would be silently misclassified, which is why decrypt falls back to returning
the raw value when the token fails to authenticate.

When SAFI_ENCRYPTION_KEY is unset the module is a passthrough (plaintext
mode); Config.validate() forbids that in production.
"""
import logging
from typing import Optional, Sequence

from cryptography.fernet import Fernet, MultiFernet, InvalidToken

from ..config import Config

logger = logging.getLogger(__name__)

FERNET_PREFIX = "gAAAA"

_fernet: Optional[MultiFernet] = None


def _get_fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        keys = [k.strip() for k in Config.ENCRYPTION_KEY.split(",") if k.strip()]
        try:
            _fernet = MultiFernet([Fernet(k) for k in keys])
        except (ValueError, TypeError) as e:
            raise ValueError(
                "SAFI_ENCRYPTION_KEY is malformed — each comma-separated entry must be "
                "a urlsafe-base64 32-byte Fernet key (generate with Fernet.generate_key())"
            ) from e
    return _fernet


def is_enabled() -> bool:
    """True when a master key is configured (encryption active)."""
    return bool(Config.ENCRYPTION_KEY.strip())


def is_token(value) -> bool:
    """True when the value looks like Fernet ciphertext."""
    return isinstance(value, str) and value.startswith(FERNET_PREFIX)


def encrypt_value(value: Optional[str]) -> Optional[str]:
    """Encrypts a string for storage. None/empty pass through; already-encrypted
    values pass through (idempotency guard for re-runs and copy paths)."""
    if value is None or value == "" or not is_enabled() or is_token(value):
        return value
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value):
    """Decrypts a stored value. Non-token values (legacy plaintext rows, None,
    non-strings) return unchanged. An unverifiable token returns unchanged with
    a warning rather than raising — serving ciphertext is recoverable once the
    right key is restored; a hard failure would take the whole read path down."""
    if not is_token(value):
        return value
    if not is_enabled():
        logger.warning("Encrypted value read while SAFI_ENCRYPTION_KEY is unset — returning ciphertext")
        return value
    try:
        return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("Stored value failed decryption (wrong/rotated-out key?) — returning raw value")
        return value


def decrypt_fields(row: Optional[dict], fields: Sequence[str]) -> Optional[dict]:
    """Decrypts the named fields of a dict-cursor row in place. None-safe."""
    if row is None:
        return None
    for f in fields:
        if f in row:
            row[f] = decrypt_value(row[f])
    return row
