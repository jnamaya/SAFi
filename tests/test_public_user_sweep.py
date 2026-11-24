import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

_FULL = inspect.getsource(db.cleanup_orphaned_public_users)
SRC = _FULL.split('"""', 2)[-1]
PURGE = (Path(__file__).resolve().parent.parent / "scripts" / "retention_purge.py").read_text(
    encoding="utf-8")


class TheSweepCannotDestroyEvidence(unittest.TestCase):

    def test_it_requires_no_conversation_and_no_governance_record(self):
        self.assertIn("NOT EXISTS", SRC)
        self.assertIn("FROM conversations c WHERE c.user_id = u.id", SRC)
        self.assertIn("FROM governance_records g WHERE g.user_id = u.id", SRC)
        self.assertEqual(SRC.count("NOT EXISTS"), 2,
                         "both guards must be present; one alone lets the sweep "
                         "delete a row that still has evidence attached")

    def test_it_only_deletes_from_users(self):
        deletes = [l for l in SRC.splitlines() if "DELETE FROM" in l.upper()]
        self.assertEqual(len(deletes), 1, f"expected exactly one DELETE, got {deletes}")
        self.assertIn("DELETE FROM users", deletes[0])

    def test_it_is_scoped_to_the_public_prefix(self):
        self.assertIn("LIKE 'public", SRC)
        for other in ("demo_", "LIKE '%'"):
            self.assertNotIn(other, SRC,
                             "the sweep must match the public prefix and nothing else")


class ItRunsWithTheNightlyPurge(unittest.TestCase):

    def test_the_sweep_is_called_from_the_purge_run(self):
        self.assertIn("sweep_orphaned_public_users(args)", PURGE)

    def test_dry_run_deletes_nothing(self):
        i = PURGE.index("def sweep_orphaned_public_users")
        body = PURGE[i:i + 900]
        self.assertIn("if args.dry_run:", body)
        self.assertLess(body.index("if args.dry_run:"),
                        body.index("cleanup_orphaned_public_users"),
                        "the dry-run guard must precede the delete")

    def test_it_evidences_what_it_removed(self):
        self.assertIn('"public_users_swept"', PURGE)

    def test_a_sweep_failure_cannot_abort_the_purge(self):
        i = PURGE.index("def sweep_orphaned_public_users")
        self.assertIn("except Exception", PURGE[i:i + 900])


if __name__ == "__main__":
    unittest.main(verbosity=2)
