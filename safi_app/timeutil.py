# Timestamp serialization for API responses.
#
# MySQL DATETIME/TIMESTAMP columns hold UTC wall time but the connector
# returns them as naive datetimes. A naive ISO string ("2026-08-14T02:51:00")
# is parsed by browsers as LOCAL time, so the UI displays the UTC clock as if
# it were the viewer's. Every instant-typed timestamp leaving the API must go
# through utc_isoformat so it carries an explicit +00:00 offset and the
# browser localizes it.
#
# Date-only filter echoes (an audit range like "from 2026-08-01") are the
# deliberate exception: they are calendar dates, not instants, and stamping
# them +00:00 would shift them a day for viewers west of UTC.

from datetime import datetime, timezone
from typing import Optional


def utc_isoformat(dt) -> Optional[str]:
    """ISO-8601 with explicit UTC offset. Naive input is trusted to be UTC
    wall time (what MySQL hands back). None and strings pass through."""
    if dt is None or isinstance(dt, str):
        return dt
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
