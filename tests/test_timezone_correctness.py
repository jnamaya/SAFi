"""
The two ways SAFi's clock must respect the user's timezone.

WHY. A demo user asked at 10pm Thursday (EDT) "how is our schedule for
tomorrow" and was told tomorrow was Saturday: the orchestrator prepends the
current date in UTC, where it was already 2am Friday. Separately, several
API responses serialized DB datetimes with a bare isoformat(), and browsers
parse an offset-less ISO string as LOCAL time, so Control Panel views showed
the UTC wall clock as if it were the viewer's.

Two contracts, pinned here:

1. `_current_date_line` renders the user's calendar when the client sends an
   IANA zone, keeps UTC alongside for audit clarity, and treats the zone
   string as untrusted input: junk falls back to the UTC-only line, never an
   error. The zone is prompt context only; nothing deterministic reads it.
2. `utc_isoformat` stamps every instant leaving the API with an explicit
   UTC offset, so the browser (the only party that knows the viewer's
   timezone) does the localizing. Naive DB datetimes are trusted to be UTC
   wall time, which is what MySQL hands back on a UTC server.

No database needed; this file runs standalone.

Run:  venv/bin/python tests/test_timezone_correctness.py
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.timeutil import utc_isoformat
from safi_app.core.orchestrator import _current_date_line

# The reported failure, reconstructed: Thursday 2026-08-13 22:00 EDT is
# Friday 2026-08-14 02:00 UTC.
THURSDAY_NIGHT_UTC = datetime(2026, 8, 14, 2, 0, 0, tzinfo=timezone.utc)


class CurrentDateLine(unittest.TestCase):

    def test_no_timezone_keeps_the_utc_line_verbatim(self):
        line = _current_date_line(THURSDAY_NIGHT_UTC)
        self.assertEqual(line, "Current Date: Friday, August 14, 2026. 02:00:00 Z")

    def test_users_zone_wins_the_weekday(self):
        line = _current_date_line(THURSDAY_NIGHT_UTC, "America/New_York")
        self.assertIn("Thursday, August 13, 2026", line)
        self.assertIn("America/New_York", line)
        # The user's calendar leads; Friday appears only in the UTC tail.
        self.assertTrue(line.startswith("Current Date: Thursday"))

    def test_utc_stays_alongside_for_audit_clarity(self):
        line = _current_date_line(THURSDAY_NIGHT_UTC, "America/New_York")
        self.assertIn("UTC: Friday 02:00:00 Z", line)

    def test_east_of_utc_shifts_the_other_way(self):
        # 02:00 UTC Friday is already 11:00 Friday in Tokyo.
        line = _current_date_line(THURSDAY_NIGHT_UTC, "Asia/Tokyo")
        self.assertTrue(line.startswith("Current Date: Friday"))
        self.assertIn("11:00", line)

    def test_junk_zone_falls_back_to_utc_not_an_error(self):
        for junk in ("Neverland/Nowhere", "'; DROP TABLE--", "UTC+5", " ", "\x00"):
            line = _current_date_line(THURSDAY_NIGHT_UTC, junk)
            self.assertEqual(
                line, "Current Date: Friday, August 14, 2026. 02:00:00 Z",
                f"zone {junk!r} must fall back to the UTC line")

    def test_the_reported_bug_is_dead(self):
        """At 10pm EDT the model must not be told it is Friday."""
        line = _current_date_line(THURSDAY_NIGHT_UTC, "America/New_York")
        date_half = line.split("UTC:")[0]
        self.assertNotIn("Friday", date_half)


class UtcIsoformat(unittest.TestCase):

    def test_naive_db_datetime_gets_explicit_utc_offset(self):
        out = utc_isoformat(datetime(2026, 8, 14, 2, 51, 0))
        self.assertEqual(out, "2026-08-14T02:51:00+00:00")

    def test_aware_datetime_is_normalized_to_utc(self):
        edt = timezone(timedelta(hours=-4))
        out = utc_isoformat(datetime(2026, 8, 13, 22, 51, 0, tzinfo=edt))
        self.assertEqual(out, "2026-08-14T02:51:00+00:00")

    def test_none_and_strings_pass_through(self):
        self.assertIsNone(utc_isoformat(None))
        self.assertEqual(utc_isoformat("2026-08-14"), "2026-08-14")

    def test_every_output_carries_an_offset(self):
        """The property the browser depends on: no offset-less instants."""
        out = utc_isoformat(datetime(2026, 1, 1, 0, 0, 0))
        self.assertTrue(out.endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
