"""
Public-widget user rows must not accumulate — and the sweep must not destroy.

WHY. The public widget mints one user row per CONVERSATION
(`conversations.py`: `public_{conversation_id}`), so every page reload creates
another. Nothing removed them: `cleanup_old_demo_users` matches `demo_%` only,
and the retention purge deletes conversations rather than the user rows that
pointed at them.

Measured on the live demo host on 2026-08-10: 68 `public_*` rows against ~15
genuinely registered accounts. They are indistinguishable from real users in
any count anyone would naturally run, which is how "94 users" got reported when
the real figure was about 15.

The risk in fixing it is worse than the bug. A sweep that deletes by prefix
would destroy governed turns — 55 governance records and 160 messages on that
same host — in a product whose claim is a complete audit record. So this sweep
removes a row ONLY when it has no conversation AND no governance record.
Anything with either belongs to the retention engine, which respects each org's
retention period, checks legal holds, and evidences what it destroyed.

Run:  venv/bin/python tests/test_public_user_sweep.py
"""
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

_FULL = inspect.getsource(db.cleanup_orphaned_public_users)
# Code only. The docstring explains why `cleanup_old_demo_users` does not cover
# this, so a naive search for "demo_" matches the explanation, not a bug.
SRC = _FULL.split('"""', 2)[-1]
PURGE = (Path(__file__).resolve().parent.parent / "scripts" / "retention_purge.py").read_text(
    encoding="utf-8")


class TheSweepCannotDestroyEvidence(unittest.TestCase):

    def test_it_requires_no_conversation_and_no_governance_record(self):
        """Both conditions, not either. A row with a governance record but no
        conversation is still evidence that a governed turn happened."""
        self.assertIn("NOT EXISTS", SRC)
        self.assertIn("FROM conversations c WHERE c.user_id = u.id", SRC)
        self.assertIn("FROM governance_records g WHERE g.user_id = u.id", SRC)
        self.assertEqual(SRC.count("NOT EXISTS"), 2,
                         "both guards must be present; one alone lets the sweep "
                         "delete a row that still has evidence attached")

    def test_it_only_deletes_from_users(self):
        """It must not cascade into conversations, chat_history or
        governance_records — that is the retention engine's job, on the org's
        own schedule and with its own evidence."""
        deletes = [l for l in SRC.splitlines() if "DELETE FROM" in l.upper()]
        self.assertEqual(len(deletes), 1, f"expected exactly one DELETE, got {deletes}")
        self.assertIn("DELETE FROM users", deletes[0])

    def test_it_is_scoped_to_the_public_prefix(self):
        """The WHERE clause, not the prose: an unanchored LIKE here would sweep
        registered accounts."""
        self.assertIn("LIKE 'public", SRC)
        for other in ("demo_", "LIKE '%'"):
            self.assertNotIn(other, SRC,
                             "the sweep must match the public prefix and nothing else")


class ItRunsWithTheNightlyPurge(unittest.TestCase):

    def test_the_sweep_is_called_from_the_purge_run(self):
        """Scheduled where it belongs: the rows it clears are created by the
        very deletions Phase A performs, so it is the tail of that job rather
        than a second timer to forget about."""
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
        """Retention destruction is the important half of this job. Losing a
        cosmetic sweep must not take it down."""
        i = PURGE.index("def sweep_orphaned_public_users")
        self.assertIn("except Exception", PURGE[i:i + 900])


if __name__ == "__main__":
    unittest.main(verbosity=2)
