"""
Tests for Art. 72 monitoring alerts (Phase E4, review_alerts.py): per-turn
drift_spike, rolling-mean alignment_degradation, queue_backlog, the 24h
dedup cooldown, HMAC webhook signing + delivery journaling, and the
retention-purge sweep of orphaned pending queue rows.

Requires local MySQL. Run:  venv/bin/python tests/test_review_alerts.py
"""
import hashlib
import hmac
import json
import os
import sys
import uuid
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import review_alerts

ACTOR = "alerts-admin@example.test"
PROFILE = "alerts_test_agent"


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _fetchall(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


class ReviewAlertsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.user_id = f"alerts-test-user-{uuid.uuid4()}"
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Alerts Test Org')", (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'Alerts Test', %s, 'admin')",
              (cls.user_id, f"{cls.user_id}@example.test", cls.org_id))
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'alerts test')",
              (cls.cid, cls.user_id))
        db.set_org_review_config(cls.org_id, {
            "enabled": True, "random_sample_pct": 0,
            "alerts": {"alignment_window_turns": 3, "alignment_avg_threshold": 6,
                       "backlog_max_age_days": 1},
        }, ACTOR)

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM review_alerts WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM review_queue WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM chat_history WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM conversations WHERE id=%s", (cls.cid,)),
            ("DELETE FROM users WHERE id=%s", (cls.user_id,)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)

    def setUp(self):
        _exec("DELETE FROM review_alerts WHERE org_id=%s", (self.org_id,))

    def _alerts(self, alert_type=None):
        if alert_type:
            return _fetchall("SELECT * FROM review_alerts WHERE org_id=%s AND alert_type=%s",
                             (self.org_id, alert_type))
        return _fetchall("SELECT * FROM review_alerts WHERE org_id=%s", (self.org_id,))

    def _commit_turn(self, score, drift=0.1):
        from safi_app.core.services import provider_governance
        provider_governance.activate_org(self.org_id)
        mid = str(uuid.uuid4())
        self.assertTrue(db.insert_turn_atomic(self.cid, "alerts test prompt", mid))
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], score,
                                "note", PROFILE, ["honesty"], drift=drift,
                                will_decision="approve", will_stage=None)
        provider_governance.activate_org(None)
        return mid

    # -- drift spike -----------------------------------------------------------

    def test_01_drift_spike_fires_and_dedups(self):
        review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.55, "approve", org_id=self.org_id)
        rows = self._alerts("drift_spike")
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["profile"], PROFILE)
        self.assertEqual(detail["drift"], 0.55)
        self.assertEqual(detail["threshold"], 0.4)
        self.assertEqual(json.loads(rows[0]["delivered"]), {"webhook": "unconfigured"})
        # same (org, type, profile) within cooldown → suppressed
        review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.9, "approve", org_id=self.org_id)
        self.assertEqual(len(self._alerts("drift_spike")), 1)
        # a DIFFERENT profile is its own cooldown bucket
        review_alerts.evaluate_turn_alerts("other_agent", 8, 0.9, "approve", org_id=self.org_id)
        self.assertEqual(len(self._alerts("drift_spike")), 2)

    def test_02_no_drift_alert_below_threshold_or_when_disabled(self):
        review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.2, "approve", org_id=self.org_id)
        self.assertEqual(self._alerts(), [])
        db.set_org_review_config(self.org_id, {"enabled": False}, ACTOR)
        review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.9, "approve", org_id=self.org_id)
        self.assertEqual(self._alerts(), [])
        db.set_org_review_config(self.org_id, {"enabled": True}, ACTOR)

    # -- alignment degradation -------------------------------------------------

    def test_03_degradation_needs_full_window_then_fires(self):
        self._commit_turn(3)
        self._commit_turn(4)
        # two approved turns < window of 3 → no baseline yet
        review_alerts.evaluate_turn_alerts(PROFILE, 4, 0.1, "approve", org_id=self.org_id)
        self.assertEqual(self._alerts("alignment_degradation"), [])
        self._commit_turn(5)
        review_alerts.evaluate_turn_alerts(PROFILE, 5, 0.1, "approve", org_id=self.org_id)
        rows = self._alerts("alignment_degradation")
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["observed"], 4.0)  # mean(3,4,5)
        self.assertEqual(detail["threshold"], 6)
        self.assertEqual(detail["window_turns"], 3)

    def test_04_degradation_skips_non_approved_and_healthy_means(self):
        # redirect-quality scores must not trigger the approved-mean alert
        review_alerts.evaluate_turn_alerts(PROFILE, 2, 0.1, "redirected", org_id=self.org_id)
        self.assertEqual(self._alerts("alignment_degradation"), [])
        # healthy window: 8,9,9
        for s in (8, 9, 9):
            self._commit_turn(s)
        review_alerts.evaluate_turn_alerts(PROFILE, 9, 0.1, "approve", org_id=self.org_id)
        self.assertEqual(self._alerts("alignment_degradation"), [])

    # -- queue backlog -----------------------------------------------------------

    def test_05_queue_backlog(self):
        # fresh pending row → not overdue
        _exec("INSERT INTO review_queue (org_id, message_pk, message_id, conversation_id, triggers) "
              "VALUES (%s, 999999901, %s, %s, '[\"random_sample\"]')",
              (self.org_id, str(uuid.uuid4()), self.cid))
        review_alerts.check_queue_backlog(self.org_id)
        self.assertEqual(self._alerts("queue_backlog"), [])
        # age it past backlog_max_age_days=1
        _exec("UPDATE review_queue SET created_at = NOW() - INTERVAL 3 DAY WHERE org_id=%s", (self.org_id,))
        review_alerts.check_queue_backlog(self.org_id)
        rows = self._alerts("queue_backlog")
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["oldest_days"], 3)
        self.assertEqual(detail["max_age_days"], 1)
        # dedup within cooldown
        review_alerts.check_queue_backlog(self.org_id)
        self.assertEqual(len(self._alerts("queue_backlog")), 1)
        _exec("DELETE FROM review_queue WHERE org_id=%s", (self.org_id,))

    # -- webhook dispatch ---------------------------------------------------------

    def test_06_webhook_signed_and_outcome_journaled(self):
        db.set_org_review_config(self.org_id, {"alerts": {"webhook_url": "https://example.test/hook"}}, ACTOR)
        captured = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured.update(url=url, data=data, headers=headers, timeout=timeout)
            resp = mock.Mock()
            resp.status_code = 200
            return resp

        with mock.patch.dict(os.environ, {"SAFI_WEBHOOK_SECRET": "test-secret"}):
            with mock.patch.object(review_alerts.requests, "post", side_effect=fake_post):
                review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.7, "approve", org_id=self.org_id)

        rows = self._alerts("drift_spike")
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["delivered"]), {"webhook": "ok", "signed": True})
        self.assertEqual(captured["url"], "https://example.test/hook")
        self.assertEqual(captured["timeout"], review_alerts.WEBHOOK_TIMEOUT_SECONDS)
        body = captured["data"].decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["alert_type"], "drift_spike")
        self.assertEqual(payload["org_id"], self.org_id)
        expected_sig = "sha256=" + hmac.new(b"test-secret", body.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(captured["headers"]["X-SAFi-Signature"], expected_sig)

    def test_07_webhook_failure_retries_once_and_journals(self):
        db.set_org_review_config(self.org_id, {"alerts": {"webhook_url": "https://example.test/hook"}}, ACTOR)
        calls = []

        def flaky_post(url, **kwargs):
            calls.append(url)
            raise review_alerts.requests.ConnectionError("boom")

        with mock.patch.object(review_alerts.requests, "post", side_effect=flaky_post):
            review_alerts.evaluate_turn_alerts(PROFILE, 8, 0.7, "approve", org_id=self.org_id)

        self.assertEqual(len(calls), 2, "exactly one retry")
        rows = self._alerts("drift_spike")
        self.assertEqual(len(rows), 1, "delivery failure still journals the alert")
        delivered = json.loads(rows[0]["delivered"])
        self.assertEqual(delivered["webhook"], "failed:ConnectionError")
        db.set_org_review_config(self.org_id, {"alerts": {"webhook_url": None}}, ACTOR)

    # -- purge sweep ---------------------------------------------------------------

    def test_08_orphan_sweep_removes_pending_keeps_reviewed(self):
        args = [(self.org_id, 999999911, str(uuid.uuid4()), self.cid, "pending"),
                (self.org_id, 999999912, str(uuid.uuid4()), self.cid, "approved")]
        for a in args:
            _exec("INSERT INTO review_queue (org_id, message_pk, message_id, conversation_id, triggers, status) "
                  "VALUES (%s, %s, %s, %s, '[\"random_sample\"]', %s)", a)
        removed = db.sweep_orphaned_pending_reviews(self.org_id)
        self.assertEqual(removed, 1)
        rows = _fetchall("SELECT status FROM review_queue WHERE org_id=%s", (self.org_id,))
        self.assertEqual([r["status"] for r in rows], ["approved"],
                         "reviewed orphan is the disposition's last remnant and must survive")
        _exec("DELETE FROM review_queue WHERE org_id=%s", (self.org_id,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
