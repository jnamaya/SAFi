import re
import sys
import uuid
import unittest
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.api import auth as auth_api

from support import new_user


def _auth_events(user_id, event):
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT org_id, detail FROM auth_events WHERE user_id=%s AND event=%s",
                    (user_id, event))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _drop(user_id, *org_ids):
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM auth_events WHERE user_id=%s", (user_id,))
        cur.execute("UPDATE users SET org_id=NULL WHERE id=%s", (user_id,))
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        for oid in org_ids:
            if not oid:
                continue
            cur.execute("DELETE FROM auth_events WHERE org_id=%s", (oid,))
            cur.execute("UPDATE users SET org_id=NULL WHERE org_id=%s", (oid,))
            cur.execute("UPDATE organizations SET global_policy_id=NULL WHERE id=%s", (oid,))
            cur.execute("DELETE FROM policies WHERE org_id=%s", (oid,))
            cur.execute("DELETE FROM organizations WHERE id=%s", (oid,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


class EveryLoginPathFoundsAnOrg(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(auth_api)

    def _bodies_calling(self, name):
        out = set()
        current = None
        for line in self.src.splitlines():
            m = re.match(r'^def (\w+)', line)
            if m:
                current = m.group(1)
            elif current and name in line and not line.lstrip().startswith('#'):
                out.add(current)
        return out

    def test_no_path_resolves_membership_without_founding(self):
        resolvers = self._bodies_calling('_resolve_membership(')
        resolvers.discard('_resolve_membership')
        founders = self._bodies_calling('_found_org_if_unaffiliated(')
        founders.discard('_found_org_if_unaffiliated')

        self.assertGreaterEqual(len(resolvers), 3,
                                "expected the google web, google mobile and "
                                "microsoft paths to resolve membership")
        missing = resolvers - founders
        self.assertEqual(missing, set(),
                         f"login path(s) {sorted(missing)} resolve membership but never "
                         "found an org, so an unaffiliated user finishes login with no "
                         "organization and no route out (backlog 57)")

    def test_the_founder_flow_is_not_inlined_anywhere(self):
        callers = self._bodies_calling('create_organization_atomic(')
        callers.discard('create_organization_atomic')
        self.assertEqual(
            callers, {'_resolve_single_tenant_membership', '_found_org_if_unaffiliated'},
            "org creation at login belongs to the shared helper (single-tenant mode "
            "keeps its own, which also sets org_id and journals org_founded)")


class AnUnaffiliatedUserBecomesAdminOfANewOrg(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.uid = f"founder-{self.tag}"
        new_user(user_id=self.uid, email=f"nobody@fresh{self.tag}.example",
                 name="Fresh Founder")
        self.org_id = None

    def tearDown(self):
        _drop(self.uid, self.org_id)

    def test_microsoft_signup_on_an_unclaimed_domain_founds_an_org(self):
        details = {"id": self.uid, "name": "Fresh Founder",
                   "email": f"nobody@fresh{self.tag}.example"}
        with self.app.app_context():
            auth_api._resolve_membership(details, idp="microsoft")
            self.assertIsNone(details.get("org_id"),
                              "membership resolution alone must not create an org")
            founded = auth_api._found_org_if_unaffiliated(details, idp="microsoft")

        self.assertTrue(founded)
        self.org_id = details["org_id"]
        self.assertEqual(details["role"], "admin")

        row = db.get_user_details(self.uid)
        self.assertEqual(str(row["org_id"]), str(self.org_id),
                         "the founder must not be left outside the org they founded")
        self.assertEqual(row["role"], "admin")

        events = _auth_events(self.uid, "org_founded")
        self.assertEqual(len(events), 1, "founding an org is an auth-trail event")
        self.assertEqual(str(events[0]["org_id"]), str(self.org_id))
        self.assertIn("microsoft", events[0]["detail"],
                      "the trail must say which IdP the founder came from")

    def test_a_second_call_is_a_no_op(self):
        details = {"id": self.uid, "name": "Fresh Founder"}
        with self.app.app_context():
            self.assertTrue(auth_api._found_org_if_unaffiliated(details, idp="microsoft"))
            self.org_id = details["org_id"]
            self.assertFalse(auth_api._found_org_if_unaffiliated(details, idp="microsoft"))
        self.assertEqual(len(_auth_events(self.uid, "org_founded")), 1)


class AClaimedDomainStillGetsNoShadowOrg(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.domain = f"claimed{self.tag}.example"
        self.org_owner = db.create_organization(f"Owner {self.tag}")
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE organizations SET domain_to_verify=%s, "
                        "domain_verified=TRUE WHERE id=%s", (self.domain, self.org_owner))
            conn.commit()
        finally:
            cur.close()
            conn.close()
        db.set_org_identity_config(self.org_owner, {"join_policy": "invite_only"},
                                   "user:test-admin")
        self.uid = f"newhire-{self.tag}"
        new_user(user_id=self.uid, email=f"newhire@{self.domain}")

    def tearDown(self):
        _drop(self.uid, self.org_owner)

    def test_microsoft_signup_on_a_claimed_invite_only_domain_founds_nothing(self):
        details = {"id": self.uid, "name": "New Hire",
                   "email": f"newhire@{self.domain}"}
        with self.app.app_context():
            auth_api._resolve_membership(details, idp="microsoft")
            founded = auth_api._found_org_if_unaffiliated(details, idp="microsoft")

        self.assertFalse(founded, "a claimed domain must not spawn a shadow org")
        self.assertIsNone(details.get("org_id"))
        self.assertIsNone(db.get_user_details(self.uid)["org_id"])
        self.assertEqual(_auth_events(self.uid, "org_founded"), [])


if __name__ == '__main__':
    unittest.main()
