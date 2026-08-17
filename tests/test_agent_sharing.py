"""
Scoped agent sharing (backlog 55) and use-path enforcement (backlog 55b).

The load-bearing assertion is the 55b regression: before this feature, the
visibility ladder gated LISTING only. PUT /me/profile wrote active_profile
with no validation and the chat path trusted it, so any authenticated user
could converse with any private agent in any org by key. These tests pin the
door shut at both entry points, then cover the widening half: grants to users
and to groups, org scoping, revocation, group deletion, and offboarding
cleanup.

Requires local MySQL. Run:  venv/bin/python tests/test_agent_sharing.py
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import sharing_store
from support import login_as, new_user


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _make_agent(key, created_by, org_id, visibility='private'):
    db.create_agent(
        key=key, name=key.replace('_', ' ').title(), description='t', avatar='',
        worldview='', style='', values=[], rules=[], policy_id='standalone',
        created_by=created_by, org_id=org_id, visibility=visibility)


class SharingTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        sharing_store.init_schema()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.org = str(uuid.uuid4())
        self.other_org = str(uuid.uuid4())
        self.owner = new_user(f"share_owner_{suffix}", org_id=self.org, role='editor')
        self.member = new_user(f"share_member_{suffix}", org_id=self.org, role='member')
        self.admin = new_user(f"share_admin_{suffix}", org_id=self.org, role='admin')
        self.outsider = new_user(f"share_out_{suffix}", org_id=self.other_org, role='member')
        self.agent_key = f"shared_agent_{suffix}"
        _make_agent(self.agent_key, self.owner, self.org, visibility='private')
        self.users = [self.owner, self.member, self.admin, self.outsider]

    def tearDown(self):
        _exec("DELETE FROM agents WHERE agent_key=%s", (self.agent_key,))
        _exec("DELETE FROM agent_visibility_grants WHERE agent_key=%s", (self.agent_key,))
        _exec("DELETE FROM custom_groups WHERE org_id IN (%s,%s)", (self.org, self.other_org))
        _exec("DELETE FROM group_memberships WHERE user_id IN (%s,%s,%s,%s)", tuple(self.users))
        for uid in self.users:
            _exec("DELETE FROM sessions WHERE user_id=%s", (uid,))
            _exec("DELETE FROM conversations WHERE user_id=%s", (uid,))
            _exec("DELETE FROM scheduled_tasks WHERE user_id=%s", (uid,))
            _exec("DELETE FROM prompt_usage WHERE user_id=%s", (uid,))
            _exec("DELETE FROM users WHERE id=%s", (uid,))
        _exec("DELETE FROM org_compliance_log WHERE org_id IN (%s,%s)",
              (self.org, self.other_org))


class TheResolver(SharingTestBase):

    def _agent(self):
        return db.get_agent(self.agent_key)

    def test_default_deny(self):
        self.assertFalse(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()))

    def test_owner_always(self):
        self.assertTrue(sharing_store.can_use_agent(
            self.owner, 'editor', self.org, self._agent()))

    def test_org_admin_clears_private(self):
        self.assertTrue(sharing_store.can_use_agent(
            self.admin, 'admin', self.org, self._agent()))

    def test_foreign_org_admin_denied(self):
        self.assertFalse(sharing_store.can_use_agent(
            self.outsider, 'admin', self.other_org, self._agent()))

    def test_ladder_still_works(self):
        _exec("UPDATE agents SET visibility='member' WHERE agent_key=%s", (self.agent_key,))
        self.assertTrue(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()))

    def test_direct_grant_widens(self):
        sharing_store.set_grant(self.agent_key, 'user', self.member, self.org, self.owner)
        self.assertTrue(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()))
        sharing_store.revoke_grant(self.agent_key, 'user', self.member)
        self.assertFalse(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()))

    def test_group_grant_widens_and_dies_with_the_group(self):
        gid = sharing_store.create_group(self.org, "Finance", self.admin)
        sharing_store.add_group_member(gid, self.member, self.admin)
        sharing_store.set_grant(self.agent_key, 'group', gid, self.org, self.owner)
        self.assertTrue(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()))
        sharing_store.delete_group(gid)
        self.assertFalse(sharing_store.can_use_agent(
            self.member, 'member', self.org, self._agent()),
            "a deleted group kept conferring access through orphaned rows")

    def test_grant_never_crosses_orgs(self):
        # Even a directly inserted cross-org grant row must not resolve:
        # the resolver re-asserts the org scope on read.
        _exec("INSERT INTO agent_visibility_grants "
              "(agent_key, grantee_type, grantee_id, org_id) VALUES (%s,'user',%s,%s)",
              (self.agent_key, self.outsider, self.other_org))
        self.assertFalse(sharing_store.can_use_agent(
            self.outsider, 'member', self.other_org, self._agent()))

    def test_offboarding_cleanup(self):
        gid = sharing_store.create_group(self.org, "Ops", self.admin)
        sharing_store.add_group_member(gid, self.member, self.admin)
        sharing_store.set_grant(self.agent_key, 'user', self.member, self.org, self.owner)
        sharing_store.remove_user_from_org_sharing(self.member, self.org)
        self.assertFalse(sharing_store.has_grant(self.agent_key, self.member, self.org))
        self.assertEqual(sharing_store.list_group_members(gid), [])


class UsePathEnforcement(SharingTestBase):
    """The 55b regression tests: knowing a key is not access."""

    def test_profile_switch_denied_without_access(self):
        client = self.app.test_client()
        login_as(client, self.outsider, 'member', org_id=self.other_org)
        r = client.put('/api/me/profile', json={"profile": self.agent_key})
        self.assertEqual(r.status_code, 403)

    def test_profile_switch_rejects_unknown_agent(self):
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.put('/api/me/profile', json={"profile": "no_such_agent_xyz"})
        self.assertEqual(r.status_code, 404)

    def test_profile_switch_allowed_with_grant(self):
        sharing_store.set_grant(self.agent_key, 'user', self.member, self.org, self.owner)
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.put('/api/me/profile', json={"profile": self.agent_key})
        self.assertEqual(r.status_code, 200)

    def test_chat_turn_denied_after_revoke(self):
        """A stored active_profile must not outlive the grant: the chat path
        re-resolves on every turn, 403s, and heals the stored selection."""
        sharing_store.set_grant(self.agent_key, 'user', self.member, self.org, self.owner)
        db.update_user_profile(self.member, self.agent_key)
        sharing_store.revoke_grant(self.agent_key, 'user', self.member)

        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.post('/api/process_prompt',
                        json={"message": "hi", "conversation_id": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 403)
        self.assertEqual((r.get_json() or {}).get('code'), 'AGENT_ACCESS_DENIED')
        healed = (db.get_user_details(self.member) or {}).get('active_profile')
        self.assertNotEqual(healed, self.agent_key)

    def test_schedule_creation_denied_without_access(self):
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.post('/api/schedules', json={
            "agent_key": self.agent_key, "prompt": "digest",
            "time_of_day": "08:00", "days": [0], "timezone": "UTC"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("access", (r.get_json() or {}).get("error", "").lower())


class PickerUnion(SharingTestBase):

    def test_granted_agent_appears_in_both_pickers(self):
        sharing_store.set_grant(self.agent_key, 'user', self.member, self.org, self.owner)
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)

        r = client.get('/api/agents/all')
        keys = {a.get('key') for a in (r.get_json() or {}).get('available', [])}
        self.assertIn(self.agent_key, keys)

        r = client.get('/api/profiles')
        keys = {a.get('key') for a in (r.get_json() or {}).get('available', [])}
        self.assertIn(self.agent_key, keys)

    def test_unshared_private_agent_stays_hidden(self):
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.get('/api/agents/all')
        keys = {a.get('key') for a in (r.get_json() or {}).get('available', [])}
        self.assertNotIn(self.agent_key, keys)


class ShareAndGroupApi(SharingTestBase):

    def test_owner_can_share_and_revoke(self):
        client = self.app.test_client()
        login_as(client, self.owner, 'editor', org_id=self.org)
        r = client.post(f'/api/agents/{self.agent_key}/share',
                        json={"grantee_type": "user", "grantee_id": self.member})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(sharing_store.has_grant(self.agent_key, self.member, self.org))

        r = client.delete(f'/api/agents/{self.agent_key}/share/user/{self.member}')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(sharing_store.has_grant(self.agent_key, self.member, self.org))

    def test_non_owner_cannot_share(self):
        client = self.app.test_client()
        login_as(client, self.member, 'member', org_id=self.org)
        r = client.post(f'/api/agents/{self.agent_key}/share',
                        json={"grantee_type": "user", "grantee_id": self.member})
        self.assertEqual(r.status_code, 403)

    def test_cannot_grant_to_foreign_org_user(self):
        client = self.app.test_client()
        login_as(client, self.owner, 'editor', org_id=self.org)
        r = client.post(f'/api/agents/{self.agent_key}/share',
                        json={"grantee_type": "user", "grantee_id": self.outsider})
        self.assertEqual(r.status_code, 400)

    def test_can_edit_is_refused(self):
        client = self.app.test_client()
        login_as(client, self.owner, 'editor', org_id=self.org)
        r = client.post(f'/api/agents/{self.agent_key}/share',
                        json={"grantee_type": "user", "grantee_id": self.member,
                              "permission_level": "can_edit"})
        self.assertEqual(r.status_code, 400)

    def test_group_management_is_admin_only(self):
        client = self.app.test_client()
        login_as(client, self.owner, 'editor', org_id=self.org)
        self.assertEqual(client.get('/api/groups').status_code, 403)
        self.assertEqual(client.post('/api/groups', json={"name": "X"}).status_code, 403)

    def test_group_crud_and_evidence(self):
        client = self.app.test_client()
        login_as(client, self.admin, 'admin', org_id=self.org)
        r = client.post('/api/groups', json={"name": "Finance"})
        self.assertEqual(r.status_code, 201)
        gid = r.get_json()['id']

        r = client.post(f'/api/groups/{gid}/members', json={"user_id": self.member})
        self.assertEqual(r.status_code, 200)
        r = client.post(f'/api/groups/{gid}/members', json={"user_id": self.outsider})
        self.assertEqual(r.status_code, 400, "foreign org user must be refused")

        r = client.get(f'/api/groups/{gid}/members')
        self.assertEqual([m['user_id'] for m in r.get_json()['members']], [self.member])

        self.assertEqual(client.delete(f'/api/groups/{gid}').status_code, 200)

        events = {e['event_type'] for e in db.list_compliance_log(self.org, limit=20)}
        for expected in ('group_created', 'group_member_added', 'group_deleted'):
            self.assertIn(expected, events)

    def test_share_leaves_evidence(self):
        client = self.app.test_client()
        login_as(client, self.owner, 'editor', org_id=self.org)
        client.post(f'/api/agents/{self.agent_key}/share',
                    json={"grantee_type": "user", "grantee_id": self.member})
        client.delete(f'/api/agents/{self.agent_key}/share/user/{self.member}')
        events = {e['event_type'] for e in db.list_compliance_log(self.org, limit=20)}
        self.assertIn('agent_share_granted', events)
        self.assertIn('agent_share_revoked', events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
