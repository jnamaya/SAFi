from datetime import datetime, timezone
from typing import Optional


def utc_isoformat(dt) -> Optional[str]:
    if dt is None or isinstance(dt, str):
        return dt
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
