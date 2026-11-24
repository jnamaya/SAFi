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
    return bool(Config.ENCRYPTION_KEY.strip())


def is_token(value) -> bool:
    return isinstance(value, str) and value.startswith(FERNET_PREFIX)


def encrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or not is_enabled() or is_token(value):
        return value
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value):
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
    if row is None:
        return None
    for f in fields:
        if f in row:
            row[f] = decrypt_value(row[f])
    return row
