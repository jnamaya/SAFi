"""
Unit tests for WillGate.evaluate_tool_intent (Phase 6):

- Allow-list block, read-only fast pass, deterministic approve.
- Empty allowed_tools is deny-all; only an absent key (a profile not built
  by synderesis.get_profile) skips the check.
- Parameter constraints default-deny: an omitted constrained parameter is a
  violation (a tool's server-side default is unvetted), not a bypass.
- _stamp_tool_authorization: advertised tools are the baseline, a policy's
  will_rules.allowed_tools can only narrow, never grant. Both lists are
  expanded from connector names to function names first, which is why
  "web_search" produces ["web_search", "web_news"] below.

Run:  venv/bin/python tests/test_will_tool_gate.py
"""
import sys
import asyncio
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.will import WillGate
from safi_app.core.faculties.synderesis import _stamp_tool_authorization

PROFILE = {
    "allowed_tools": ["send_email", "web_search"],
    "tool_parameter_constraints": {
        "send_email": {"recipient_domain": ["example.org"]},
    },
}


def gate():
    return WillGate(None, values=[], profile={})


def evaluate(tool, params, profile=PROFILE):
    return asyncio.run(gate().evaluate_tool_intent(tool, params, profile))


class TestToolGate(unittest.TestCase):

    def test_tool_not_in_allowlist_blocked(self):
        decision, reason = evaluate("delete_files", {})
        self.assertEqual(decision, "violation")
        self.assertIn("not authorized", reason)

    def test_read_only_fast_pass(self):
        decision, _ = evaluate("web_search", {"query": "anything"})
        self.assertEqual(decision, "approve")

    def test_constrained_param_with_allowed_value_approved(self):
        decision, _ = evaluate("send_email", {"recipient_domain": "example.org"})
        self.assertEqual(decision, "approve")

    def test_constrained_param_with_wrong_value_blocked(self):
        decision, reason = evaluate("send_email", {"recipient_domain": "evil.com"})
        self.assertEqual(decision, "violation")
        self.assertIn("not permitted", reason)

    def test_omitted_constrained_param_is_default_deny(self):
        # Previously an omitted param skipped the check entirely, letting the
        # tool's server-side default through unvetted.
        decision, reason = evaluate("send_email", {"subject": "hi"})
        self.assertEqual(decision, "violation")
        self.assertIn("must be provided explicitly", reason)

    def test_none_valued_constrained_param_is_default_deny(self):
        decision, _ = evaluate("send_email", {"recipient_domain": None})
        self.assertEqual(decision, "violation")

    def test_unconstrained_write_tool_approved(self):
        profile = {"allowed_tools": ["send_email"]}
        decision, _ = evaluate("send_email", {"anything": "goes"}, profile)
        self.assertEqual(decision, "approve")

    def test_empty_allowlist_denies_all(self):
        # An agent offered no tools has no legitimate tool intents — even
        # read-only ones (the allow-list check runs before the fast pass).
        decision, reason = evaluate("web_search", {}, {"allowed_tools": []})
        self.assertEqual(decision, "violation")
        self.assertIn("not authorized", reason)

    def test_absent_allowlist_skips_check(self):
        # A profile with no allowed_tools key at all wasn't built by the
        # governance compiler — legacy behavior is preserved for that case.
        decision, _ = evaluate("some_write_tool", {}, {})
        self.assertEqual(decision, "approve")


class TestToolAuthorizationCompile(unittest.TestCase):

    def test_advertised_tools_become_allowed_tools(self):
        # "web_search" is a CONNECTOR that expands to two functions. The wizard is
        # connector-level; the Will matches function names exactly; so the compiler
        # expands. See tool_connectors.py and test_tool_connector_expansion.py.
        p = _stamp_tool_authorization({"tools": ["web_search", "send_email"]})
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news", "send_email"])

    def test_no_tools_stamps_empty_deny_all(self):
        self.assertEqual(_stamp_tool_authorization({})["allowed_tools"], [])
        self.assertEqual(_stamp_tool_authorization({"tools": None})["allowed_tools"], [])

    def test_policy_allowed_tools_narrows(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search", "send_email"],
            "will_rules": {"allowed_tools": ["web_search"]},
        })
        # send_email is dropped; web_search expands on both sides of the intersection.
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])

    def test_policy_narrows_to_one_function_within_a_connector(self):
        # Expansion must not cost the ability to narrow: a policy naming a single
        # function still wins over a connector-level grant.
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": {"allowed_tools": ["web_news"]},
        })
        self.assertEqual(p["allowed_tools"], ["web_news"])

    def test_policy_cannot_grant_unadvertised_tools(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": {"allowed_tools": ["web_search", "delete_files"]},
        })
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])
        self.assertNotIn("delete_files", p["allowed_tools"])

    def test_legacy_list_will_rules_ignored(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": ["some legacy string rule"],
        })
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])

    def test_param_constraints_hoisted_from_will_rules(self):
        p = _stamp_tool_authorization({
            "tools": ["send_email"],
            "will_rules": {"tool_parameter_constraints": {
                "send_email": {"recipient_domain": ["example.org"]},
            }},
        })
        self.assertEqual(
            p["tool_parameter_constraints"]["send_email"]["recipient_domain"],
            ["example.org"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
