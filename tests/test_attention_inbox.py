"""
Attention inbox (backlog 57) and tool-change evidence (backlog 57a).

The inbox is DERIVED: /api/attention aggregates live from the tables that
already hold pending work, so these tests seed those tables directly and
assert three things: the counts are right, the role shaping is right (member
sees only their own items, auditor adds review work, admin sees everything),
and nothing crosses an org boundary.

57a: changing an agent's tool list must append org_compliance_log evidence,
because until now the highest-consequence capability change was unrecorded.

Requires local MySQL. Run:  venv/bin/python tests/test_attention_inbox.py
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


class AttentionTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.org = str(uuid.uuid4())
        self.other_org = str(uuid.uuid4())
        self.member = new_user(f"att_member_{suffix}", org_id=self.org, role='member')
        self.auditor = new_user(f"att_auditor_{suffix}", org_id=self.org, role='auditor')
        self.admin = new_user(f"att_admin_{suffix}", org_id=self.org, role='admin')
        self.other_admin = new_user(f"att_oadmin_{suffix}", org_id=self.other_org, role='admin')
        self.users = [self.member, self.auditor, self.admin, self.other_admin]
        self.kb_id = str(uuid.uuid4())
        self.doc_id = str(uuid.uuid4())
        self.inv_id = str(uuid.uuid4())
        self.inc_id = str(uuid.uuid4())
        self.sched_id = str(uuid.uuid4())
        self.msg_pk = int(uuid.uuid4().int % 2_000_000_000)

        # One pending item in every source, all in org A.
        _exec("INSERT INTO knowledge_bases (id, name, created_by, org_id, visibility) "
              "VALUES (%s, 'Attention KB', %s, %s, 'member')",
              (self.kb_id, self.admin, self.org))
        _exec("INSERT INTO knowledge_base_documents (id, kb_id, filename, uploaded_by, status) "
              "VALUES (%s, %s, 'handbook.pdf', %s, 'pending')",
              (self.doc_id, self.kb_id, self.member))
        _exec("INSERT INTO review_queue (org_id, message_pk, message_id, conversation_id, "
              "profile_name, triggers, status) VALUES (%s, %s, %s, %s, 'tutor', '[\"low_score\"]', 'pending')",
              (self.org, self.msg_pk, str(uuid.uuid4()), str(uuid.uuid4())))
        _exec("INSERT INTO org_invitations (id, org_id, email, role, invited_by, expires_at) "
              "VALUES (%s, %s, 'new.person@example.test', 'member', %s, NOW() + INTERVAL 7 DAY)",
              (self.inv_id, self.org, self.admin))
        _exec("INSERT INTO security_incidents (id, org_id, title, status, severity, firm_aware_at) "
              "VALUES (%s, %s, 'Test incident', 'open', 'high', NOW())",
              (self.inc_id, self.org))
        _exec("INSERT INTO scheduled_tasks (id, user_id, agent_key, prompt, time_of_day, "
              "days, timezone, enabled, last_run_date, last_status) "
              "VALUES (%s, %s, 'tutor', 'digest', '08:00', '0', 'UTC', 1, '2026-08-17', "
              "'error: turn failed')",
              (self.sched_id, self.member))

    def tearDown(self):
        _exec("DELETE FROM knowledge_base_documents WHERE id=%s", (self.doc_id,))
        _exec("DELETE FROM knowledge_bases WHERE id=%s", (self.kb_id,))
        _exec("DELETE FROM review_queue WHERE message_pk=%s", (self.msg_pk,))
        _exec("DELETE FROM org_invitations WHERE id=%s", (self.inv_id,))
        _exec("DELETE FROM security_incidents WHERE id=%s", (self.inc_id,))
        _exec("DELETE FROM scheduled_tasks WHERE id=%s", (self.sched_id,))
        _exec("DELETE FROM org_compliance_log WHERE org_id IN (%s,%s)",
              (self.org, self.other_org))
        for uid in self.users:
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))

    def _get(self, user_id, role):
        client = self.app.test_client()
        org = self.other_org if user_id == self.other_admin else self.org
        login_as(client, user_id, role, org_id=org)
        r = client.get('/api/attention')
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def _keys(self, payload):
        return {i['key'] for i in payload['items']}


class RoleShaping(AttentionTestBase):

    def test_unauthenticated_is_401(self):
        r = self.app.test_client().get('/api/attention')
        self.assertEqual(r.status_code, 401)

    def test_member_sees_only_their_own_failures(self):
        payload = self._get(self.member, 'member')
        self.assertEqual(self._keys(payload), {'schedules'})
        self.assertEqual(payload['total'], 1)
        item = payload['items'][0]
        self.assertEqual(item['target'], 'schedules')
        self.assertTrue(any('tutor' in x for x in item['examples']))

    def test_auditor_adds_review_work_but_not_admin_items(self):
        payload = self._get(self.auditor, 'auditor')
        self.assertEqual(self._keys(payload), {'kb_documents', 'review_queue'})

    def test_admin_sees_everything_in_their_org(self):
        payload = self._get(self.admin, 'admin')
        self.assertEqual(self._keys(payload),
                         {'kb_documents', 'review_queue', 'invitations', 'incidents'})
        by_key = {i['key']: i for i in payload['items']}
        self.assertEqual(by_key['invitations']['count'], 1)
        self.assertIn('new.person@example.test', by_key['invitations']['examples'])
        self.assertTrue(any('handbook.pdf' in x for x in by_key['kb_documents']['examples']))
        self.assertIsNotNone(by_key['review_queue']['oldest'])

    def test_nothing_crosses_the_org_boundary(self):
        payload = self._get(self.other_admin, 'admin')
        self.assertEqual(payload['items'], [])
        self.assertEqual(payload['total'], 0)

    def test_resolved_work_leaves_the_inbox(self):
        _exec("UPDATE review_queue SET status='approved' WHERE message_pk=%s", (self.msg_pk,))
        _exec("UPDATE knowledge_base_documents SET status='approved' WHERE id=%s", (self.doc_id,))
        _exec("UPDATE security_incidents SET status='closed' WHERE id=%s", (self.inc_id,))
        _exec("UPDATE org_invitations SET accepted_at=NOW() WHERE id=%s", (self.inv_id,))
        payload = self._get(self.admin, 'admin')
        self.assertEqual(payload['items'], [],
                         "a derived inbox must empty itself the moment the work is done")


class ToolChangeEvidence(AttentionTestBase):
    """57a: the tool list is the capability boundary; changing it must leave
    org_compliance_log evidence naming the actor and the delta."""

    def test_tool_removal_via_api_is_recorded(self):
        agent_key = f"att_agent_{uuid.uuid4().hex[:8]}"
        db.create_agent(
            key=agent_key, name='Evidence Agent', description='t', avatar='',
            worldview='', style='', values=[], rules=[], policy_id='test_policy',
            created_by=self.admin, org_id=self.org, visibility='private',
            tools=['send_email'])
        try:
            client = self.app.test_client()
            login_as(client, self.admin, 'admin', org_id=self.org)
            r = client.put('/api/agents', json={
                "key": agent_key, "name": "Evidence Agent",
                "policy_id": "test_policy", "tools": []})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

            events = db.list_compliance_log(self.org, limit=10)
            tool_events = [e for e in events if e['event_type'] == 'agent_tools_changed']
            self.assertEqual(len(tool_events), 1)
            import json as _json
            detail = tool_events[0]['detail']
            if isinstance(detail, str):
                detail = _json.loads(detail)
            self.assertEqual(detail['agent'], agent_key)
            self.assertEqual(detail['removed'], ['send_email'])
            self.assertEqual(detail['added'], [])
        finally:
            _exec("DELETE FROM agents WHERE agent_key=%s", (agent_key,))

    def test_saving_without_tool_change_logs_nothing(self):
        agent_key = f"att_agent_{uuid.uuid4().hex[:8]}"
        db.create_agent(
            key=agent_key, name='Quiet Agent', description='t', avatar='',
            worldview='', style='', values=[], rules=[], policy_id='test_policy',
            created_by=self.admin, org_id=self.org, visibility='private')
        try:
            client = self.app.test_client()
            login_as(client, self.admin, 'admin', org_id=self.org)
            r = client.put('/api/agents', json={
                "key": agent_key, "name": "Quiet Agent renamed",
                "policy_id": "test_policy", "tools": []})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            events = db.list_compliance_log(self.org, limit=10)
            self.assertFalse(
                [e for e in events if e['event_type'] == 'agent_tools_changed'],
                "an unchanged tool list must not spam the evidence log")
        finally:
            _exec("DELETE FROM agents WHERE agent_key=%s", (agent_key,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
