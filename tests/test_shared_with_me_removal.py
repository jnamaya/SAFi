"""
Grantee-side "remove from shared with me" (DELETE /conversations/shared-with-me/<id>
and DELETE /projects/shared-with-me/<id>).

Distinct from the owner's revoke routes: no ownership check, only the
caller's own direct user grant is touched. Group grants and folder-derived
access are reported via `still_shared`, never removed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence import conversation_sharing_store, sharing_store
from support import login_as, new_user


class SharedWithMeRemovalTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        if not self._tables_ready():
            self.skipTest("sharing tables unavailable")
        self.org = f"test_org_{__import__('uuid').uuid4().hex[:12]}"
        self.owner = new_user(org_id=self.org, role="editor")
        self.member = new_user(org_id=self.org, role="member")
        self._cleanup = []

    @staticmethod
    def _tables_ready():
        try:
            conn = db.get_db_connection()
            cur = conn.cursor()
            cur.execute("SHOW TABLES LIKE 'conversation_visibility_grants'")
            ok = cur.fetchone() is not None
            cur.close()
            conn.close()
            return ok
        except Exception:
            return False

    def _new_conversation(self, user_id):
        row = db.create_conversation(user_id)
        cid = row["id"]
        self._cleanup.append(("conversation", cid))
        return cid

    def _new_project(self, user_id, name="Shared folder"):
        row = db.create_project(user_id, name)
        pid = row["id"]
        self._cleanup.append(("project", pid))
        return pid

    def tearDown(self):
        for kind, rid in self._cleanup:
            try:
                if kind == "conversation":
                    db.delete_conversation(rid)
                else:
                    db.delete_project(rid, self.owner)
            except Exception:
                pass
        for uid in (self.owner, self.member):
            try:
                db.delete_user(uid)
            except Exception:
                pass

    # -- conversations -----------------------------------------------------

    def test_grantee_can_remove_direct_conversation_share(self):
        cid = self._new_conversation(self.owner)
        conversation_sharing_store.set_conversation_grant(
            cid, "user", self.member, "viewer", self.org, self.owner)
        login_as(self.client, self.member, "member", org_id=self.org)
        resp = self.client.delete(f"/api/conversations/shared-with-me/{cid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["removed"])
        self.assertIsNone(body["still_shared"])
        self.assertIsNone(conversation_sharing_store.get_conversation_role(
            self.member, self.org, cid, self.owner))

    def test_group_share_is_reported_not_removed(self):
        cid = self._new_conversation(self.owner)
        gid = sharing_store.create_group(self.org, "removal-group", self.owner)
        sharing_store.add_group_member(gid, self.member, self.owner)
        conversation_sharing_store.set_conversation_grant(
            cid, "group", gid, "viewer", self.org, self.owner)
        login_as(self.client, self.member, "member", org_id=self.org)
        resp = self.client.delete(f"/api/conversations/shared-with-me/{cid}")
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["still_shared"], "group")
        # The group grant is intact — removal is not the member's to make.
        self.assertIsNotNone(conversation_sharing_store.get_conversation_role(
            self.member, self.org, cid, self.owner))

    # -- projects ----------------------------------------------------------

    def test_grantee_can_remove_direct_project_share(self):
        pid = self._new_project(self.owner)
        conversation_sharing_store.set_project_grant(
            pid, "user", self.member, "viewer", self.org, self.owner)
        login_as(self.client, self.member, "member", org_id=self.org)
        resp = self.client.delete(f"/api/projects/shared-with-me/{pid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["removed"])
        self.assertIsNone(body["still_shared"])
        self.assertIsNone(conversation_sharing_store.get_project_role(
            self.member, self.org, pid, self.owner))

    def test_owner_revoke_route_still_owner_only(self):
        # The pre-existing owner route must NOT accept a grantee calling it.
        cid = self._new_conversation(self.owner)
        conversation_sharing_store.set_conversation_grant(
            cid, "user", self.member, "viewer", self.org, self.owner)
        login_as(self.client, self.member, "member", org_id=self.org)
        resp = self.client.delete(
            f"/api/conversations/{cid}/shares/user/{self.member}")
        self.assertIn(resp.status_code, (403, 404))


if __name__ == "__main__":
    unittest.main()
