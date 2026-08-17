"""
Incident lifecycle must reach the org-wide compliance log (backlog 58).

Before this, create/close/harm-determination/notice events journaled ONLY
into incident_events (the per-incident trail), so org_compliance_log, the
evidence stream an auditor reads first, had no idea an incident ever
existed. Inconsistent by inspection: changing the org's DEFAULT regimes was
evidence-logged while closing an actual incident was not.

The mirror is thin (id, title, transition) and best-effort; the incident
journal stays the authoritative detail. These tests drive the HTTP API the
way the form does and assert each transition lands in the log exactly once.

Requires local MySQL. Run:  venv/bin/python tests/test_incident_compliance_mirror.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from support import login_as, new_user


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class IncidentComplianceMirror(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.admin = new_user(f"inc_admin_{uuid.uuid4().hex[:8]}",
                              org_id=self.org, role='admin')
        self.client = self.app.test_client()
        login_as(self.client, self.admin, 'admin', org_id=self.org)

    def tearDown(self):
        _exec("DELETE FROM incident_events WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM security_incidents WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM sessions WHERE user_id=%s", (self.admin,))
        _exec("DELETE FROM users WHERE id=%s", (self.admin,))

    def _events(self, event_type):
        return [e for e in db.list_compliance_log(self.org, limit=50)
                if e['event_type'] == event_type]

    def _create(self):
        r = self.client.post(f'/api/organizations/{self.org}/incidents', json={
            "title": "Mirror test incident", "severity": "high",
            "firm_aware_at": "2026-08-01T09:00", "regimes": ["reg_sp"]})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()['id']

    def test_create_is_mirrored(self):
        self._create()
        rows = self._events('incident_created')
        self.assertEqual(len(rows), 1)

    def test_closing_is_mirrored_with_the_transition(self):
        iid = self._create()
        r = self.client.put(f'/api/organizations/{self.org}/incidents/{iid}',
                            json={"status": "closed"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rows = self._events('incident_status_changed')
        self.assertEqual(len(rows), 1)
        import json as _json
        detail = rows[0]['detail']
        if isinstance(detail, str):
            detail = _json.loads(detail)
        self.assertEqual(detail['from'], 'open')
        self.assertEqual(detail['to'], 'closed')
        self.assertEqual(detail['incident'], iid)

    def test_noop_update_mirrors_nothing(self):
        iid = self._create()
        r = self.client.put(f'/api/organizations/{self.org}/incidents/{iid}',
                            json={"severity": "high"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._events('incident_status_changed'), [])
        self.assertEqual(self._events('incident_harm_determination'), [])

    def test_harm_determination_is_mirrored(self):
        iid = self._create()
        r = self.client.put(f'/api/organizations/{self.org}/incidents/{iid}',
                            json={"harm_determination": "no_substantial_harm"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rows = self._events('incident_harm_determination')
        self.assertEqual(len(rows), 1)

    def test_regime_notice_is_mirrored(self):
        iid = self._create()
        r = self.client.post(f'/api/organizations/{self.org}/incidents/{iid}/events',
                             json={"event_type": "notification_sent",
                                   "detail": "customers emailed"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rows = self._events('incident_notice_recorded')
        self.assertEqual(len(rows), 1)
        import json as _json
        detail = rows[0]['detail']
        if isinstance(detail, str):
            detail = _json.loads(detail)
        self.assertEqual(detail['notice'], 'notification_sent')

    def test_every_mirror_names_an_actor(self):
        iid = self._create()
        self.client.put(f'/api/organizations/{self.org}/incidents/{iid}',
                        json={"status": "closed"})
        for e in db.list_compliance_log(self.org, limit=50):
            self.assertTrue(str(e.get('actor') or '').startswith('user:'),
                            f"compliance row without an actor: {e['event_type']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
