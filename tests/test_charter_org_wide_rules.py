import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.synderesis import apply_charter, authorized_tools
from safi_app.core.faculties.will import WillGate
from safi_app.core.tool_connectors import CONNECTOR_TOOLS, expand_connectors


def base_profile(will_rules=None):
    return {"name": "Agent", "values": [], "will_rules": will_rules if will_rules is not None else {}}


def charter_with(**kw):
    return dict(kw)


class TestBackwardCompatibility(unittest.TestCase):

    def test_no_charter_is_a_no_op(self):
        wr = {"structural_requirements": {"require_disclaimer": True}}
        out = apply_charter(base_profile(wr), None, ai_standards=None)
        self.assertEqual(out["will_rules"], wr)

    def test_charter_without_the_new_fields_is_a_no_op(self):
        wr = {"structural_requirements": {"banned_markdown_syntaxes": ["```html"]}}
        out = apply_charter(base_profile(wr), None, ai_standards=charter_with())
        self.assertEqual(out["will_rules"], wr)

    def test_empty_charter_tool_list_does_not_deny_all(self):
        out = apply_charter(base_profile({"allowed_tools": ["github"]}), None, ai_standards=charter_with(allowed_tools=[]))
        self.assertEqual(out["will_rules"]["allowed_tools"], ["github"])


class TestDisclaimerPrecedence(unittest.TestCase):

    def test_charter_turns_the_requirement_on(self):
        out = apply_charter(base_profile(), None, ai_standards=charter_with(structural_requirements={
            "require_disclaimer": True, "mandatory_disclaimer_substring": "AI-generated.",
        }))
        struct = out["will_rules"]["structural_requirements"]
        self.assertTrue(struct["require_disclaimer"])
        self.assertEqual(struct["mandatory_disclaimer_substring"], "AI-generated.")

    def test_policy_cannot_switch_the_requirement_off(self):
        policy = {"structural_requirements": {"require_disclaimer": False}}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(structural_requirements={
            "require_disclaimer": True, "mandatory_disclaimer_substring": "AI-generated.",
        }))
        self.assertTrue(out["will_rules"]["structural_requirements"]["require_disclaimer"])

    def test_charter_substring_replaces_the_policy_one(self):
        policy = {"structural_requirements": {
            "require_disclaimer": True, "mandatory_disclaimer_substring": "Unit disclaimer.",
        }}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(structural_requirements={
            "require_disclaimer": True, "mandatory_disclaimer_substring": "Org disclaimer.",
        }))
        self.assertEqual(
            out["will_rules"]["structural_requirements"]["mandatory_disclaimer_substring"],
            "Org disclaimer.",
        )

    def test_policy_disclaimer_survives_when_charter_sets_none(self):
        policy = {"structural_requirements": {
            "require_disclaimer": True, "mandatory_disclaimer_substring": "Unit disclaimer.",
        }}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(early_prompt_blacklist=["x"]))
        self.assertEqual(
            out["will_rules"]["structural_requirements"]["mandatory_disclaimer_substring"],
            "Unit disclaimer.",
        )

    def test_the_merged_disclaimer_actually_blocks(self):
        out = apply_charter(base_profile(), None, ai_standards=charter_with(structural_requirements={
            "require_disclaimer": True, "mandatory_disclaimer_substring": "AI-generated.",
        }))
        will = WillGate(None, values=[], profile=out)
        ok, reason = will.evaluate_draft_structure("Here is your answer.")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_disclaimer")
        ok, _ = will.evaluate_draft_structure("Here is your answer.\n\nAI-generated.")
        self.assertTrue(ok)


class TestUnionAndThreshold(unittest.TestCase):

    def test_banned_markdown_is_unioned(self):
        policy = {"structural_requirements": {"banned_markdown_syntaxes": ["```js"]}}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(
            structural_requirements={"banned_markdown_syntaxes": ["```html"]}))
        banned = out["will_rules"]["structural_requirements"]["banned_markdown_syntaxes"]
        self.assertIn("```js", banned)
        self.assertIn("```html", banned)

    def test_blacklist_is_unioned_without_duplicates(self):
        policy = {"early_prompt_blacklist": ["shared phrase", "unit phrase"]}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(
            early_prompt_blacklist=["shared phrase", "org phrase"]))
        bl = out["will_rules"]["early_prompt_blacklist"]
        self.assertEqual(sorted(bl), ["org phrase", "shared phrase", "unit phrase"])
        self.assertEqual(len(bl), len(set(bl)))

    def test_threshold_takes_the_stricter_value(self):
        policy = {"structural_requirements": {"alignment_score_threshold": 0.8}}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(
            structural_requirements={"alignment_score_threshold": 0.5}))
        self.assertEqual(out["will_rules"]["structural_requirements"]["alignment_score_threshold"], 0.8)

    def test_charter_raises_a_lower_policy_threshold(self):
        policy = {"structural_requirements": {"alignment_score_threshold": 0.3}}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(
            structural_requirements={"alignment_score_threshold": 0.7}))
        self.assertEqual(out["will_rules"]["structural_requirements"]["alignment_score_threshold"], 0.7)

    def test_non_numeric_threshold_is_ignored_not_fatal(self):
        out = apply_charter(base_profile(), None, ai_standards=charter_with(
            structural_requirements={"alignment_score_threshold": "high"}))
        self.assertNotIn("alignment_score_threshold",
                         out["will_rules"].get("structural_requirements", {}))


class TestToolCap(unittest.TestCase):

    def test_charter_caps_when_policy_sets_none(self):
        out = apply_charter(base_profile({}), None, ai_standards=charter_with(allowed_tools=["web_search"]))
        self.assertEqual(out["will_rules"]["allowed_tools"], ["web_search"])

    def test_charter_and_policy_intersect(self):
        policy = {"allowed_tools": ["web_search", "calculator"]}
        out = apply_charter(
            base_profile(policy), None,
            ai_standards=charter_with(allowed_tools=["web_search"]),
            tool_catalog=CONNECTOR_TOOLS,
        )
        allowed = out["will_rules"]["allowed_tools"]
        self.assertEqual(set(allowed), set(expand_connectors(["web_search"])))
        self.assertNotIn("calculator", allowed)

    def test_policy_cannot_add_a_tool_the_charter_withheld(self):
        policy = {"allowed_tools": ["calculator"]}
        out = apply_charter(base_profile(policy), None, ai_standards=charter_with(allowed_tools=["web_search"]))
        self.assertEqual(out["will_rules"]["allowed_tools"], [])

    def test_cap_still_cannot_grant_beyond_what_the_agent_advertises(self):
        out = apply_charter(base_profile({}), None, ai_standards=charter_with(allowed_tools=["web_search", "calculator"]))
        effective = authorized_tools(["calculator"], out["will_rules"]["allowed_tools"])
        self.assertEqual(effective, ["calculator"])


class TestShapePromotion(unittest.TestCase):

    def test_legacy_prose_list_is_promoted_not_discarded(self):
        out = apply_charter(base_profile(["A written rule."]), None, ai_standards=charter_with(
            early_prompt_blacklist=["blocked"]))
        wr = out["will_rules"]
        self.assertIsInstance(wr, dict)
        self.assertEqual(wr["rules"], ["A written rule."])
        self.assertEqual(wr["early_prompt_blacklist"], ["blocked"])

    def test_charter_settings_do_not_disturb_the_value_split(self):
        prof = {"name": "A", "values": [], "will_rules": {}}
        charter = {"mission": "", "core_values": [
            {"name": "Care", "weight": 1.0,
             "rubric": {"scoring_guide": [{"score": 1.0, "descriptor": "ok"}]}}]}
        standards = charter_with(early_prompt_blacklist=["blocked"])
        out = apply_charter(prof, charter, policy_values=[], charter_weight=0.40, ai_standards=standards)
        self.assertEqual([v["value"] for v in out["values"]], ["Care"])
        self.assertEqual(out["will_rules"]["early_prompt_blacklist"], ["blocked"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
