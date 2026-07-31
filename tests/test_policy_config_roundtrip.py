"""
`policy_config` must come back as a dict from EVERY policy reader.

WHY. `policy_config` is a JSON column holding four wizard-authored values:
business_unit, scope_statement, alignment_threshold, ethical_memory.
`get_policy` and `get_policy_version_detail` json.loads it; `list_policies` did
not, so it reached the browser as a JSON *string*.

That was not cosmetic. The Governance tab opens the policy editor from the LIST
(`ui-settings-governance.js` -> `openPolicyWizard(policy)`), and `hydratePolicy`
reads `existingPolicy.policy_config.<key>`. On a string every key is `undefined`,
so:

    business_unit       -> ""
    scope_statement     -> ""          <- the reported symptom
    alignment_threshold -> 0.5         <- wizard default
    ethical_memory      -> 0.90        <- wizard default

`alignment_threshold` is written back as
`structural_requirements.alignment_score_threshold`, the Will's blocking
threshold. So opening a policy and saving it silently reset an enforcement
parameter, with no warning, no diff and no audit signal.

Reported as "the scope is not saved". The scope saved fine — the write path was
always correct. That is the point of testing this against a real database rather
than by reading the source: the writer and the consumer are each correct in
isolation, and only the round trip shows the defect.

Needs the disposable stack (it writes and deletes a policy row):
    docker compose -f docker-compose.test.yml run --rm --build tests -k policy_config
"""
import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

# The exact four keys the wizard round-trips, with non-default values so a
# fallback is detectable. 0.5 / 0.90 are the wizard defaults and would mask the
# bug if used here.
CONFIG = {
    "business_unit": "Marketing",
    "scope_statement": "Campaign strategy only — no legal or medical guidance.",
    "alignment_threshold": 0.75,
    "ethical_memory": 0.55,
}


class PolicyConfigRoundTrip(unittest.TestCase):

    def setUp(self):
        self.pid = f"test_policy_{uuid.uuid4().hex[:12]}"
        self.user = f"test_user_{uuid.uuid4().hex[:8]}"
        db.create_policy(
            name="Round Trip Policy",
            worldview="Test worldview.",
            will_rules={"structural_requirements": {"alignment_score_threshold": 0.75}},
            values=[{"value": "Clarity", "weight": 1.0}],
            created_by=self.user,
            policy_id=self.pid,
            policy_config=dict(CONFIG),
        )

    def tearDown(self):
        try:
            db.delete_policy(self.pid)
        except Exception:
            pass

    def _listed(self):
        rows = db.list_policies(user_id=self.user, org_id=None)
        row = next((r for r in rows if r["id"] == self.pid), None)
        self.assertIsNotNone(row, "the policy did not come back from list_policies")
        return row

    def test_01_list_policies_returns_a_dict_not_a_string(self):
        cfg = self._listed()["policy_config"]
        self.assertIsInstance(
            cfg, dict,
            f"policy_config came back as {type(cfg).__name__}. A JSON string here "
            f"makes every cfg.<key> undefined in hydratePolicy, which silently "
            f"resets the Will's blocking threshold on the next save.")

    def test_02_every_wizard_key_survives_the_list_path(self):
        cfg = self._listed()["policy_config"]
        for key, expected in CONFIG.items():
            with self.subTest(key=key):
                self.assertEqual(cfg.get(key), expected,
                                 f"{key} was lost or altered via list_policies")

    def test_03_the_enforcement_threshold_is_not_silently_defaulted(self):
        """The consequence that matters. 0.5 is the wizard's fallback, so seeing it
        after storing 0.75 means the value was lost, not read."""
        cfg = self._listed()["policy_config"]
        self.assertNotEqual(cfg.get("alignment_threshold"), 0.5,
                            "alignment_threshold fell back to the wizard default — "
                            "an edit-and-save would rewrite the blocking threshold")
        self.assertEqual(cfg.get("alignment_threshold"), 0.75)
        self.assertNotEqual(cfg.get("ethical_memory"), 0.90,
                            "ethical_memory fell back to the wizard default")

    def test_04_list_and_get_agree_on_the_same_row(self):
        """Two readers of one column disagreeing is how this survived: the detail
        view looked right while the list view was broken."""
        listed = self._listed()["policy_config"]
        fetched = db.get_policy(self.pid)["policy_config"]
        self.assertIsInstance(fetched, dict)
        self.assertEqual(listed, fetched,
                         "list_policies and get_policy must return the same shape "
                         "and content for the same policy")

    def test_05_the_scope_statement_is_readable_where_the_ui_reads_it(self):
        """The reported symptom, pinned at the exact access pattern the UI uses:
        `existingPolicy.policy_config.scope_statement`."""
        cfg = self._listed()["policy_config"]
        self.assertEqual(cfg.get("scope_statement"), CONFIG["scope_statement"])
        self.assertTrue(cfg.get("scope_statement"),
                        "scope_statement is empty — this is what was reported as "
                        "'the scope is not saved'")

    def test_06_an_absent_config_reads_as_an_empty_dict(self):
        """Legacy rows predate policy_config. They must hydrate as {} so the UI
        gets its defaults, never `None` (which would throw on cfg.get)."""
        legacy = f"test_policy_{uuid.uuid4().hex[:12]}"
        db.create_policy(name="Legacy", worldview="", will_rules=[], values=[],
                         created_by=self.user, policy_id=legacy, policy_config=None)
        try:
            rows = db.list_policies(user_id=self.user, org_id=None)
            row = next(r for r in rows if r["id"] == legacy)
            self.assertIsInstance(row["policy_config"], dict)
            self.assertEqual(row["policy_config"], {})
        finally:
            db.delete_policy(legacy)

    def test_07_the_frontend_tolerates_a_string_as_well(self):
        """Belt and braces: hydratePolicy parses a string config, because the cost
        of being wrong here is an enforcement parameter rather than a label."""
        core = (Path(__file__).resolve().parent.parent / "public" / "js" / "ui"
                / "policy-wizard" / "ui-policy-wizard-core.js").read_text(
                    encoding="utf-8", errors="replace")
        i = core.index("function hydratePolicy")
        seg = core[i:i + 1200]
        self.assertIn("typeof cfg === 'string'", seg,
                      "hydratePolicy should defensively parse a string config")
        self.assertIn("JSON.parse(cfg)", seg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
