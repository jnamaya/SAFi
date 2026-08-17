"""
Tool-grant approvals (backlog 57b): widening an org agent's tool list waits
for a second person; narrowing never does.

The assertions that matter: the agent's live tool set is UNCHANGED while a
request is pending (the whole point), authors cannot approve their own
widening when another reviewer exists, the sole-reviewer exception is
recorded as non-independent rather than deadlocking, a newer request
supersedes an older pending one, and every transition leaves compliance
evidence.

Requires local MySQL. Run:  venv/bin/python tests/test_tool_approval.py
"""
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import tool_approval_store
from support import login_as, new_user

KNOWN = patch('safi_app.core.services.mcp_manager.MCPManager.known_connectors',
              MagicMock(return_value={'send_email', 'calendar'}))


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class ToolApprovalBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        tool_approval_store.init_schema()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.org = str(uuid.uuid4())
        self.editor = new_user(f"ta_editor_{suffix}", org_id=self.org, role='editor')
        self.admin = new_user(f"ta_admin_{suffix}", org_id=self.org, role='admin')
        self.auditor = new_user(f"ta_auditor_{suffix}", org_id=self.org, role='auditor')
        self.member = new_user(f"ta_member_{suffix}", org_id=self.org, role='member')
        self.users = [self.editor, self.admin, self.auditor, self.member]
        self.agent_key = f"ta_agent_{suffix}"
        db.create_agent(
            key=self.agent_key, name='Approval Agent', description='t', avatar='',
            worldview='', style='', values=[], rules=[], policy_id='test_policy',
            created_by=self.editor, org_id=self.org, visibility='private')

    def tearDown(self):
        _exec("DELETE FROM agents WHERE agent_key=%s", (self.agent_key,))
        _exec("DELETE FROM agent_tool_requests WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org,))
        for uid in self.users:
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))

    def _client(self, user_id, role):
        client = self.app.test_client()
        login_as(client, user_id, role, org_id=self.org)
        return client

    def _put_tools(self, client, tools):
        with KNOWN:
            return client.put('/api/agents', json={
                "key": self.agent_key, "name": "Approval Agent",
                "policy_id": "test_policy", "tools": tools})

    def _events(self, event_type):
        return [e for e in db.list_compliance_log(self.org, limit=50)
                if e['event_type'] == event_type]


class TheGate(ToolApprovalBase):

    def test_addition_is_held_not_applied(self):
        client = self._client(self.editor, 'editor')
        r = self._put_tools(client, ['send_email'])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual(body['tools_pending_approval'], ['send_email'])
        self.assertEqual(db.get_agent(self.agent_key).get('tools'), [],
                         "the agent's live tool set widened without approval")
        pending = tool_approval_store.list_requests(self.org, 'pending')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['added'], ['send_email'])
        self.assertEqual(len(self._events('tool_request_created')), 1)

    def test_removal_applies_immediately(self):
        tool_approval_store.apply_tools(self.agent_key, ['send_email'])
        client = self._client(self.editor, 'editor')
        r = self._put_tools(client, [])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['tools_pending_approval'], [])
        self.assertEqual(db.get_agent(self.agent_key).get('tools'), [])
        self.assertEqual(tool_approval_store.list_requests(self.org, 'pending'), [])

    def test_newer_request_supersedes_older(self):
        client = self._client(self.editor, 'editor')
        self._put_tools(client, ['send_email'])
        self._put_tools(client, ['calendar'])
        pending = tool_approval_store.list_requests(self.org, 'pending')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['added'], ['calendar'])
        self.assertEqual(len(tool_approval_store.list_requests(self.org, 'superseded')), 1)

    def test_no_org_agent_is_exempt(self):
        solo = new_user(f"ta_solo_{uuid.uuid4().hex[:8]}", org_id=None, role='editor')
        key = f"ta_solo_agent_{uuid.uuid4().hex[:8]}"
        db.create_agent(key=key, name='Solo', description='t', avatar='',
                        worldview='', style='', values=[], rules=[],
                        policy_id='test_policy', created_by=solo, org_id=None)
        try:
            client = self.app.test_client()
            login_as(client, solo, 'editor', org_id=None)
            with KNOWN:
                r = client.put('/api/agents', json={
                    "key": key, "name": "Solo", "policy_id": "test_policy",
                    "tools": ['send_email']})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(r.get_json()['tools_pending_approval'], [])
            self.assertEqual(db.get_agent(key).get('tools'), ['send_email'])
        finally:
            _exec("DELETE FROM agents WHERE agent_key=%s", (key,))
            _exec("DELETE FROM sessions WHERE user_id=%s", (solo,))
            _exec("DELETE FROM users WHERE id=%s", (solo,))


class TheReview(ToolApprovalBase):

    def _file_request(self):
        self._put_tools(self._client(self.editor, 'editor'), ['send_email'])
        return tool_approval_store.list_requests(self.org, 'pending')[0]['id']

    def test_reviewer_approval_applies_the_tools(self):
        rid = self._file_request()
        r = self._client(self.admin, 'admin').post(f'/api/agents/tool-requests/{rid}/approve')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertFalse(r.get_json()['self_approved'])
        self.assertEqual(db.get_agent(self.agent_key).get('tools'), ['send_email'])
        self.assertEqual(len(self._events('tool_request_approved')), 1)
        self.assertEqual(len(self._events('agent_tools_changed')), 1)

    def test_auditor_may_approve(self):
        rid = self._file_request()
        r = self._client(self.auditor, 'auditor').post(f'/api/agents/tool-requests/{rid}/approve')
        self.assertEqual(r.status_code, 200)

    def test_member_may_not_review(self):
        rid = self._file_request()
        client = self._client(self.member, 'member')
        self.assertEqual(client.get('/api/agents/tool-requests').status_code, 403)
        self.assertEqual(client.post(f'/api/agents/tool-requests/{rid}/approve').status_code, 403)

    def test_author_cannot_self_approve_when_another_reviewer_exists(self):
        # The admin authors a request on their own agent; the auditor exists,
        # so separation of duties holds.
        _exec("UPDATE agents SET created_by=%s WHERE agent_key=%s",
              (self.admin, self.agent_key))
        client = self._client(self.admin, 'admin')
        self._put_tools(client, ['send_email'])
        rid = tool_approval_store.list_requests(self.org, 'pending')[0]['id']
        r = client.post(f'/api/agents/tool-requests/{rid}/approve')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(db.get_agent(self.agent_key).get('tools'), [])

    def test_sole_reviewer_self_approves_as_non_independent(self):
        # Remove every other eligible reviewer, leaving the authoring admin
        # alone: the exception applies and is recorded on the row.
        _exec("UPDATE users SET role='member' WHERE id IN (%s)", (self.auditor,))
        _exec("UPDATE agents SET created_by=%s WHERE agent_key=%s",
              (self.admin, self.agent_key))
        client = self._client(self.admin, 'admin')
        self._put_tools(client, ['send_email'])
        rid = tool_approval_store.list_requests(self.org, 'pending')[0]['id']
        r = client.post(f'/api/agents/tool-requests/{rid}/approve')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['self_approved'])
        req = tool_approval_store.get_request(rid)
        self.assertTrue(req['self_approved'])

    def test_reject_leaves_tools_unchanged(self):
        rid = self._file_request()
        r = self._client(self.admin, 'admin').post(
            f'/api/agents/tool-requests/{rid}/reject', json={"reason": "not needed"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(db.get_agent(self.agent_key).get('tools'), [])
        self.assertEqual(tool_approval_store.get_request(rid)['status'], 'rejected')
        self.assertEqual(len(self._events('tool_request_rejected')), 1)

    def test_author_may_withdraw_their_own_request(self):
        rid = self._file_request()
        r = self._client(self.editor, 'editor').post(
            f'/api/agents/tool-requests/{rid}/reject', json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(tool_approval_store.get_request(rid)['status'], 'rejected')

    def test_resolved_request_cannot_be_reused(self):
        rid = self._file_request()
        admin = self._client(self.admin, 'admin')
        self.assertEqual(admin.post(f'/api/agents/tool-requests/{rid}/approve').status_code, 200)
        self.assertEqual(admin.post(f'/api/agents/tool-requests/{rid}/approve').status_code, 409)
        self.assertEqual(admin.post(f'/api/agents/tool-requests/{rid}/reject').status_code, 409)

    def test_pending_request_reaches_the_inbox(self):
        self._file_request()
        r = self._client(self.admin, 'admin').get('/api/attention')
        keys = {i['key'] for i in r.get_json()['items']}
        self.assertIn('tool_requests', keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
