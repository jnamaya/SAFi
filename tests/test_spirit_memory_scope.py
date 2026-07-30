"""
spirit_memory is keyed on profile_name alone, so a built-in agent's baseline is
shared by every org using it. That is intentional — with an identical persona and
policy, "how this agent expresses its values" is a property of the agent, and
pooling gives a better-estimated baseline.

What was NOT intentional: reset_spirit_memory deleted that shared row
unconditionally and returned a bare True/False, so an operator clearing "their"
agent's baseline from a shell silently moved the Consistency figures of every
other tenant, with nothing on screen to say so.

These tests pin the guard. They also pin that the guard triggers on real blast
radius rather than on the name, so a single-tenant built-in and a throwaway test
fixture are not gratuitously blocked.

Requires local MySQL. Run:  venv/bin/python tests/test_spirit_memory_scope.py
"""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class TestSpiritMemoryScope(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tag = uuid.uuid4().hex[:8]
        cls.shared_agent = f"the_shared_{cls.tag}"          # built-in shape
        cls.custom_agent = f"org_9999_custom_{cls.tag}"     # org-prefixed shape
        cls.lonely_agent = f"the_lonely_{cls.tag}"          # built-in, one org
        cls.orgs = [str(uuid.uuid4()) for _ in range(2)]
        # Two orgs' worth of records against the same built-in agent name.
        for i, org in enumerate(cls.orgs):
            _exec("INSERT INTO governance_records (org_id, user_id, profile_key, "
                  "conversation_id, message_pk, message_id, record_enc, created_at) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())",
                  (org, f"u{i}_{cls.tag}", cls.shared_agent, str(uuid.uuid4()),
                   900000 + i, str(uuid.uuid4()), "{}"))
        _exec("INSERT INTO governance_records (org_id, user_id, profile_key, "
              "conversation_id, message_pk, message_id, record_enc, created_at) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())",
              (cls.orgs[0], f"solo_{cls.tag}", cls.lonely_agent, str(uuid.uuid4()),
               900100, str(uuid.uuid4()), "{}"))
        for agent in (cls.shared_agent, cls.custom_agent, cls.lonely_agent):
            _exec("INSERT INTO spirit_memory (profile_name, turn, mu) "
                  "VALUES (%s, 5, %s)", (agent, '{"honesty": 0.5}'))

    @classmethod
    def tearDownClass(cls):
        for agent in (cls.shared_agent, cls.custom_agent, cls.lonely_agent):
            _exec("DELETE FROM spirit_memory WHERE profile_name=%s", (agent,))
            _exec("DELETE FROM governance_records WHERE profile_key=%s", (agent,))

    def _exists(self, agent):
        return db.load_spirit_memory(agent) is not None

    def test_01_scope_reports_the_blast_radius(self):
        s = db.spirit_memory_scope(self.shared_agent)
        self.assertTrue(s["shared"], "a non org-prefixed key is shared by name")
        self.assertTrue(s["cross_tenant"], "two orgs is a real cross-tenant baseline")
        self.assertEqual(s["orgs"], 2)
        self.assertEqual(s["users"], 2)

    def test_02_org_prefixed_agents_are_namespaced_by_construction(self):
        s = db.spirit_memory_scope(self.custom_agent)
        self.assertFalse(s["shared"], "org_-prefixed keys cannot collide across tenants")
        self.assertFalse(s["cross_tenant"])

    def test_03_refuses_to_reset_a_cross_tenant_baseline(self):
        """The actual fix. Previously this deleted and returned True."""
        res = db.reset_spirit_memory(self.shared_agent)
        self.assertTrue(res["refused"], "must not silently reset 2 orgs' baseline")
        self.assertFalse(res["deleted"])
        self.assertEqual(res["scope"]["orgs"], 2, "the refusal reports the radius")
        self.assertTrue(self._exists(self.shared_agent), "row must survive a refusal")

    def test_04_resets_when_explicitly_confirmed(self):
        res = db.reset_spirit_memory(self.shared_agent, confirm_shared=True)
        self.assertTrue(res["deleted"])
        self.assertFalse(res["refused"])
        self.assertFalse(self._exists(self.shared_agent))

    def test_05_custom_agent_needs_no_confirmation(self):
        res = db.reset_spirit_memory(self.custom_agent)
        self.assertTrue(res["deleted"], "an org's own agent is theirs to reset")
        self.assertFalse(res["refused"])

    def test_06_single_tenant_builtin_is_not_gratuitously_blocked(self):
        """The guard keys on real blast radius, not on the name. A built-in used
        by one org — or a throwaway fixture with no records — has no other tenant
        to disturb, and refusing there would be friction with no safety value."""
        res = db.reset_spirit_memory(self.lonely_agent)
        self.assertTrue(res["deleted"])
        self.assertFalse(res["refused"])

    def test_07_unused_agent_name_reports_no_radius(self):
        s = db.spirit_memory_scope(f"never_used_{self.tag}")
        self.assertEqual(s["orgs"], 0)
        self.assertFalse(s["cross_tenant"])
        res = db.reset_spirit_memory(f"never_used_{self.tag}")
        self.assertFalse(res["refused"])
        self.assertFalse(res["deleted"], "nothing to delete, but not a refusal either")

    def test_08_return_shape_is_never_a_bare_bool(self):
        """A bare True/False is what let the blast radius go unnoticed."""
        res = db.reset_spirit_memory(f"shape_check_{self.tag}")
        self.assertIsInstance(res, dict)
        self.assertEqual(set(res), {"deleted", "refused", "scope"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
