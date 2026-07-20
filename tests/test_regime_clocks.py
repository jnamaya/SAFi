"""
Pure unit tests for the regime-keyed notification clocks (Phase D — no DB).

Covers the rule table itself (reg_sp / eu_ai_act / hipaa), regime tagging
defaults for legacy rows, and multi-regime composition. The original Reg S-P
clock keeps its own suite in test_incident_clock.py.

Run:  venv/bin/python tests/test_regime_clocks.py
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api.incidents_api import (
    REGIME_RULES, compute_notification_clocks, incident_regimes,
)

NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def incident(**kw):
    base = {"firm_aware_at": None, "customers_notified_at": None,
            "harm_determination": None, "ag_delay": False, "ag_delay_until": None,
            "vendor_aware_at": None, "vendor_notified_firm_at": None,
            "regimes": None, "eu_incident_class": None, "hipaa_role": None,
            "affected_count": None, "authority_notified_at": None,
            "individuals_notified_at": None, "hhs_notified_at": None,
            "media_notified_at": None, "ce_notified_at": None}
    base.update(kw)
    return base


def by_key(clocks, key):
    return next(c for c in clocks if c["key"] == key)


class TestRegimeTagging(unittest.TestCase):

    def test_legacy_row_reads_as_reg_sp(self):
        self.assertEqual(incident_regimes(incident(regimes=None)), ["reg_sp"])
        self.assertEqual(incident_regimes(incident(regimes=[])), ["reg_sp"])

    def test_json_string_regimes_parsed(self):
        self.assertEqual(incident_regimes(incident(regimes='["hipaa", "eu_ai_act"]')),
                         ["eu_ai_act", "hipaa"])  # canonical order

    def test_unknown_keys_dropped(self):
        self.assertEqual(incident_regimes(incident(regimes=["hipaa", "gdpr"])), ["hipaa"])
        self.assertEqual(incident_regimes(incident(regimes=["gdpr"])), ["reg_sp"])

    def test_rule_table_covers_all_keys(self):
        self.assertEqual(tuple(REGIME_RULES), ("reg_sp", "eu_ai_act", "hipaa"))
        for rule in REGIME_RULES.values():
            self.assertIn("label", rule)
            self.assertTrue(callable(rule["clocks"]))


class TestRegSPClock(unittest.TestCase):

    def test_reg_sp_only_by_default_with_metadata(self):
        clocks = compute_notification_clocks(
            incident(firm_aware_at=NOW - timedelta(days=10)), now=NOW)
        self.assertEqual(len(clocks), 1)
        c = clocks[0]
        self.assertEqual((c["regime"], c["key"], c["state"], c["days_remaining"]),
                         ("reg_sp", "customer_notice", "running", 20))
        self.assertEqual(c["window_days"], 30)

    def test_reg_sp_exception_and_vendor_fields_survive(self):
        clocks = compute_notification_clocks(
            incident(firm_aware_at=NOW - timedelta(days=40),
                     harm_determination="no_substantial_harm",
                     vendor_aware_at=NOW - timedelta(hours=80),
                     vendor_notified_firm_at=NOW), now=NOW)
        c = by_key(clocks, "customer_notice")
        self.assertEqual(c["state"], "excepted")
        self.assertTrue(c["vendor_notice_late"])

    def test_notified_at_exposed(self):
        clocks = compute_notification_clocks(
            incident(firm_aware_at=NOW - timedelta(days=12),
                     customers_notified_at=NOW - timedelta(days=2)), now=NOW)
        c = by_key(clocks, "customer_notice")
        self.assertEqual(c["state"], "notified")
        self.assertIn("2026-07-18", c["notified_at"])


class TestEUAIActClock(unittest.TestCase):

    def _clock(self, **kw):
        kw.setdefault("regimes", ["eu_ai_act"])
        return by_key(compute_notification_clocks(incident(**kw), now=NOW), "eu_authority")

    def test_general_is_15_days(self):
        c = self._clock(firm_aware_at=NOW - timedelta(days=5))
        self.assertEqual((c["window_days"], c["days_remaining"], c["state"]), (15, 10, "running"))

    def test_missing_class_defaults_to_general(self):
        c = self._clock(firm_aware_at=NOW, eu_incident_class=None)
        self.assertEqual(c["window_days"], 15)

    def test_death_is_10_days(self):
        c = self._clock(firm_aware_at=NOW - timedelta(days=11),
                        eu_incident_class="death_or_serious_harm")
        self.assertEqual((c["window_days"], c["state"]), (10, "overdue"))

    def test_widespread_is_2_days(self):
        c = self._clock(firm_aware_at=NOW - timedelta(days=1),
                        eu_incident_class="widespread")
        self.assertEqual((c["window_days"], c["days_remaining"], c["state"]), (2, 1, "running"))

    def test_authority_notified_stops_clock(self):
        c = self._clock(firm_aware_at=NOW - timedelta(days=8),
                        authority_notified_at=NOW - timedelta(days=1))
        self.assertEqual((c["state"], c["days_taken"]), ("notified", 7))

    def test_harm_determination_does_not_except_eu(self):
        # The Reg S-P no-substantial-harm exception is regime-specific:
        # a non-reportable EU incident is untagged instead.
        c = self._clock(firm_aware_at=NOW - timedelta(days=20),
                        harm_determination="no_substantial_harm")
        self.assertEqual(c["state"], "overdue")


class TestHIPAAClocks(unittest.TestCase):

    def _clocks(self, **kw):
        kw.setdefault("regimes", ["hipaa"])
        return compute_notification_clocks(incident(**kw), now=NOW)

    def test_covered_entity_small_breach(self):
        clocks = self._clocks(firm_aware_at=NOW - timedelta(days=10), affected_count=120)
        self.assertEqual([c["key"] for c in clocks], ["hipaa_individuals", "hipaa_hhs"])
        ind = by_key(clocks, "hipaa_individuals")
        self.assertEqual((ind["window_days"], ind["days_remaining"], ind["state"]),
                         (60, 50, "running"))
        # <500: HHS annual log — due 60d after the calendar year of discovery
        hhs = by_key(clocks, "hipaa_hhs")
        self.assertIsNone(hhs["window_days"])
        self.assertIn("2027-03-01", hhs["due_at"])
        self.assertEqual(hhs["state"], "running")

    def test_unknown_count_treated_as_small(self):
        clocks = self._clocks(firm_aware_at=NOW, affected_count=None)
        self.assertEqual([c["key"] for c in clocks], ["hipaa_individuals", "hipaa_hhs"])

    def test_covered_entity_large_breach(self):
        clocks = self._clocks(firm_aware_at=NOW - timedelta(days=61), affected_count=500)
        self.assertEqual([c["key"] for c in clocks],
                         ["hipaa_individuals", "hipaa_hhs", "hipaa_media"])
        for c in clocks:
            self.assertEqual(c["state"], "overdue", c["key"])
            self.assertEqual(c["window_days"], 60, c["key"])

    def test_business_associate_single_ce_clock(self):
        clocks = self._clocks(firm_aware_at=NOW - timedelta(days=3),
                              hipaa_role="business_associate", affected_count=900)
        self.assertEqual([c["key"] for c in clocks], ["hipaa_ce"])
        self.assertEqual(clocks[0]["days_remaining"], 57)

    def test_stamps_stop_individual_clocks_independently(self):
        clocks = self._clocks(firm_aware_at=NOW - timedelta(days=10), affected_count=600,
                              individuals_notified_at=NOW - timedelta(days=1))
        self.assertEqual(by_key(clocks, "hipaa_individuals")["state"], "notified")
        self.assertEqual(by_key(clocks, "hipaa_hhs")["state"], "running")
        self.assertEqual(by_key(clocks, "hipaa_media")["state"], "running")


class TestMultiRegime(unittest.TestCase):

    def test_all_three_regimes_canonical_order(self):
        clocks = compute_notification_clocks(
            incident(firm_aware_at=NOW - timedelta(days=5),
                     regimes=["hipaa", "reg_sp", "eu_ai_act"],
                     eu_incident_class="widespread", affected_count=1000), now=NOW)
        self.assertEqual([c["key"] for c in clocks],
                         ["customer_notice", "eu_authority",
                          "hipaa_individuals", "hipaa_hhs", "hipaa_media"])
        self.assertEqual(by_key(clocks, "eu_authority")["state"], "overdue")
        self.assertEqual(by_key(clocks, "customer_notice")["state"], "running")

    def test_no_aware_date_runs_without_due(self):
        clocks = compute_notification_clocks(
            incident(regimes=["eu_ai_act", "hipaa"]), now=NOW)
        for c in clocks:
            self.assertEqual(c["state"], "running", c["key"])
            self.assertIsNone(c["due_at"], c["key"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
