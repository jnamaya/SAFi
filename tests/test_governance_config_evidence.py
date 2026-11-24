import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ORGS = (ROOT / "safi_app" / "api" / "organizations.py").read_text(encoding="utf-8")
POLICIES = (ROOT / "safi_app" / "api" / "policy_api_routes.py").read_text(encoding="utf-8")

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
    (ORGS, 'member_role_changed'),
    (ORGS, 'member_removed'),
]


class EveryWritePathLeavesEvidence(unittest.TestCase):

    def test_each_event_is_appended(self):
        for src, event in EXPECTED:
            with self.subTest(event=event):
                self.assertIn(f"'{event}'", src,
                              f"no compliance entry for {event}")

    def test_every_append_names_an_actor(self):
        for src in (ORGS, POLICIES):
            calls = [frag[:260] for frag in src.split("append_compliance_log(")[1:]]
            self.assertTrue(calls)
            for call in calls:
                named = "user:" in call or re.search(r",\s*actor\s*,", call)
                self.assertTrue(named,
                                f"an append_compliance_log call records no actor: {call[:90]}")


class ThePayloadsAnswerAuditQuestions(unittest.TestCase):

    def test_ai_standards_entry_names_the_non_negotiable_ones(self):
        self.assertIn('"non_negotiable": sorted(v[\'name\'] for v in cleaned if v.get(\'hard_gate\'))', ORGS)

    def test_ai_standards_entry_records_the_deterministic_settings(self):
        for field in ('"requires_disclaimer"', '"blocked_phrases"', '"tool_cap"'):
            self.assertIn(field, ORGS)

    def test_settings_entry_keeps_before_and_after(self):
        self.assertIn('"before": before', ORGS)
        self.assertIn('"after": settings', ORGS)

    def test_charter_entry_distinguishes_creation_from_edit(self):
        self.assertIn('"created": not prev', ORGS)
        self.assertIn('"mission_changed"', ORGS)

    def test_policy_entries_reference_the_version_not_the_content(self):
        self.assertIn('"version": _after.get(\'version\')', POLICIES)


class RoleChangesAreVisibleNotJustRecorded(unittest.TestCase):

    def test_role_change_captures_both_sides(self):
        self.assertIn('"prior_role": prior', ORGS)
        self.assertIn('"new_role": new_role', ORGS)

    def test_admin_transitions_are_called_out_explicitly(self):
        self.assertIn('"admin_granted"', ORGS)
        self.assertIn('"admin_revoked"', ORGS)

    def test_removal_records_what_they_could_do(self):
        self.assertIn("'member_removed'", ORGS)
        self.assertIn('"prior_role": prior', ORGS)


class TheLogStaysAppendOnly(unittest.TestCase):

    def test_no_update_or_delete_helper_exists(self):
        db = (ROOT / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
        self.assertIn("def append_compliance_log", db)
        for forbidden in ("UPDATE org_compliance_log", "DELETE FROM org_compliance_log"):
            self.assertNotIn(forbidden, db,
                             "the compliance log is append-only evidence; it must not be editable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
