"""
API tests for the human review queue (Phase E2, review_api.py), via the Flask
test client with forged sessions. Covers the reviewer set-check (admin|auditor,
editor excluded), approve/override dispositions riding the chat_audit_trail
hash chain, mandatory override reason, config evidence-logging, the coverage
report, and the alerts surface.

Requires local MySQL. Run:  venv/bin/python tests/test_review_api.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import crypto
from safi_app.core.services import provider_governance


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


class TestReviewApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"revapi_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Review API Test Org')", (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'Rev Test', %s, 'admin')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        db.set_org_review_config(cls.org_id, {"enabled": True, "random_sample_pct": 0},
                                 f"{cls.uid}@example.test")
        provider_governance.activate_org(cls.org_id)

        # Three governed turns: low-alignment (sampled), hard-gate redirect
        # (sampled), clean (not sampled).
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'review api test')",
              (cls.cid, cls.uid))
        cls.mid_low = cls._turn("REVAPI low alignment prompt",
                                "REVAPI low alignment answer",
                                score=3, will_decision="approve", will_stage="spirit")
        cls.mid_gate = cls._turn("REVAPI gated prompt",
                                 "REVAPI persona redirect text",
                                 score=None, drift=None,
                                 will_decision="redirected", will_stage="hard_gate")
        cls.mid_clean = cls._turn("REVAPI clean prompt", "REVAPI clean answer",
                                  score=9, will_decision="approve", will_stage="spirit")
        provider_governance.activate_org(None)

    @classmethod
    def _turn(cls, prompt, answer, score, drift=0.1, will_decision=None, will_stage=None):
        mid = str(uuid.uuid4())
        assert db.insert_turn_atomic(cls.cid, prompt, mid)
        db.update_message_content(mid, answer, audit_status="complete")
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], score,
                                "test note", "test_agent", ["honesty"], drift=drift,
                                policy_id="pol-rev", policy_version=2,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision=will_decision, will_stage=will_stage)
        return mid

    @classmethod
    def tearDownClass(cls):
        provider_governance.activate_org(None)
        for sql, params in [
            ("DELETE FROM review_queue WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM review_alerts WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM chat_history WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM conversations WHERE id=%s", (cls.cid,)),
            ("DELETE FROM users WHERE id=%s", (cls.uid,)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)

    def client(self, role="auditor", org_id=None):
        c = self.app.test_client()
        with c.session_transaction() as sess:
            sess["user"] = {"id": self.uid, "email": f"{self.uid}@example.test",
                            "role": role, "org_id": org_id or self.org_id}
        return c

    def _queue_id(self, mid):
        res = self.client().get(f"/api/organizations/{self.org_id}/review/queue?limit=200")
        for item in json.loads(res.data)["items"]:
            if item["message_id"] == mid:
                return item["id"]
        return None

    # -- access control ------------------------------------------------------

    def test_01_reviewer_set_check(self):
        url = f"/api/organizations/{self.org_id}/review/queue"
        self.assertEqual(self.client(role="member").get(url).status_code, 403)
        self.assertEqual(self.client(role="editor").get(url).status_code, 403,
                         "editor outranks auditor in the hierarchy but must NOT review")
        self.assertEqual(self.client(role="auditor").get(url).status_code, 200)
        self.assertEqual(self.client(role="admin").get(url).status_code, 200)
        # cross-org: session org differs from the path org
        other = self.client(role="admin", org_id=str(uuid.uuid4()))
        self.assertEqual(other.get(url).status_code, 403)

    def test_02_list_and_filters(self):
        c = self.client()
        base = f"/api/organizations/{self.org_id}/review/queue"
        doc = json.loads(c.get(base).data)
        self.assertEqual(doc["total"], 2, "low-alignment + hard-gate sampled; clean turn not")
        mids = {i["message_id"] for i in doc["items"]}
        self.assertEqual(mids, {self.mid_low, self.mid_gate})
        for item in doc["items"]:
            self.assertNotIn("reason_enc", item)
        doc = json.loads(c.get(f"{base}?trigger=hard_gate_block").data)
        self.assertEqual([i["message_id"] for i in doc["items"]], [self.mid_gate])
        self.assertEqual(c.get(f"{base}?status=bogus").status_code, 400)
        self.assertEqual(c.get(f"{base}?trigger=bogus").status_code, 400)

    # -- detail ---------------------------------------------------------------

    def test_03_detail_decrypts_turn_and_verifies_chain(self):
        qid = self._queue_id(self.mid_low)
        res = self.client().get(f"/api/organizations/{self.org_id}/review/queue/{qid}")
        self.assertEqual(res.status_code, 200)
        doc = json.loads(res.data)
        self.assertEqual(doc["user_prompt"], "REVAPI low alignment prompt")
        self.assertEqual(doc["turn"]["content"], "REVAPI low alignment answer")
        self.assertEqual(doc["turn"]["will_decision"], "approve")
        self.assertEqual(doc["turn"]["will_stage"], "spirit")
        self.assertEqual(doc["turn"]["spirit_score"], 3)
        self.assertTrue(doc["chain"]["valid"])
        self.assertEqual(doc["review_history"], [])
        self.assertIn("low_alignment", doc["queue"]["triggers"])
        # unknown id in this org → 404
        res = self.client().get(f"/api/organizations/{self.org_id}/review/queue/999999999")
        self.assertEqual(res.status_code, 404)

    # -- dispositions ---------------------------------------------------------

    def test_04_approve_appends_chained_review_evidence(self):
        qid = self._queue_id(self.mid_low)
        res = self.client(role="auditor").post(
            f"/api/organizations/{self.org_id}/review/queue/{qid}/action",
            json={"action": "approve"})
        self.assertEqual(res.status_code, 200)
        item = json.loads(res.data)["item"]
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["reviewer_email"], f"{self.uid}@example.test")
        trail = _fetchall("SELECT * FROM chat_audit_trail WHERE message_id=%s AND action='review'",
                          (self.mid_low,))
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0]["actor"], f"user:{self.uid}")
        state = json.loads(trail[0]["state"])
        self.assertEqual(state["disposition"], "approved")
        self.assertEqual(state["queue_id"], qid)
        self.assertEqual(state["policy_id"], "pol-rev")
        self.assertTrue(db.verify_message_audit_trail(trail[0]["message_pk"])["valid"],
                        "review entry must extend the hash chain, not break it")

    def test_05_disposition_is_one_shot(self):
        qid = self._queue_id(self.mid_low)  # approved in test_04
        res = self.client().post(
            f"/api/organizations/{self.org_id}/review/queue/{qid}/action",
            json={"action": "override", "reason": "second thoughts"})
        self.assertEqual(res.status_code, 409)

    def test_06_override_requires_reason_and_round_trips_encrypted(self):
        qid = self._queue_id(self.mid_gate)
        url = f"/api/organizations/{self.org_id}/review/queue/{qid}/action"
        self.assertEqual(self.client().post(url, json={"action": "override"}).status_code, 400)
        self.assertEqual(self.client().post(url, json={"action": "override", "reason": "  "}).status_code, 400)
        self.assertEqual(self.client().post(url, json={"action": "bogus"}).status_code, 400)
        reason = "REVAPI gate fired correctly but the redirect copy needs work"
        res = self.client().post(url, json={"action": "override", "reason": reason})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(json.loads(res.data)["item"]["status"], "overridden")
        # reason decrypts in the detail view and in review_history
        doc = json.loads(self.client().get(
            f"/api/organizations/{self.org_id}/review/queue/{qid}").data)
        self.assertEqual(doc["queue"]["reason"], reason)
        self.assertEqual(doc["review_history"][0]["disposition"], "overridden")
        self.assertEqual(doc["review_history"][0]["reason"], reason)
        self.assertTrue(doc["chain"]["valid"])
        # at rest the reason is ciphertext (when encryption is configured)
        if crypto.is_enabled():
            rows = _fetchall("SELECT reason_enc FROM review_queue WHERE id=%s", (qid,))
            self.assertNotIn(reason, rows[0]["reason_enc"])
            trail = _fetchall("SELECT state FROM chat_audit_trail WHERE message_id=%s AND action='review'",
                              (self.mid_gate,))
            self.assertNotIn(reason, trail[0]["state"])

    def test_07_editor_cannot_act(self):
        qid = self._queue_id(self.mid_gate)
        res = self.client(role="editor").post(
            f"/api/organizations/{self.org_id}/review/queue/{qid}/action",
            json={"action": "approve"})
        self.assertEqual(res.status_code, 403)

    # -- config ---------------------------------------------------------------

    def test_08_config_get_reviewer_put_admin_only(self):
        base = f"/api/organizations/{self.org_id}/review/config"
        doc = json.loads(self.client(role="auditor").get(base).data)
        self.assertTrue(doc["enabled"])
        self.assertEqual(self.client(role="auditor").put(base, json={"enabled": False}).status_code, 403)
        self.assertEqual(self.client(role="admin").put(base, json={"random_sample_pct": 200}).status_code, 400)
        res = self.client(role="admin").put(base, json={"triggers": {"alignment_threshold": 7}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(json.loads(res.data)["triggers"]["alignment_threshold"], 7)
        events = [e["event_type"] for e in db.list_compliance_log(self.org_id, 20)]
        self.assertIn("review_config_changed", events)

    # -- coverage report ------------------------------------------------------

    def test_09_report_counts_and_csv_custody(self):
        res = self.client().get(f"/api/organizations/{self.org_id}/review/report")
        self.assertEqual(res.status_code, 200)
        rep = json.loads(res.data)
        self.assertEqual(rep["total_turns"], 3, "all three governed turns count in the denominator")
        self.assertEqual(rep["sampled"], 2)
        self.assertEqual(rep["dispositions"]["approved"], 1)
        self.assertEqual(rep["dispositions"]["overridden"], 1)
        self.assertEqual(rep["dispositions"]["pending"], 0)
        self.assertEqual(rep["trigger_counts"]["low_alignment"], 1)
        self.assertEqual(rep["trigger_counts"]["hard_gate_block"], 1)
        self.assertIsNotNone(rep["median_review_latency_seconds"])
        self.assertEqual(rep["per_reviewer"][f"{self.uid}@example.test"], 2)
        self.assertEqual(rep["purged_message_rows"], 0)
        # JSON read leaves no custody entry; CSV download logs one
        before = [e for e in db.list_compliance_log(self.org_id, 50)
                  if e["event_type"] == "review_report_exported"]
        self.assertEqual(before, [])
        res = self.client().get(f"/api/organizations/{self.org_id}/review/report?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        after = [e for e in db.list_compliance_log(self.org_id, 50)
                 if e["event_type"] == "review_report_exported"]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["detail"]["counts"]["sampled"], 2)

    # -- alerts ---------------------------------------------------------------

    def test_10_alerts_surface(self):
        base = f"/api/organizations/{self.org_id}/review/alerts"
        doc = json.loads(self.client().get(base).data)
        self.assertEqual(doc["alerts"], [])
        _exec("INSERT INTO review_alerts (org_id, alert_type, detail, delivered) "
              "VALUES (%s, 'drift_spike', %s, %s)",
              (self.org_id, json.dumps({"drift": 0.6, "threshold": 0.4}),
               json.dumps({"webhook": "unconfigured"})))
        doc = json.loads(self.client().get(base).data)
        self.assertEqual(len(doc["alerts"]), 1)
        self.assertEqual(doc["alerts"][0]["alert_type"], "drift_spike")
        self.assertEqual(doc["alerts"][0]["detail"]["drift"], 0.6)
        self.assertEqual(self.client(role="member").get(base).status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
