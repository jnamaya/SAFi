"""
Retired demo policies must not surface as Example Policies.

WHY. The Governance tab's Example Policies section renders every policy that
`list_policies` returns with `is_demo=TRUE`. When a demo agent is retired, its
seeded policy row is deliberately KEPT in the database as point-in-time
provenance for the governance records it once governed (see the demo host
cleanup item in GOVERNANCE_BACKLOG.md: the Contoso row must not be deleted).
Before this fix, that kept row still rendered as an example: the Contoso GenAI
Use Policy was visible on the demo host months after the agent was removed.

The contract, pinned here:

- `list_policies` surfaces a demo row only when its id is in the CURRENT seed
  set (DEMO_AGENT_POLICIES keys plus safi_default_policy). An is_demo row with
  any other id is a retired leftover and stays hidden.
- `get_policy` stays unfiltered, so historical governance records that
  reference a retired policy by id keep resolving it.

Needs the disposable stack (it writes and deletes policy rows):
    docker compose -f docker-compose.test.yml run --rm tests -k retired_demo
"""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.policies.demo.policies import DEMO_AGENT_POLICIES


def _set_is_demo(pid, flag):
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE policies SET is_demo=%s WHERE id=%s", (flag, pid))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


class RetiredDemoPoliciesStayHidden(unittest.TestCase):

    def setUp(self):
        self.user = f"test_user_{uuid.uuid4().hex[:8]}"
        # A demo-flagged row whose id is in no current seed set: exactly what a
        # retired agent leaves behind.
        self.retired_pid = f"test_retired_demo_{uuid.uuid4().hex[:12]}"
        db.create_policy(
            name="Retired Demo Policy",
            worldview="Governed an agent that no longer exists.",
            will_rules=[],
            values=[{"value": "Clarity", "weight": 1.0}],
            created_by=None,
            policy_id=self.retired_pid,
        )
        _set_is_demo(self.retired_pid, True)

    def tearDown(self):
        try:
            db.delete_policy(self.retired_pid)
        except Exception:
            pass

    def test_01_a_retired_demo_row_is_not_listed(self):
        rows = db.list_policies(user_id=self.user, org_id=None)
        ids = [r["id"] for r in rows]
        self.assertNotIn(
            self.retired_pid, ids,
            "an is_demo row outside the current seed set surfaced in "
            "list_policies — this is the Contoso GenAI Use Policy bug")

    def test_02_the_retired_row_still_resolves_by_id(self):
        """Provenance: old governance records reference the policy by id."""
        row = db.get_policy(self.retired_pid)
        self.assertIsNotNone(
            row,
            "get_policy must keep resolving retired demo rows, or historical "
            "governance records lose their policy provenance")
        self.assertEqual(row["id"], self.retired_pid)

    def test_03_a_current_seed_id_is_still_listed(self):
        """The filter must be membership in the seed set, not is_demo=FALSE
        everywhere. Seed one current demo id if the test db lacks it."""
        current_pid = next(iter(DEMO_AGENT_POLICIES))
        created_here = False
        if not db.get_policy(current_pid):
            pol = DEMO_AGENT_POLICIES[current_pid]
            db.create_policy(
                name=pol["name"],
                worldview=pol.get("worldview", ""),
                will_rules=pol.get("will_rules", []),
                values=pol.get("values", []),
                created_by=None,
                policy_id=current_pid,
            )
            _set_is_demo(current_pid, True)
            created_here = True
        try:
            rows = db.list_policies(user_id=self.user, org_id=None)
            ids = [r["id"] for r in rows]
            self.assertIn(current_pid, ids,
                          "a current demo policy vanished from the list — the "
                          "seed-set filter is too aggressive")
        finally:
            if created_here:
                db.delete_policy(current_pid)

    def test_04_own_policies_are_unaffected_by_the_demo_filter(self):
        own_pid = f"test_policy_{uuid.uuid4().hex[:12]}"
        db.create_policy(name="Mine", worldview="", will_rules=[],
                         values=[], created_by=self.user, policy_id=own_pid)
        try:
            rows = db.list_policies(user_id=self.user, org_id=None)
            ids = [r["id"] for r in rows]
            self.assertIn(own_pid, ids)
        finally:
            db.delete_policy(own_pid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
