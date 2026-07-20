"""
DB integration tests for the security-incident registry (Reg S-P 248.30).

Requires local MySQL. Uses a throwaway org, cleaned up in tearDownClass via
raw SQL (there is deliberately no delete helper for incidents).

Run:  venv/bin/python tests/test_incident_registry.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

ACTOR = ("admin-1", "admin@example.test")


class TestIncidentRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.other_org = str(uuid.uuid4())
        cls.iids = []

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        for org in (cls.org_id, cls.other_org):
            cur.execute("DELETE FROM incident_events WHERE org_id=%s", (org,))
            cur.execute("DELETE FROM security_incidents WHERE org_id=%s", (org,))
        conn.commit()
        cur.close()
        conn.close()

    def _create(self, **overrides):
        data = {"title": "Test incident", "firm_aware_at": "2026-07-10 09:00:00",
                "severity": "high", "description": "unit test"}
        data.update(overrides)
        iid = db.create_security_incident(self.org_id, data, *ACTOR)
        self.iids.append(iid)
        return iid

    def test_create_writes_created_event(self):
        iid = self._create()
        events = db.list_incident_events(self.org_id, iid)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "created")
        self.assertEqual(events[0]["actor_email"], ACTOR[1])
        row = db.get_security_incident(self.org_id, iid)
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["created_by"], ACTOR[0])

    def test_update_produces_exact_diff(self):
        iid = self._create()
        updated = db.update_security_incident(
            self.org_id, iid, {"severity": "critical", "containment_notes": "isolated host"}, *ACTOR)
        self.assertEqual(updated["severity"], "critical")
        events = db.list_incident_events(self.org_id, iid)
        self.assertEqual(events[-1]["event_type"], "updated")
        diff = events[-1]["changes"]
        self.assertEqual(diff["severity"]["from"], "high")
        self.assertEqual(diff["severity"]["to"], "critical")
        self.assertEqual(diff["containment_notes"]["to"], "isolated host")
        self.assertNotIn("title", diff)  # unchanged fields not in diff

    def test_noop_update_writes_no_event(self):
        iid = self._create()
        before = len(db.list_incident_events(self.org_id, iid))
        db.update_security_incident(self.org_id, iid, {"severity": "high"}, *ACTOR)
        self.assertEqual(len(db.list_incident_events(self.org_id, iid)), before)

    def test_status_change_typed_event(self):
        iid = self._create()
        db.update_security_incident(self.org_id, iid, {"status": "assessing"}, *ACTOR)
        events = db.list_incident_events(self.org_id, iid)
        self.assertEqual(events[-1]["event_type"], "status_changed")

    def test_harm_determination_server_stamped(self):
        iid = self._create()
        row = db.update_security_incident(
            self.org_id, iid, {"harm_determination": "no_substantial_harm",
                               "harm_assessment": "PII was encrypted at rest"}, *ACTOR)
        self.assertEqual(row["harm_determined_by"], ACTOR[1])
        self.assertIsNotNone(row["harm_determined_at"])
        events = db.list_incident_events(self.org_id, iid)
        self.assertEqual(events[-1]["event_type"], "harm_determination")

    def test_notification_sent_stamps_timestamp_once(self):
        iid = self._create()
        self.assertTrue(db.append_incident_event(
            self.org_id, iid, "notification_sent", "Notices mailed to 120 customers", *ACTOR))
        row = db.get_security_incident(self.org_id, iid)
        first_stamp = row["customers_notified_at"]
        self.assertIsNotNone(first_stamp)
        # Second notification event does not move the first-notice timestamp
        db.append_incident_event(self.org_id, iid, "notification_sent", "Follow-up batch", *ACTOR)
        row2 = db.get_security_incident(self.org_id, iid)
        self.assertEqual(row2["customers_notified_at"], first_stamp)

    def test_org_scoping(self):
        iid = self._create()
        self.assertIsNone(db.get_security_incident(self.other_org, iid))
        self.assertIsNone(db.update_security_incident(self.other_org, iid, {"severity": "low"}, *ACTOR))
        self.assertFalse(db.append_incident_event(self.other_org, iid, "note", "sneaky", *ACTOR))
        self.assertEqual(db.list_incident_events(self.other_org, iid), [])
        titles = [r["id"] for r in db.list_security_incidents(self.other_org)]
        self.assertNotIn(iid, titles)

    def test_json_columns_round_trip(self):
        iid = self._create(data_types=["email", "chat_content"],
                           affected_user_ids=["u1", "u2"])
        row = db.get_security_incident(self.org_id, iid)
        self.assertEqual(row["data_types"], ["email", "chat_content"])
        self.assertEqual(row["affected_user_ids"], ["u1", "u2"])

    def test_events_ordered(self):
        iid = self._create()
        db.append_incident_event(self.org_id, iid, "assessment", "scope: 3 users", *ACTOR)
        db.append_incident_event(self.org_id, iid, "containment", "tokens revoked", *ACTOR)
        events = db.list_incident_events(self.org_id, iid)
        self.assertEqual([e["event_type"] for e in events],
                         ["created", "assessment", "containment"])
        ids = [e["id"] for e in events]
        self.assertEqual(ids, sorted(ids))

    # --- Phase D: regime tags + per-regime notice stamps -------------------

    def test_regime_fields_round_trip(self):
        iid = self._create(regimes=["reg_sp", "hipaa"], hipaa_role="business_associate",
                           affected_count=42, eu_incident_class=None)
        row = db.get_security_incident(self.org_id, iid)
        self.assertEqual(row["regimes"], ["reg_sp", "hipaa"])
        self.assertEqual(row["hipaa_role"], "business_associate")
        self.assertEqual(row["affected_count"], 42)

    def test_regime_update_diffed(self):
        iid = self._create(regimes=["reg_sp"])
        db.update_security_incident(self.org_id, iid,
                                    {"regimes": ["reg_sp", "eu_ai_act"],
                                     "eu_incident_class": "widespread"}, *ACTOR)
        events = db.list_incident_events(self.org_id, iid)
        diff = events[-1]["changes"]
        self.assertIn("regimes", diff)
        self.assertEqual(diff["eu_incident_class"]["to"], "widespread")

    def test_regime_notice_events_stamp_their_own_columns(self):
        iid = self._create(regimes=["eu_ai_act", "hipaa"], affected_count=600)
        db.append_incident_event(self.org_id, iid, "authority_notified",
                                 "Reported to market surveillance authority", *ACTOR)
        row = db.get_security_incident(self.org_id, iid)
        self.assertIsNotNone(row["authority_notified_at"])
        self.assertIsNone(row["individuals_notified_at"])
        self.assertIsNone(row["customers_notified_at"])
        db.append_incident_event(self.org_id, iid, "hhs_notified", "HHS portal filing", *ACTOR)
        row = db.get_security_incident(self.org_id, iid)
        self.assertIsNotNone(row["hhs_notified_at"])
        first = row["authority_notified_at"]
        # Re-notifying does not move the first stamp
        db.append_incident_event(self.org_id, iid, "authority_notified", "follow-up", *ACTOR)
        self.assertEqual(db.get_security_incident(self.org_id, iid)["authority_notified_at"], first)

    def test_note_event_stamps_nothing(self):
        iid = self._create(regimes=["hipaa"])
        db.append_incident_event(self.org_id, iid, "note", "just a note", *ACTOR)
        row = db.get_security_incident(self.org_id, iid)
        for col in ("customers_notified_at", "authority_notified_at",
                    "individuals_notified_at", "hhs_notified_at",
                    "media_notified_at", "ce_notified_at"):
            self.assertIsNone(row[col], col)


class TestOrgIncidentRegimes(unittest.TestCase):
    """Org-level default regime set (organizations.settings.incident_regimes)."""

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)",
                    (cls.org_id, "regime-test-org"))
        conn.commit()
        cur.close()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,))
        cur.execute("DELETE FROM organizations WHERE id=%s", (cls.org_id,))
        conn.commit()
        cur.close()
        conn.close()

    def test_default_is_reg_sp(self):
        self.assertEqual(db.get_org_incident_regimes(self.org_id), ["reg_sp"])

    def test_set_canonicalizes_and_evidence_logs(self):
        out = db.set_org_incident_regimes(self.org_id, ["hipaa", "reg_sp"], ACTOR[1])
        self.assertEqual(out["regimes"], ["reg_sp", "hipaa"])  # canonical order
        self.assertEqual(db.get_org_incident_regimes(self.org_id), ["reg_sp", "hipaa"])
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM org_compliance_log WHERE org_id=%s "
                    "AND event_type='incident_regimes_changed'", (self.org_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor"], ACTOR[1])

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            db.set_org_incident_regimes(self.org_id, [], ACTOR[1])
        with self.assertRaises(ValueError):
            db.set_org_incident_regimes(self.org_id, ["gdpr"], ACTOR[1])
        with self.assertRaises(ValueError):
            db.set_org_incident_regimes(str(uuid.uuid4()), ["reg_sp"], ACTOR[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
