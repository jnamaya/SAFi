"""
Cross-org isolation on the policy and agent APIs (backlog 70).

A confirmed IDOR cluster: policy-management endpoints and GET /agents/<key>
fetched a resource by id and acted on it without comparing its org_id to the
caller's org. Any logged-in user of org A could read (and an editor mutate,
delete, or mint keys against) org B's policies and read org B's agent config.

These tests drive the HTTP API as org B against org A's resources and assert
404, while confirming the legitimate paths still work: org A's owner reads its
own policy, and demo/global templates stay readable by everyone.

Requires local MySQL. Run:
    docker compose -f docker-compose.test.yml run --rm tests -k cross_org
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


class CrossOrgIsolation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        self.org_a = str(uuid.uuid4())
        self.org_b = str(uuid.uuid4())
        # policies/agents FK org_id -> organizations(id), so the orgs must exist.
        _exec("INSERT INTO organizations (id, name) VALUES (%s,%s)", (self.org_a, "Org A"))
        _exec("INSERT INTO organizations (id, name) VALUES (%s,%s)", (self.org_b, "Org B"))
        self.admin_a = new_user(f"a_{uuid.uuid4().hex[:8]}", org_id=self.org_a, role='admin')
        self.admin_b = new_user(f"b_{uuid.uuid4().hex[:8]}", org_id=self.org_b, role='admin')

        # Org A owns a policy and a custom agent.
        self.policy_a = f"pol_a_{uuid.uuid4().hex[:10]}"
        db.create_policy(name="Org A Policy", worldview="A worldview",
                         will_rules=[], values=[], org_id=self.org_a,
                         created_by=self.admin_a, policy_id=self.policy_a)
        self.agent_a = f"agent_a_{uuid.uuid4().hex[:8]}"
        db.create_agent(key=self.agent_a, name="Org A Agent", description="",
                        avatar="", worldview="secret worldview", style="",
                        values=[], rules=[], policy_id="standalone",
                        created_by=self.admin_a, org_id=self.org_a)

        # A demo/global template (readable by all).
        self.demo_pol = f"demo_pol_{uuid.uuid4().hex[:8]}"
        db.create_policy(name="Demo Template", worldview="tpl", will_rules=[],
                         values=[], org_id=None, created_by=None, policy_id=self.demo_pol)
        _exec("UPDATE policies SET is_demo=TRUE WHERE id=%s", (self.demo_pol,))

        self.client = self.app.test_client()

    def tearDown(self):
        _exec("DELETE FROM policies WHERE id IN (%s,%s)", (self.policy_a, self.demo_pol))
        _exec("DELETE FROM agents WHERE agent_key=%s", (self.agent_a,))
        for u in (self.admin_a, self.admin_b):
            _exec("DELETE FROM sessions WHERE user_id=%s", (u,))
            _exec("DELETE FROM users WHERE id=%s", (u,))
        _exec("DELETE FROM organizations WHERE id IN (%s,%s)", (self.org_a, self.org_b))

    # --- org B is blocked from org A's policy on every route ---

    def test_org_b_cannot_read_org_a_policy(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        r = self.client.get(f"/api/policies/{self.policy_a}")
        self.assertEqual(r.status_code, 404)

    def test_org_b_cannot_read_versions_or_keys(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        for path in (f"/api/policies/{self.policy_a}/versions",
                     f"/api/policies/{self.policy_a}/keys"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_org_b_cannot_mint_key_against_org_a_policy(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        r = self.client.post(f"/api/policies/{self.policy_a}/keys", json={"label": "x"})
        self.assertEqual(r.status_code, 404)

    def test_org_b_cannot_rotate_or_delete_or_update_org_a_policy(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        self.assertEqual(self.client.post(f"/api/policies/{self.policy_a}/rotate_key").status_code, 404)
        self.assertEqual(self.client.put(f"/api/policies/{self.policy_a}",
                                         json={"name": "hijack", "worldview": "x"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/policies/{self.policy_a}").status_code, 404)
        # The policy is untouched.
        self.assertIsNotNone(db.get_policy(self.policy_a))
        self.assertEqual(db.get_policy(self.policy_a)['name'], "Org A Policy")

    def test_org_b_cannot_read_org_a_agent_config(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        r = self.client.get(f"/api/agents/{self.agent_a}")
        self.assertEqual(r.status_code, 404)

    # --- legitimate paths still work ---

    def test_org_a_owner_can_read_its_policy(self):
        login_as(self.client, self.admin_a, 'admin', org_id=self.org_a)
        r = self.client.get(f"/api/policies/{self.policy_a}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['policy']['name'], "Org A Policy")

    def test_org_a_owner_can_read_its_agent(self):
        login_as(self.client, self.admin_a, 'admin', org_id=self.org_a)
        r = self.client.get(f"/api/agents/{self.agent_a}")
        self.assertEqual(r.status_code, 200)

    def test_demo_template_readable_by_any_org(self):
        login_as(self.client, self.admin_b, 'admin', org_id=self.org_b)
        r = self.client.get(f"/api/policies/{self.demo_pol}")
        self.assertEqual(r.status_code, 200, "demo templates must stay globally readable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
