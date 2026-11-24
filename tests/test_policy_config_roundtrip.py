import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

CONFIG = {
    "business_unit": "Marketing",
    "scope_statement": "Campaign strategy only — no legal or medical guidance.",
    "context": "Governs the marketing agents.\nSecond line, which used to break the round trip.",
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
        cfg = self._listed()["policy_config"]
        self.assertNotEqual(cfg.get("alignment_threshold"), 0.5,
                            "alignment_threshold fell back to the wizard default — "
                            "an edit-and-save would rewrite the blocking threshold")
        self.assertEqual(cfg.get("alignment_threshold"), 0.75)
        self.assertNotEqual(cfg.get("ethical_memory"), 0.90,
                            "ethical_memory fell back to the wizard default")

    def test_04_list_and_get_agree_on_the_same_row(self):
        listed = self._listed()["policy_config"]
        fetched = db.get_policy(self.pid)["policy_config"]
        self.assertIsInstance(fetched, dict)
        self.assertEqual(listed, fetched,
                         "list_policies and get_policy must return the same shape "
                         "and content for the same policy")

    def test_05_the_scope_statement_is_readable_where_the_ui_reads_it(self):
        cfg = self._listed()["policy_config"]
        self.assertEqual(cfg.get("scope_statement"), CONFIG["scope_statement"])
        self.assertTrue(cfg.get("scope_statement"),
                        "scope_statement is empty — this is what was reported as "
                        "'the scope is not saved'")

    def test_06_an_absent_config_reads_as_an_empty_dict(self):
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
        core = (Path(__file__).resolve().parent.parent / "public" / "js" / "ui"
                / "policy-wizard" / "ui-policy-wizard-core.js").read_text(
                    encoding="utf-8", errors="replace")
        i = core.index("function hydratePolicy")
        seg = core[i:i + 1200]
        self.assertIn("typeof cfg === 'string'", seg,
                      "hydratePolicy should defensively parse a string config")
        self.assertIn("JSON.parse(cfg)", seg)


    def test_08_a_multiline_description_survives_intact(self):
        for cfg in (self._listed()["policy_config"],
                    db.get_policy(self.pid)["policy_config"]):
            self.assertEqual(cfg.get("context"), CONFIG["context"])
            self.assertIn("\n", cfg.get("context"))

    def test_09_the_wizard_no_longer_embeds_the_description_in_worldview(self):
        core = (Path(__file__).resolve().parent.parent / "public" / "js" / "ui"
                / "policy-wizard" / "ui-policy-wizard-core.js").read_text(
                    encoding="utf-8", errors="replace")
        self.assertNotIn("<!-- CONTEXT: ${", core,
                         "submitPolicy is embedding the description in worldview "
                         "again — that round trip corrupts on the first newline")
        self.assertIn("[\\s\\S]*?", core,
                      "the legacy CONTEXT readers must tolerate newlines, or "
                      "old rows keep hydrating empty")
        step1 = (Path(__file__).resolve().parent.parent / "public" / "js" / "ui"
                 / "agent-wizard" / "ui-wizard-step1.js").read_text(
                     encoding="utf-8", errors="replace")
        self.assertIn("[\\s\\S]*?", step1,
                      "the agent wizard's policy summary strip must tolerate "
                      "newlines for legacy rows")


if __name__ == "__main__":
    unittest.main(verbosity=2)
