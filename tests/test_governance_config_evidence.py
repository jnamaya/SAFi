"""
Changing governance config must leave evidence.

WHY. `org_compliance_log` is the append-only record an auditor reads. Knowledge
bases, connectors, provider allow-lists and review dispositions all wrote to it;
the Charter, AI Standards, org governance settings and policies did not. So the
actions with the WIDEST blast radius were the ones with no record of who changed
what, when.

That is not a tidiness point. On 2026-08-09 an AI standard was added that
blocked every response from every agent in an organization, and nothing in SAFi
could answer "who added it, and when" — the question this product exists to
answer.

Asserted at the source, because the alternative is a live database and an
authenticated admin session per endpoint; what matters is that each write path
calls the log with an event name and an actor, and that the payload carries the
few fields an auditor actually needs.

Run:  venv/bin/python tests/test_governance_config_evidence.py
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ORGS = (ROOT / "safi_app" / "api" / "organizations.py").read_text(encoding="utf-8")
POLICIES = (ROOT / "safi_app" / "api" / "policy_api_routes.py").read_text(encoding="utf-8")

# Every governance-config write path, and the event it must record.
EXPECTED = [
    (ORGS, 'charter_saved'),
    (ORGS, 'charter_deleted'),
    (ORGS, 'ai_standards_saved'),
    (ORGS, 'ai_standards_deleted'),
    (ORGS, 'org_settings_changed'),
    (ORGS, 'org_renamed'),
    (POLICIES, 'policy_created'),
    (POLICIES, 'policy_updated'),
    (POLICIES, 'policy_deleted'),
]


class EveryWritePathLeavesEvidence(unittest.TestCase):

    def test_each_event_is_appended(self):
        for src, event in EXPECTED:
            with self.subTest(event=event):
                self.assertIn(f"'{event}'", src,
                              f"no compliance entry for {event}")

    def test_every_append_names_an_actor(self):
        """An entry without an actor answers 'what' but not 'who', which is half
        the question."""
        for src in (ORGS, POLICIES):
            # A generous window rather than paren matching: the arguments
            # contain nested calls and dicts, so any cheap delimiter rule cuts
            # them in the wrong place.
            calls = [frag[:260] for frag in src.split("append_compliance_log(")[1:]]
            self.assertTrue(calls)
            for call in calls:
                # Either an inline f"user:{id}" or a local `actor` holding one.
                named = "user:" in call or re.search(r",\s*actor\s*,", call)
                self.assertTrue(named,
                                f"an append_compliance_log call records no actor: {call[:90]}")


class ThePayloadsAnswerAuditQuestions(unittest.TestCase):

    def test_ai_standards_entry_names_the_blocking_ones(self):
        """The specific question that could not be answered: which standards
        were blocking on the day responses started being stopped. A count is not
        enough — the names are what identify the culprit."""
        self.assertIn('"blocking": sorted(v[\'name\'] for v in cleaned if v.get(\'hard_gate\'))', ORGS)

    def test_ai_standards_entry_records_the_deterministic_settings(self):
        for field in ('"requires_disclaimer"', '"blocked_phrases"', '"tool_cap"'):
            self.assertIn(field, ORGS)

    def test_settings_entry_keeps_before_and_after(self):
        """governance_split and spirit_beta change how every agent is scored, so
        the values are the evidence — not merely that something moved."""
        self.assertIn('"before": before', ORGS)
        self.assertIn('"after": settings', ORGS)

    def test_charter_entry_distinguishes_creation_from_edit(self):
        self.assertIn('"created": not prev', ORGS)
        self.assertIn('"mission_changed"', ORGS)

    def test_policy_entries_reference_the_version_not_the_content(self):
        """Policies already have policy_versions and a restore endpoint, so the
        log points at the version instead of duplicating config."""
        self.assertIn('"version": _after.get(\'version\')', POLICIES)


class TheLogStaysAppendOnly(unittest.TestCase):

    def test_no_update_or_delete_helper_exists(self):
        db = (ROOT / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
        self.assertIn("def append_compliance_log", db)
        for forbidden in ("UPDATE org_compliance_log", "DELETE FROM org_compliance_log"):
            self.assertNotIn(forbidden, db,
                             "the compliance log is append-only evidence; it must not be editable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
