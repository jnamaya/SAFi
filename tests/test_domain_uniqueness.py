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


if __name__ == "__main__":
    unittest.main()
