import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.api import auth as auth_api

from support import new_user


def _verify_domain(org_id, domain):
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE organizations SET domain_to_verify=%s, domain_verified=TRUE WHERE id=%s",
                    (domain, org_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _set_join_policy(org_id, policy):
    db.set_org_identity_config(org_id, {"join_policy": policy}, "user:test-admin")


class InvitationVersusVerifiedDomain(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.owner_domain = f"owner{tag}.example"
        self.other_domain = f"other{tag}.example"
        self.org_owner = db.create_organization(f"Domain Owner {tag}")
        self.org_other = db.create_organization(f"Other Org {tag}")
        _verify_domain(self.org_owner, self.owner_domain)
        _verify_domain(self.org_other, self.other_domain)
        self.actor = "user:test-admin"

    def tearDown(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            for oid in (self.org_owner, self.org_other):
                cur.execute("DELETE FROM org_invitations WHERE org_id=%s", (oid,))
                cur.execute("DELETE FROM auth_events WHERE org_id=%s", (oid,))
                cur.execute("UPDATE users SET org_id=NULL WHERE org_id=%s", (oid,))
                cur.execute("DELETE FROM organizations WHERE id=%s", (oid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()


    def test_cannot_invite_into_another_orgs_verified_domain(self):
        with self.assertRaises(ValueError) as ctx:
            db.create_org_invitation(self.org_other, f"alice@{self.owner_domain}",
                                     "member", self.actor)
        self.assertIn("another organization", str(ctx.exception).lower())

    def test_domain_owner_may_invite_its_own_domain(self):
        inv = db.create_org_invitation(self.org_owner, f"bob@{self.owner_domain}",
                                       "member", self.actor)
        self.assertEqual(inv["org_id"], self.org_owner)
        self.assertFalse(inv["external_domain"], "own verified domain is not external")

    def test_contractor_on_an_unclaimed_domain_is_still_allowed(self):
        inv = db.create_org_invitation(self.org_other, "consultant@unclaimed-vendor.example",
                                       "member", self.actor)
        self.assertEqual(inv["org_id"], self.org_other)
        self.assertTrue(inv["external_domain"], "off-domain invites stay flagged in evidence")

    def test_own_domain_invite_is_not_flagged_external(self):
        inv = db.create_org_invitation(self.org_other, f"staff@{self.other_domain}",
                                       "member", self.actor)
        self.assertFalse(inv["external_domain"])


    def _resolve(self, email):
        uid = f"invtest-{uuid.uuid4().hex[:8]}"
        new_user(user_id=uid, email=email)
        details = {"id": uid, "email": email}
        with self.app.app_context():
            auth_api._resolve_membership(details, idp="test")
        return uid, details

    def _force_invite(self, org_id, email, role="member"):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO org_invitations (id, org_id, email, role, invited_by, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 14 DAY))",
                (str(uuid.uuid4()), org_id, email.lower(), role, self.actor),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def test_predating_cross_domain_invite_loses_to_the_domain_owner(self):
        _set_join_policy(self.org_owner, "domain_auto_join")
        email = f"carol@{self.owner_domain}"
        self._force_invite(self.org_other, email, role="admin")

        uid, details = self._resolve(email)

        self.assertEqual(details.get("org_id"), self.org_owner,
                         "the org that verified the domain must win")
        self.assertNotEqual(details.get("org_id"), self.org_other,
                            "an outside invite must not capture a domain owner's user")
        self.assertEqual(details.get("role"), "member",
                         "the outside invite's admin role must not be honored")

    def test_declined_invite_is_journaled(self):
        _set_join_policy(self.org_owner, "domain_auto_join")
        email = f"dave@{self.owner_domain}"
        self._force_invite(self.org_other, email)
        self._resolve(email)

        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT event FROM auth_events WHERE org_id=%s AND event=%s",
                        (self.org_other, 'invite_declined_domain_owned'))
            self.assertIsNotNone(cur.fetchone(),
                                 "dropping an invitation must leave evidence")
        finally:
            cur.close()
            conn.close()

    def test_invite_only_domain_owner_leaves_the_user_org_less(self):
        _set_join_policy(self.org_owner, "invite_only")
        email = f"erin@{self.owner_domain}"
        self._force_invite(self.org_other, email)

        uid, details = self._resolve(email)

        self.assertIsNone(details.get("org_id"),
                          "better org-less than placed in a tenant the domain owner did not authorize")

    def test_domain_owners_own_invite_is_still_accepted(self):
        _set_join_policy(self.org_owner, "invite_only")
        email = f"frank@{self.owner_domain}"
        self._force_invite(self.org_owner, email, role="editor")

        uid, details = self._resolve(email)

        self.assertEqual(details.get("org_id"), self.org_owner)
        self.assertEqual(details.get("role"), "editor")

    def test_contractor_invite_on_unclaimed_domain_still_joins_the_inviter(self):
        email = f"grace@unclaimed-{uuid.uuid4().hex[:6]}.example"
        self._force_invite(self.org_other, email, role="member")

        uid, details = self._resolve(email)

        self.assertEqual(details.get("org_id"), self.org_other,
                         "no domain owner means the invitation stands")


if __name__ == "__main__":
    unittest.main()
