"""
Pure unit tests for the Reg S-P 30-day notification clock (no DB).

Run:  venv/bin/python tests/test_incident_clock.py
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api.incidents_api import compute_notification_clock

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def incident(**kw):
    base = {"firm_aware_at": None, "customers_notified_at": None,
            "harm_determination": None, "ag_delay": False, "ag_delay_until": None,
            "vendor_aware_at": None, "vendor_notified_firm_at": None}
    base.update(kw)
    return base


class TestClock(unittest.TestCase):

    def test_running_with_days_remaining(self):
        c = compute_notification_clock(incident(firm_aware_at=NOW - timedelta(days=10)), now=NOW)
        self.assertEqual(c["state"], "running")
        self.assertEqual(c["days_remaining"], 20)
        self.assertIn("2026-08-02", c["due_at"])

    def test_overdue(self):
        c = compute_notification_clock(incident(firm_aware_at=NOW - timedelta(days=35)), now=NOW)
        self.assertEqual(c["state"], "overdue")
        self.assertLess(c["days_remaining"], 0)

    def test_due_boundary_still_running(self):
        c = compute_notification_clock(incident(firm_aware_at=NOW - timedelta(days=30, hours=-1)), now=NOW)
        self.assertEqual(c["state"], "running")

    def test_excepted_by_harm_determination(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW - timedelta(days=40), harm_determination="no_substantial_harm"),
            now=NOW)
        self.assertEqual(c["state"], "excepted")

    def test_notification_required_keeps_clock_running(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW - timedelta(days=5), harm_determination="notification_required"),
            now=NOW)
        self.assertEqual(c["state"], "running")

    def test_notified_stops_clock(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW - timedelta(days=12),
                     customers_notified_at=NOW - timedelta(days=2)), now=NOW)
        self.assertEqual(c["state"], "notified")
        self.assertEqual(c["days_taken"], 10)

    def test_ag_delay_extends_due_date(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW - timedelta(days=35), ag_delay=True,
                     ag_delay_until=NOW + timedelta(days=10)), now=NOW)
        self.assertEqual(c["state"], "running")
        self.assertEqual(c["days_remaining"], 10)

    def test_ag_delay_earlier_than_30_days_is_ignored(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW - timedelta(days=5), ag_delay=True,
                     ag_delay_until=NOW + timedelta(days=1)), now=NOW)
        # due stays at aware+30 (25 days out), not the earlier AG date
        self.assertEqual(c["days_remaining"], 25)

    def test_vendor_notice_within_72h(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW, vendor_aware_at=NOW - timedelta(hours=71),
                     vendor_notified_firm_at=NOW), now=NOW)
        self.assertFalse(c["vendor_notice_late"])
        self.assertAlmostEqual(c["vendor_notice_hours"], 71.0, places=1)

    def test_vendor_notice_late(self):
        c = compute_notification_clock(
            incident(firm_aware_at=NOW, vendor_aware_at=NOW - timedelta(hours=73),
                     vendor_notified_firm_at=NOW), now=NOW)
        self.assertTrue(c["vendor_notice_late"])

    def test_vendor_missing_timestamps(self):
        c = compute_notification_clock(incident(firm_aware_at=NOW), now=NOW)
        self.assertIsNone(c["vendor_notice_hours"])
        self.assertIsNone(c["vendor_notice_late"])

    def test_mysql_naive_datetime_input(self):
        # Rows come back from MySQL as naive datetimes
        c = compute_notification_clock(
            incident(firm_aware_at=datetime(2026, 7, 1, 9, 0, 0)), now=NOW)
        self.assertEqual(c["state"], "running")

    def test_iso_string_input(self):
        c = compute_notification_clock(incident(firm_aware_at="2026-06-01T00:00:00Z"), now=NOW)
        self.assertEqual(c["state"], "overdue")

    def test_no_aware_date(self):
        c = compute_notification_clock(incident(), now=NOW)
        self.assertEqual(c["state"], "running")
        self.assertIsNone(c["due_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
