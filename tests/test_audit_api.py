"""
API tests for the native Audit Hub (audit_api.py, N2), via the Flask test
client with forged sessions. Covers the observer set-check (admin|editor|
auditor, member excluded), org scoping, metric parity with the Streamlit
definitions (alignment over approved turns only, overall = clip(align −
drift×10, 1, 10), flagged = score<6 OR drift>0.4), prompt search under the
decrypt-scan cap, drill-down decryption + chain verification, and the
custody-logged export.

Requires local MySQL. Run:  venv/bin/python tests/test_audit_api.py
"""
import hashlib
import json
import sys
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.core.services import provider_governance
from support import login_as


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


def _record(prompt, output, decision, reason, score, drift, model="test/model-1"):
    return {
        "timestamp": "2026-07-21T00:00:00+00:00",
        "userPrompt": prompt,
        "intellectDraft": output,
        "intellectReflection": "reflection text",
        "finalOutput": output,
        "willDecision": decision,
        "willReason": reason,
        "conscienceLedger": [{"value": "honesty", "score": 1}],
        "spiritScore": score,
        "spiritNote": "note",
        "drift": drift,
        "memorySummary": "",
        "recentTurns": "",
        "spiritFeedback": "",
        "retrievedContext": "",
        "userId": "audit-api-user",
        "agentName": "audit_test_agent",
        "intellectModel": model,
    }


class TestAuditApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.other_org = str(uuid.uuid4())
        cls.uid = f"auditapi_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Audit API Test Org')", (cls.org_id,))
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Audit API Other Org')", (cls.other_org,))
        _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'Audit Test', %s, 'admin')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'audit api test')",
              (cls.cid, cls.uid))
        provider_governance.activate_org(cls.org_id)
        # Four turns: clean approve, flagged approve (low score + high drift),
        # redirect (quality 7, no drift), violation (unscored).
        cls.mid_clean = cls._turn("AUDITAPI unique clean prompt xyzzy", "clean answer",
                                  score=9, drift=0.1, decision="approve", stage=None,
                                  reason="alignment_within_threshold")
        cls.mid_flag = cls._turn("AUDITAPI flagged prompt", "flagged answer",
                                 score=3, drift=0.5, decision="approve", stage="spirit",
                                 reason="low_alignment_score")
        cls.mid_redir = cls._turn("AUDITAPI redirected prompt", "redirect text",
                                  score=7, drift=None, decision="redirected", stage="hard_gate",
                                  reason="hard_gate_violation")
        cls.mid_viol = cls._turn("AUDITAPI violation prompt", "blocked text",
                                 score=None, drift=None, decision="violation", stage="phase_zero",
                                 reason="injection:persona_hijack")
        provider_governance.activate_org(None)

    @classmethod
    def _turn(cls, prompt, answer, score, drift, decision, stage, reason):
        mid = str(uuid.uuid4())
        assert db.insert_turn_atomic(cls.cid, prompt, mid)
        db.update_message_content(mid, answer, audit_status="complete")
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], score,
                                "test note", "audit_test_agent", ["honesty"], drift=drift,
                                policy_id="pol-audit", policy_version=3,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision=decision, will_stage=stage,
                                governance_record=_record(prompt, answer, decision,
                                                          reason, score, drift))
        return mid

    @classmethod
    def tearDownClass(cls):
        provider_governance.activate_org(None)
        for sql, params in [
            ("DELETE FROM review_queue WHERE org_id=%s", (cls.org_id,)),
            # No FK by design — sweep the org's test records explicitly.
            ("DELETE FROM governance_records WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM chat_history WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM conversations WHERE id=%s", (cls.cid,)),
            ("DELETE FROM users WHERE id=%s", (cls.uid,)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.other_org,)),
        ]:
            _exec(sql, params)

    def client(self, role="auditor", org_id=None):
        c = self.app.test_client()
        login_as(c, self.uid, role, org_id or self.org_id)
        return c

    def _pk(self, mid):
        return _fetchall("SELECT message_pk FROM governance_records WHERE message_id=%s",
                         (mid,))[0]["message_pk"]

    # -- access control ------------------------------------------------------

    def test_01_observer_set_check(self):
        url = f"/api/organizations/{self.org_id}/audit/summary"
        self.assertEqual(self.client(role="member").get(url).status_code, 403)
        for role in ("admin", "editor", "auditor"):
            self.assertEqual(self.client(role=role).get(url).status_code, 200,
                             f"{role} must see the observe surface")

    def test_02_org_scoping_403(self):
        url = f"/api/organizations/{self.org_id}/audit/summary"
        res = self.client(role="admin", org_id=self.other_org).get(url)
        self.assertEqual(res.status_code, 403)

    # -- filters ---------------------------------------------------------------

    def test_03_filters_reflect_actual_records(self):
        res = self.client().get(f"/api/organizations/{self.org_id}/audit/filters")
        data = json.loads(res.data)
        self.assertIn("audit_test_agent", data["profiles"])
        self.assertIn("pol-audit", data["policies"])

    # -- summary metric parity -------------------------------------------------

    def test_04_summary_metrics_ported_exactly(self):
        res = self.client().get(f"/api/organizations/{self.org_id}/audit/summary")
        s = json.loads(res.data)
        self.assertEqual(s["total_audits"], 4)
        # Alignment over APPROVED turns only: (9 + 3) / 2
        self.assertAlmostEqual(s["avg_alignment"], 6.0)
        # Redirect quality reported separately, never pooled
        self.assertAlmostEqual(s["avg_redirect_quality"], 7.0)
        # Drift over scored turns: (0.1 + 0.5) / 2 = 0.3 → consistency 70%
        self.assertAlmostEqual(s["avg_consistency"], 70.0)
        # Overall = clip(6.0 − 0.3×10, 1, 10) = 3.0
        self.assertAlmostEqual(s["overall_score"], 3.0)
        self.assertEqual(s["interventions"], 1)
        self.assertAlmostEqual(s["intervention_rate"], 25.0)
        self.assertEqual(s["violations"], 1)
        self.assertEqual(s["flagged"], 1)

    def test_05_summary_empty_window_is_null_not_default(self):
        res = self.client().get(
            f"/api/organizations/{self.org_id}/audit/summary"
            f"?from=2020-01-01T00:00:00&to=2020-01-02T00:00:00")
        s = json.loads(res.data)
        self.assertEqual(s["total_audits"], 0)
        self.assertIsNone(s["overall_score"])
        self.assertIsNone(s["avg_alignment"])
        self.assertIsNone(s["avg_consistency"])
        self.assertIsNone(s["intervention_rate"])

    # -- trend -----------------------------------------------------------------

    def test_06_trend_buckets(self):
        res = self.client().get(f"/api/organizations/{self.org_id}/audit/trend?bucket=day")
        buckets = json.loads(res.data)["buckets"]
        self.assertEqual(len(buckets), 1)
        b = buckets[0]
        self.assertEqual(b["turns"], 4)
        self.assertEqual(b["scored_turns"], 2)
        self.assertAlmostEqual(b["avg_drift"], 0.3)
        self.assertAlmostEqual(b["avg_consistency"], 70.0)

    # -- explorer --------------------------------------------------------------

    def test_07_events_list_and_filters(self):
        base = f"/api/organizations/{self.org_id}/audit/events"
        all_items = json.loads(self.client().get(base).data)
        self.assertEqual(all_items["total"], 4)
        # No decrypted content on the list path
        self.assertNotIn("record_enc", all_items["items"][0])
        self.assertNotIn("prompt_preview", all_items["items"][0])
        for flt, expected_mids in (
            ("flagged", {self.mid_flag}),
            ("approved", {self.mid_clean, self.mid_flag}),
            ("redirected", {self.mid_redir}),
            ("violation", {self.mid_viol}),
        ):
            data = json.loads(self.client().get(f"{base}?filter={flt}").data)
            self.assertEqual({i["message_id"] for i in data["items"]}, expected_mids,
                             f"filter={flt}")

    def test_08_prompt_search_decrypt_scan(self):
        base = f"/api/organizations/{self.org_id}/audit/events"
        data = json.loads(self.client().get(f"{base}?q=xyzzy").data)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["message_id"], self.mid_clean)
        self.assertIn("xyzzy", data["items"][0]["prompt_preview"])
        self.assertEqual(data["window"], 4)

    def test_09_search_cap_returns_413(self):
        with patch.object(db, "GOVERNANCE_SEARCH_CAP", 1):
            res = self.client().get(
                f"/api/organizations/{self.org_id}/audit/events?q=xyzzy")
        self.assertEqual(res.status_code, 413)

    # -- drill-down --------------------------------------------------------------

    def test_10_event_detail_decrypts_and_verifies(self):
        pk = self._pk(self.mid_redir)
        res = self.client().get(f"/api/organizations/{self.org_id}/audit/events/{pk}")
        d = json.loads(res.data)
        self.assertEqual(d["event"]["message_id"], self.mid_redir)
        self.assertEqual(d["record"]["userPrompt"], "AUDITAPI redirected prompt")
        self.assertEqual(d["record"]["willReason"], "hard_gate_violation")
        self.assertTrue(d["trail"]["valid"])
        self.assertIsNone(d["review"])
        self.assertEqual(d["chat"]["audit_status"], "complete")

    def test_11_event_detail_org_isolated(self):
        pk = self._pk(self.mid_clean)
        res = self.client(role="admin", org_id=self.other_org).get(
            f"/api/organizations/{self.other_org}/audit/events/{pk}")
        self.assertEqual(res.status_code, 404)

    # -- export ------------------------------------------------------------------

    def test_12_export_custody_logged(self):
        res = self.client().get(
            f"/api/organizations/{self.org_id}/audit/export?filter=flagged")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        payload = json.loads(res.data)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["records"][0]["record"]["userPrompt"], "AUDITAPI flagged prompt")
        ev = db.list_compliance_log(self.org_id, 5)[0]
        self.assertEqual(ev["event_type"], "audit_export")
        self.assertEqual(ev["detail"]["count"], 1)
        self.assertEqual(ev["detail"]["filters"]["filter"], "flagged")
        self.assertNotIn("records", ev["detail"], "custody log must never carry content")

    def test_13_export_cap_returns_413(self):
        with patch.object(db, "GOVERNANCE_EXPORT_CAP", 1):
            res = self.client().get(f"/api/organizations/{self.org_id}/audit/export")
        self.assertEqual(res.status_code, 413)

    def test_14_export_carries_verifiable_integrity_evidence(self):
        """This was the one export a recipient could not check at all: it shipped
        decrypted records with no entry_hash, prev_hash or chain verdict, while
        records/export and the review item export both carried them."""
        res = self.client().get(f"/api/organizations/{self.org_id}/audit/export")
        self.assertEqual(res.status_code, 200)
        body = res.data.decode("utf-8")
        payload = json.loads(body)

        # --- per record ---
        self.assertTrue(payload["records"], "fixture should export something")
        for rec in payload["records"]:
            integ = rec["integrity"]
            self.assertEqual(
                set(integ),
                {"entry_hash", "prev_hash", "chain_entries", "chain_valid",
                 "chain_first_bad_id"})
            self.assertGreater(integ["chain_entries"], 0,
                               "fixture turns all have trail entries")
            self.assertTrue(integ["chain_valid"], "untampered chain must verify")
            self.assertIsNone(integ["chain_first_bad_id"])
            # A real sha256 hex digest, not a placeholder or a truncation.
            self.assertRegex(integ["entry_hash"], r"^[0-9a-f]{64}$")

        # The exported tip must be the actual chain head in the database, not a
        # recomputation that could drift from what is stored.
        rec = payload["records"][0]
        stored = _fetchall(
            "SELECT entry_hash, prev_hash FROM chat_audit_trail "
            "WHERE message_pk=%s ORDER BY id DESC LIMIT 1", (rec["message_pk"],))
        self.assertEqual(rec["integrity"]["entry_hash"], stored[0]["entry_hash"])
        self.assertEqual(rec["integrity"]["prev_hash"], stored[0]["prev_hash"])

        # And it must agree with the canonical verifier.
        verdict = db.verify_message_audit_trail(rec["message_pk"])
        self.assertEqual(verdict["entries"], rec["integrity"]["chain_entries"])
        self.assertEqual(verdict["valid"], rec["integrity"]["chain_valid"])

        # --- document level ---
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.assertEqual(res.headers.get("X-SAFi-Export-SHA256"), digest,
                         "header digest must cover the exact bytes served")
        ev = next(e for e in db.list_compliance_log(self.org_id, 10)
                  if e["event_type"] == "audit_export")
        self.assertEqual(ev["detail"]["sha256"], digest,
                         "the custody log is the authoritative copy of the digest")
        self.assertNotIn("records", ev["detail"], "custody log must never carry content")

        # The file must state the limits of what it proves, so a reader working
        # from the artifact alone cannot overstate it.
        scope = payload["integrity"]["scope"]
        self.assertIn("not", scope.lower())
        self.assertIn("integrity evidence", scope)

    def test_15_absent_trail_is_not_reported_as_verified(self):
        """No trail rows is an absence of evidence. Reporting chain_valid=true
        there would certify exactly the records with nothing backing them."""
        pk = _fetchall("SELECT message_pk FROM governance_records WHERE org_id=%s "
                       "LIMIT 1", (self.org_id,))[0]["message_pk"]
        saved = _fetchall("SELECT * FROM chat_audit_trail WHERE message_pk=%s", (pk,))
        _exec("DELETE FROM chat_audit_trail WHERE message_pk=%s", (pk,))
        try:
            res = self.client().get(f"/api/organizations/{self.org_id}/audit/export")
            rec = next(r for r in json.loads(res.data)["records"]
                       if r["message_pk"] == pk)
            self.assertIsNone(rec["integrity"]["chain_valid"],
                              "must be null, never true, with no trail rows")
            self.assertEqual(rec["integrity"]["chain_entries"], 0)
            self.assertIsNone(rec["integrity"]["entry_hash"])
        finally:
            for e in saved:
                _exec("INSERT INTO chat_audit_trail (id, message_pk, message_id, "
                      "conversation_id, action, actor, state, event_at, prev_hash, "
                      "entry_hash, org_id, created_at) VALUES "
                      "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (e["id"], e["message_pk"], e["message_id"], e["conversation_id"],
                       e["action"], e["actor"], e["state"], e["event_at"],
                       e["prev_hash"], e["entry_hash"], e["org_id"], e["created_at"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
