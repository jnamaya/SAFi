"""
A domain is verified by exactly one organization (backlog 78).

WHY. Nothing used to stop two orgs verifying the same domain: the writes were
unconditional, there was no duplicate check, and get_organization_by_domain took
the first row with no ordering. So "who owns this domain" was arbitrary, and
that answer decides real things: a verified domain outranks invitations
(item 75) and drives domain auto-join, so an ambiguous owner sends new people to
an arbitrary tenant.

What is deliberately NOT done: absorbing or downgrading an existing
organization. A later verifier taking over an org that already exists, with its
policies, agents and records, would be a takeover vector. The endpoints refuse
and point at support instead.

Needs the disposable stack:
    docker compose -f docker-compose.test.yml run --rm tests -k domain_uniqueness
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db

from support import login_as, new_user


def _verify(org_id, domain):
    """Force a verified domain, the state the guard has to defend."""
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE organizations SET domain_to_verify=%s, domain_verified=TRUE "
                    "WHERE id=%s", (domain, org_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()


class OneDomainOneOrg(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.domain = f"contested{tag}.example"
        self.org_first = db.create_organization(f"First {tag}")
        self.org_second = db.create_organization(f"Second {tag}")
        _verify(self.org_first, self.domain)          # the incumbent owner

        self.admin_second = f"dom-admin-{tag}"
        new_user(user_id=self.admin_second, org_id=self.org_second, role="admin")
        self.client = self.app.test_client()
        login_as(self.client, self.admin_second, "admin", org_id=self.org_second)

    def tearDown(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            for oid in (self.org_first, self.org_second):
                cur.execute("UPDATE users SET org_id=NULL WHERE org_id=%s", (oid,))
                cur.execute("DELETE FROM organizations WHERE id=%s", (oid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def test_starting_verification_on_a_taken_domain_is_refused(self):
        r = self.client.post('/api/organizations/domain/start',
                             json={"org_id": self.org_second, "domain": self.domain})
        self.assertEqual(r.status_code, 409)
        self.assertIn("another organization", r.get_json()["error"].lower())

    def test_the_incumbent_may_re_verify_its_own_domain(self):
        # Same domain, same org: not a conflict, so it must not be blocked.
        admin_first = f"dom-first-{uuid.uuid4().hex[:8]}"
        new_user(user_id=admin_first, org_id=self.org_first, role="admin")
        c = self.app.test_client()
        login_as(c, admin_first, "admin", org_id=self.org_first)
        r = c.post('/api/organizations/domain/start',
                   json={"org_id": self.org_first, "domain": self.domain})
        self.assertEqual(r.status_code, 200)

    def test_an_unclaimed_domain_still_works(self):
        r = self.client.post('/api/organizations/domain/start',
                             json={"org_id": self.org_second,
                                   "domain": f"free-{uuid.uuid4().hex[:6]}.example"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "pending")

    def test_confirm_is_refused_when_the_domain_was_taken_meanwhile(self):
        # Model the race the start-time check cannot cover: this org began
        # verification first, someone else verified in between.
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE organizations SET domain_to_verify=%s, "
                        "verification_token=%s WHERE id=%s",
                        (self.domain, "safi-verification=pending-token", self.org_second))
            conn.commit()
        finally:
            cur.close()
            conn.close()

        r = self.client.post('/api/organizations/domain/verify',
                             json={"org_id": self.org_second})
        self.assertEqual(r.status_code, 409,
                         "the commit step is the one that must refuse")
        # And it must not have flipped the flag.
        self.assertFalse(db.get_organization(self.org_second).get('domain_verified'))

    def test_ownership_is_deterministic_when_duplicates_already_exist(self):
        # A database written before the guard can hold two verified rows. The
        # lookup must answer the SAME way every time, rather than returning
        # whichever row the server happens to hand back first.
        #
        # Only stability is asserted, not which org wins: created_at is second
        # granularity, so two orgs created in the same second tie and the id
        # breaks it arbitrarily. Asserting a winner here would be asserting UUID
        # ordering, which is not a property worth pinning.
        _verify(self.org_second, self.domain)
        answers = {db.get_organization_by_domain(self.domain)['id'] for _ in range(6)}
        self.assertEqual(len(answers), 1, "the domain owner must not vary between calls")
        self.assertIn(answers.pop(), (self.org_first, self.org_second))


class VerifiedDomainClaimsItsIdentities(unittest.TestCase):
    """Proving a domain claims the accounts on it (backlog 78, Nelson's call):
    they join the owning org as members, and that admin decides who is promoted.
    Corporate-standard behaviour, matching Google Workspace and Microsoft 365.

    Everyone lands as 'member', so absorption can only reduce an absorbed user's
    authority, never grant any."""

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.domain = f"claimed{self.tag}.example"
        self.org_owner = db.create_organization(f"Owner {self.tag}")
        self.org_other = db.create_organization(f"Other {self.tag}")
        self.made_users = []
        self.made_orgs = [self.org_owner, self.org_other]

    def tearDown(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            for uid in self.made_users:
                cur.execute("DELETE FROM auth_events WHERE user_id=%s", (uid,))
                cur.execute("DELETE FROM users WHERE id=%s", (uid,))
            for oid in self.made_orgs:
                cur.execute("DELETE FROM auth_events WHERE org_id=%s", (oid,))
                cur.execute("UPDATE users SET org_id=NULL WHERE org_id=%s", (oid,))
                cur.execute("DELETE FROM organizations WHERE id=%s", (oid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _user(self, local, org_id=None, role="member"):
        uid = f"absorb-{local}-{self.tag}"
        new_user(user_id=uid, email=f"{local}@{self.domain}", org_id=org_id, role=role)
        self.made_users.append(uid)
        return uid

    def _absorb(self):
        return db.absorb_domain_users(self.org_owner, self.domain, "user:test-admin")

    def test_an_account_in_another_org_is_moved_in_as_member(self):
        uid = self._user("mover", org_id=self.org_other, role="admin")
        report = self._absorb()
        self.assertIn(f"mover@{self.domain}", report["moved"])
        row = db.get_user_details(uid)
        self.assertEqual(row["org_id"], self.org_owner)
        self.assertEqual(row["role"], "member",
                         "absorption must never carry a role across; admin of the "
                         "old org does not become admin here")

    def test_an_org_less_account_is_claimed_too(self):
        uid = self._user("loner", org_id=None)
        self._absorb()
        self.assertEqual(db.get_user_details(uid)["org_id"], self.org_owner)

    def test_the_owning_orgs_own_members_are_untouched(self):
        uid = self._user("insider", org_id=self.org_owner, role="admin")
        report = self._absorb()
        self.assertNotIn(f"insider@{self.domain}", report["moved"])
        self.assertEqual(db.get_user_details(uid)["role"], "admin",
                         "the verifying admin must not demote themselves")

    def test_accounts_on_other_domains_are_not_touched(self):
        uid = f"absorb-outsider-{self.tag}"
        new_user(user_id=uid, email=f"person@elsewhere{self.tag}.example",
                 org_id=self.org_other, role="admin")
        self.made_users.append(uid)
        self._absorb()
        self.assertEqual(db.get_user_details(uid)["org_id"], self.org_other)

    def test_the_rule_has_no_exceptions_even_for_another_orgs_sole_admin(self):
        """One domain per org, everyone on the domain is a member of it. A user
        administering another org from an address on this domain is out of model,
        and the domain wins. The org they leave behind is FLAGGED, not spared:
        silence there would leave members unable to administer anything."""
        admin = self._user("contractor", org_id=self.org_other, role="admin")
        staff = f"absorb-staff-{self.tag}"
        new_user(user_id=staff, email=f"staff@othercorp{self.tag}.example",
                 org_id=self.org_other, role="member")
        self.made_users.append(staff)

        report = self._absorb()

        self.assertEqual(db.get_user_details(admin)["org_id"], self.org_owner,
                         "the domain claims the identity, no exception")
        self.assertEqual(db.get_user_details(admin)["role"], "member")
        self.assertIn(self.org_other, report["orgs_without_admin"],
                      "and the org left with members but no admin must be reported")

    def test_the_headless_org_is_not_auto_promoted(self):
        # Handing a remaining member admin they never asked for is a silent
        # authority grant, which is what this product must not do quietly.
        self._user("contractor2", org_id=self.org_other, role="admin")
        staff = f"absorb-staff2-{self.tag}"
        new_user(user_id=staff, email=f"staff2@othercorp{self.tag}.example",
                 org_id=self.org_other, role="member")
        self.made_users.append(staff)
        self._absorb()
        self.assertEqual(db.get_user_details(staff)["role"], "member",
                         "nobody is promoted automatically")

    def test_a_headless_org_is_journaled(self):
        self._user("contractor3", org_id=self.org_other, role="admin")
        staff = f"absorb-staff3-{self.tag}"
        new_user(user_id=staff, email=f"staff3@othercorp{self.tag}.example",
                 org_id=self.org_other, role="member")
        self.made_users.append(staff)
        self._absorb()
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT event FROM auth_events WHERE org_id=%s AND event=%s",
                        (self.org_owner, 'org_left_without_admin'))
            self.assertIsNotNone(cur.fetchone())
        finally:
            cur.close()
            conn.close()

    def test_a_sole_admin_of_an_EMPTY_org_is_absorbed(self):
        # Nobody is left behind, so there is nothing to protect. This is
        # Nelson's own case: one person, one org, their own domain.
        uid = self._user("solo", org_id=self.org_other, role="admin")
        report = self._absorb()
        self.assertIn(f"solo@{self.domain}", report["moved"])
        self.assertIn(self.org_other, report["emptied_orgs"],
                      "an org left with no members is reported, not deleted")

    def test_an_emptied_org_is_reported_but_still_exists(self):
        self._user("solo2", org_id=self.org_other, role="admin")
        self._absorb()
        self.assertIsNotNone(db.get_organization(self.org_other),
                             "governance records are evidence; the org is not dissolved")

    def test_absorption_is_journaled(self):
        self._user("audited", org_id=self.org_other)
        self._absorb()
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT event FROM auth_events WHERE org_id=%s AND event=%s",
                        (self.org_owner, 'member_absorbed_by_domain'))
            self.assertIsNotNone(cur.fetchone(),
                                 "moving someone between tenants must leave evidence")
        finally:
            cur.close()
            conn.close()


if __name__ == "__main__":
    unittest.main()
