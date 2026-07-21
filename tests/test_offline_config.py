"""
Tests for the per-org offline/PWA kill switch (Phase F): default-off posture,
evidence-logged toggles, admin-only endpoint with org scoping, and the
offline_enabled flag on /api/me (personal users keep offline; org members
follow their org).

Requires local MySQL. Run:  venv/bin/python tests/test_offline_config.py
"""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class TestOfflineConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.other_org = str(uuid.uuid4())
        cls.admin = f"offcfg_admin_{uuid.uuid4().hex[:8]}"
        cls.member = f"offcfg_member_{uuid.uuid4().hex[:8]}"
        cls.personal = f"offcfg_personal_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Offline Cfg Test Org')", (cls.org_id,))
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Offline Cfg Other Org')", (cls.other_org,))
        for uid, org, role in ((cls.admin, cls.org_id, 'admin'),
                               (cls.member, cls.org_id, 'member'),
                               (cls.personal, None, 'member')):
            _exec("INSERT INTO users (id, email, name, org_id, role) VALUES (%s, %s, 'Offline Test', %s, %s)",
                  (uid, f"{uid}@example.test", org, role))

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM users WHERE id IN (%s, %s, %s)", (cls.admin, cls.member, cls.personal)),
            ("DELETE FROM org_compliance_log WHERE org_id=%s", (cls.org_id,)),
            ("DELETE FROM organizations WHERE id IN (%s, %s)", (cls.org_id, cls.other_org)),
        ]:
            _exec(sql, params)

    def client(self, uid, role, org_id):
        c = self.app.test_client()
        with c.session_transaction() as sess:
            sess["user"] = {"id": uid, "email": f"{uid}@example.test",
                            "role": role, "org_id": org_id}
            sess["user_id"] = uid
        return c

    def test_01_default_is_off(self):
        self.assertFalse(db.get_org_offline_config(self.org_id)["offline_enabled"])

    def test_02_me_flags(self):
        # Org member: follows the org default (off)
        res = self.client(self.member, "member", self.org_id).get("/api/me")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(json.loads(res.data)["user"]["offline_enabled"])
        # Personal user: offline stays available
        res = self.client(self.personal, "member", None).get("/api/me")
        self.assertTrue(json.loads(res.data)["user"]["offline_enabled"])

    def test_03_toggle_is_evidence_logged(self):
        cfg = db.set_org_offline_config(self.org_id, True, "admin@example.test")
        self.assertTrue(cfg["offline_enabled"])
        ev = db.list_compliance_log(self.org_id, 5)[0]
        self.assertEqual(ev["event_type"], "offline_config_changed")
        self.assertEqual(ev["detail"], {"old": False, "new": True})
        # No-op change logs nothing
        before = len(db.list_compliance_log(self.org_id, 50))
        db.set_org_offline_config(self.org_id, True, "admin@example.test")
        self.assertEqual(len(db.list_compliance_log(self.org_id, 50)), before)
        # Member now sees offline enabled on /api/me
        res = self.client(self.member, "member", self.org_id).get("/api/me")
        self.assertTrue(json.loads(res.data)["user"]["offline_enabled"])
        db.set_org_offline_config(self.org_id, False, "admin@example.test")

    def test_04_endpoint_rbac_and_scoping(self):
        url = f"/api/organizations/{self.org_id}/offline-config"
        # member forbidden
        res = self.client(self.member, "member", self.org_id).put(url, json={"offline_enabled": True})
        self.assertEqual(res.status_code, 403)
        # admin of another org forbidden
        res = self.client(self.admin, "admin", self.other_org).put(url, json={"offline_enabled": True})
        self.assertEqual(res.status_code, 403)
        # admin of the org: works
        c = self.client(self.admin, "admin", self.org_id)
        res = c.put(url, json={"offline_enabled": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(json.loads(res.data)["offline_enabled"])
        res = c.get(url)
        self.assertTrue(json.loads(res.data)["offline_enabled"])
        res = c.put(url, json={"offline_enabled": False})
        self.assertFalse(json.loads(res.data)["offline_enabled"])
        # missing field is a 400
        res = c.put(url, json={})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
