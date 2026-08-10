"""
Recreating the local admin must not mint a new organization each time.

WHY. `seed_local_admin` runs on every startup. Its create branch fires whenever
the `local_admin` USER is missing — a cleanup, a purge, a test run pointed at
the wrong database — and it used to allocate a fresh uuid4 org every time,
abandoning the previous one.

Measured on the live demo host on 2026-08-10: twenty empty
"Local Admin Organization" rows created between 16 and 22 July, one per
restart. They carried no charter, no policies, no records and no agents, but
they counted as organizations in every query anyone would naturally run — the
same class of mistake as `public_*` rows counting as users.

Run:  venv/bin/python tests/test_local_admin_org_reuse.py
"""
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

SRC = inspect.getsource(db._seed_local_admin)


class TheCreateBranchLooksBeforeItAllocates(unittest.TestCase):

    def test_it_searches_for_an_existing_org_first(self):
        self.assertIn('SELECT id FROM organizations WHERE name = %s', SRC)

    def test_the_lookup_precedes_the_insert(self):
        """Ordering is the whole fix: allocating first and checking afterwards
        would still leave the row behind."""
        self.assertLess(SRC.index("SELECT id FROM organizations WHERE name"),
                        SRC.index("INSERT INTO organizations"),
                        "the org lookup must run before any INSERT")

    def test_a_new_org_is_only_created_when_none_exists(self):
        insert_at = SRC.index("INSERT INTO organizations")
        preceding = SRC[:insert_at]
        self.assertIn("if org_id:", preceding)
        self.assertIn("else:", preceding[preceding.index("if org_id:"):])

    def test_it_converges_on_the_oldest(self):
        """ORDER BY created_at, not an arbitrary row: repeated recreation should
        settle on one organization rather than drifting between several."""
        self.assertIn("ORDER BY created_at LIMIT 1", SRC)

    def test_the_existing_user_path_is_untouched(self):
        """When the user is present its org must not be reassigned — that would
        move a working admin into a different organization on restart."""
        self.assertIn("SELECT id, org_id FROM users WHERE id = 'local_admin'", SRC)
        update_at = SRC.index("UPDATE users SET email=")
        self.assertNotIn("INSERT INTO organizations", SRC[:update_at])


if __name__ == "__main__":
    unittest.main(verbosity=2)
