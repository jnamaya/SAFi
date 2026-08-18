"""
Policy-content approval (backlog 57f): IT writes policies, legal activates
them.

The assertions that matter: the policies row keeps the APPROVED content
while a change is pending (the compiler reads that row, so this is the whole
enforcement), tool widenings still route to the TOOL approvers separately, a
designated policy-approver group replaces the admin|auditor fallback, SoD
and the sole-approver non-independence carry over, and both the submission
and the outcome reach the requester's inbox.

Requires local MySQL. Run:  venv/bin/python tests/test_policy_approval.py
"""
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import sharing_store
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


class PolicyApprovalBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        tool_approval_store.init_schema()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.org = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Policy Approval Org')",
              (self.org,))
        self.editor = new_user(f"pa_editor_{suffix}", org_id=self.org, role='editor')
        self.admin = new_user(f"pa_admin_{suffix}", org_id=self.org, role='admin')
        self.auditor = new_user(f"pa_auditor_{suffix}", org_id=self.org, role='auditor')
        self.member = new_user(f"pa_member_{suffix}", org_id=self.org, role='member')
        self.users = [self.editor, self.admin, self.auditor, self.member]
        self.policy_id = f"pa_policy_{suffix}"
        db.create_policy(
            name="Original Name", worldview="Original worldview",
            will_rules={"allowed_tools": []}, values=[],
            created_by=self.editor, org_id=self.org, policy_id=self.policy_id)

    def tearDown(self):
        _exec("DELETE FROM policy_versions WHERE policy_id=%s", (self.policy_id,))
        _exec("DELETE FROM api_keys WHERE policy_id=%s", (self.policy_id,))
        _exec("DELETE FROM policies WHERE id=%s", (self.policy_id,))
        _exec("DELETE FROM policy_change_requests WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM agent_tool_requests WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM approval_settings WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM custom_groups WHERE org_id=%s", (self.org,))
        _exec("DELETE m FROM group_memberships m LEFT JOIN custom_groups c "
              "ON c.id = m.group_id WHERE c.id IS NULL")
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org,))
        _exec("DELETE FROM organizations WHERE id=%s", (self.org,))
        for uid in self.users:
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))

    def _client(self, user_id, role):
        client = self.app.test_client()
        login_as(client, user_id, role, org_id=self.org)
        return client

    def _submit(self, client, **fields):
        payload = {"name": "Original Name"}
        payload.update(fields)
        return client.put(f'/api/policies/{self.policy_id}', json=payload)

    def _row(self):
        return db.get_policy(self.policy_id)

    def _events(self, event_type):
        return [e for e in db.list_compliance_log(self.org, limit=50)
                if e['event_type'] == event_type]

    def _inbox_item(self, client, key):
        payload = client.get('/api/attention').get_json()
        return next((i for i in payload['items'] if i['key'] == key), None)


class TheHold(PolicyApprovalBase):

    def test_content_change_is_held_not_applied(self):
        client = self._client(self.editor, 'editor')
        r = self._submit(client, worldview="Rewritten worldview")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertTrue(body['pending_approval'])
        self.assertIn('worldview', body['changed'])
        self.assertEqual(self._row()['worldview'], "Original worldview",
                         "the approved row changed without approval")
        self.assertEqual(len(tool_approval_store.list_policy_changes(self.org, 'pending')), 1)
        self.assertEqual(len(self._events('policy_change_requested')), 1)

    def test_identical_save_files_no_request(self):
        client = self._client(self.editor, 'editor')
        r = self._submit(client, worldview="Original worldview")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()['pending_approval'])
        self.assertEqual(tool_approval_store.list_policy_changes(self.org, 'pending'), [])

    def test_tool_widening_and_content_change_route_separately(self):
        client = self._client(self.editor, 'editor')
        r = self._submit(client, name="New Name",
                         will_rules={"allowed_tools": ["send_email"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual(body['tools_pending_approval'], ['send_email'])
        self.assertTrue(body['pending_approval'])
        self.assertNotIn('will_rules', body['changed'],
                         "the tool widening leaked into the content diff")
        row = self._row()
        self.assertEqual(row['name'], "Original Name")
        self.assertEqual(row['will_rules'].get('allowed_tools'), [])
        self.assertEqual(len(tool_approval_store.list_requests(self.org, 'pending')), 1)
        self.assertEqual(len(tool_approval_store.list_policy_changes(self.org, 'pending')), 1)

    def test_newer_submission_supersedes(self):
        client = self._client(self.editor, 'editor')
        self._submit(client, worldview="Draft one")
        self._submit(client, worldview="Draft two")
        pending = tool_approval_store.list_policy_changes(self.org, 'pending')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['payload']['worldview'], "Draft two")

    def test_create_stays_immediate(self):
        client = self._client(self.editor, 'editor')
        r = client.post('/api/policies', json={"name": f"fresh {uuid.uuid4().hex[:6]}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        body = r.get_json()
        self.assertFalse(body.get('pending_approval'))
        _exec("DELETE FROM api_keys WHERE policy_id=%s", (body['policy_id'],))
        _exec("DELETE FROM policies WHERE id=%s", (body['policy_id'],))


class TheActivation(PolicyApprovalBase):

    def _file(self, **fields):
        self._submit(self._client(self.editor, 'editor'), **fields)
        return tool_approval_store.list_policy_changes(self.org, 'pending')[0]['id']

    def test_approval_applies_and_versions(self):
        before_version = self._row().get('version')
        rid = self._file(worldview="Approved worldview")
        r = self._client(self.admin, 'admin').post(f'/api/policies/change-requests/{rid}/approve')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        row = self._row()
        self.assertEqual(row['worldview'], "Approved worldview")
        self.assertEqual(row.get('version'), (before_version or 1) + 1)
        self.assertEqual(len(self._events('policy_change_approved')), 1)
        self.assertFalse(r.get_json()['self_approved'])

    def test_reject_leaves_the_row_alone(self):
        rid = self._file(worldview="Should never land")
        r = self._client(self.auditor, 'auditor').post(
            f'/api/policies/change-requests/{rid}/reject', json={"reason": "too vague"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._row()['worldview'], "Original worldview")
        self.assertEqual(len(self._events('policy_change_rejected')), 1)

    def test_author_may_withdraw(self):
        rid = self._file(worldview="Changed my mind")
        r = self._client(self.editor, 'editor').post(
            f'/api/policies/change-requests/{rid}/reject', json={})
        self.assertEqual(r.status_code, 200)

    def test_author_cannot_activate_their_own_change(self):
        # The admin submits (admins clear the editor ladder) with the auditor
        # available as another fallback reviewer.
        self._submit(self._client(self.admin, 'admin'), worldview="Admin's edit")
        rid = tool_approval_store.list_policy_changes(self.org, 'pending')[0]['id']
        r = self._client(self.admin, 'admin').post(f'/api/policies/change-requests/{rid}/approve')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._row()['worldview'], "Original worldview")

    def test_sole_reviewer_self_activates_non_independent(self):
        _exec("UPDATE users SET role='member' WHERE id=%s", (self.auditor,))
        self._submit(self._client(self.admin, 'admin'), worldview="Sole admin edit")
        rid = tool_approval_store.list_policy_changes(self.org, 'pending')[0]['id']
        r = self._client(self.admin, 'admin').post(f'/api/policies/change-requests/{rid}/approve')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['self_approved'])

    def test_member_is_not_a_policy_reviewer(self):
        rid = self._file(worldview="x")
        client = self._client(self.member, 'member')
        self.assertEqual(client.get('/api/policies/change-requests').status_code, 403)
        self.assertEqual(client.post(f'/api/policies/change-requests/{rid}/approve').status_code, 403)


class NamedPolicyApprovers(PolicyApprovalBase):

    def _designate_policy_group(self, member_ids, name="Legal"):
        gid = sharing_store.create_group(self.org, name, self.admin)
        for uid in member_ids:
            sharing_store.add_group_member(gid, uid, self.admin)
        r = self._client(self.admin, 'admin').put('/api/policies/policy-approvers',
                                                  json={"group_id": gid})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return gid

    def _file(self):
        self._submit(self._client(self.editor, 'editor'), worldview="Needs legal")
        return tool_approval_store.list_policy_changes(self.org, 'pending')[0]['id']

    def test_legal_member_activates_and_admin_cannot(self):
        self._designate_policy_group([self.member])
        rid = self._file()
        member = self._client(self.member, 'member')
        self.assertIsNotNone(self._inbox_item(member, 'policy_changes'),
                             "the designated policy approver never saw the change")
        self.assertEqual(member.post(f'/api/policies/change-requests/{rid}/approve').status_code, 200)
        self.assertEqual(self._row()['worldview'], "Needs legal")
        r = self._client(self.admin, 'admin').get('/api/policies/change-requests')
        self.assertEqual(r.status_code, 403)
        events = {e['event_type'] for e in db.list_compliance_log(self.org, limit=50)}
        self.assertIn('policy_approvers_changed', events)

    def test_the_two_designations_are_independent(self):
        # A TOOL approver group must confer nothing over POLICY changes.
        gid = sharing_store.create_group(self.org, "AI Committee", self.admin)
        sharing_store.add_group_member(gid, self.member, self.admin)
        r = self._client(self.admin, 'admin').put('/api/agents/tool-approvers',
                                                  json={"group_id": gid})
        self.assertEqual(r.status_code, 200)
        rid = self._file()
        member = self._client(self.member, 'member')
        self.assertEqual(member.post(f'/api/policies/change-requests/{rid}/approve').status_code, 403)
        # And the fallback still holds for policy changes.
        self.assertEqual(self._client(self.auditor, 'auditor')
                         .post(f'/api/policies/change-requests/{rid}/approve').status_code, 200)


class RequesterVisibility(PolicyApprovalBase):

    def test_submission_then_outcome_then_dismiss(self):
        editor = self._client(self.editor, 'editor')
        self._submit(editor, worldview="Visible lifecycle")
        item = self._inbox_item(editor, 'my_pending_requests')
        self.assertIsNotNone(item)
        self.assertTrue(any('Policy' in x for x in item['examples']))

        rid = tool_approval_store.list_policy_changes(self.org, 'pending')[0]['id']
        self._client(self.admin, 'admin').post(f'/api/policies/change-requests/{rid}/approve')
        self.assertIsNone(self._inbox_item(editor, 'my_pending_requests'))
        outcome = self._inbox_item(editor, 'my_tool_requests')
        self.assertIsNotNone(outcome)
        self.assertTrue(any('approved' in x for x in outcome['examples']))

        r = editor.post('/api/agents/tool-requests/acknowledge')
        self.assertEqual(r.get_json()['cleared'], 1)
        self.assertIsNone(self._inbox_item(editor, 'my_tool_requests'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
