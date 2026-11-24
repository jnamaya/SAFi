import sys
import asyncio
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.will import WillGate
from safi_app.core.faculties.synderesis import _stamp_tool_authorization
from safi_app.core.tool_connectors import CONNECTOR_TOOLS

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
        decision, reason = evaluate("web_search", {}, {"allowed_tools": []})
        self.assertEqual(decision, "violation")
        self.assertIn("not authorized", reason)

    def test_absent_allowlist_skips_check(self):
        decision, _ = evaluate("some_write_tool", {}, {})
        self.assertEqual(decision, "approve")


class TestToolAuthorizationCompile(unittest.TestCase):

    def test_advertised_tools_become_allowed_tools(self):
        p = _stamp_tool_authorization({"tools": ["web_search", "send_email"]}, CONNECTOR_TOOLS)
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news", "send_email"])

    def test_no_tools_stamps_empty_deny_all(self):
        self.assertEqual(_stamp_tool_authorization({}, CONNECTOR_TOOLS)["allowed_tools"], [])
        self.assertEqual(_stamp_tool_authorization({"tools": None}, CONNECTOR_TOOLS)["allowed_tools"], [])

    def test_policy_allowed_tools_narrows(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search", "send_email"],
            "will_rules": {"allowed_tools": ["web_search"]},
        }, CONNECTOR_TOOLS)
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])

    def test_policy_narrows_to_one_function_within_a_connector(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": {"allowed_tools": ["web_news"]},
        }, CONNECTOR_TOOLS)
        self.assertEqual(p["allowed_tools"], ["web_news"])

    def test_policy_cannot_grant_unadvertised_tools(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": {"allowed_tools": ["web_search", "delete_files"]},
        }, CONNECTOR_TOOLS)
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])
        self.assertNotIn("delete_files", p["allowed_tools"])

    def test_legacy_list_will_rules_ignored(self):
        p = _stamp_tool_authorization({
            "tools": ["web_search"],
            "will_rules": ["some legacy string rule"],
        }, CONNECTOR_TOOLS)
        self.assertEqual(p["allowed_tools"], ["web_search", "web_news"])

    def test_param_constraints_hoisted_from_will_rules(self):
        p = _stamp_tool_authorization({
            "tools": ["send_email"],
            "will_rules": {"tool_parameter_constraints": {
                "send_email": {"recipient_domain": ["example.org"]},
            }},
        }, CONNECTOR_TOOLS)
        self.assertEqual(
            p["tool_parameter_constraints"]["send_email"]["recipient_domain"],
            ["example.org"],
        )


    def test_shell_command_with_piped_regex_does_not_trigger_forbidden_exec(self):
        profile = {"allowed_tools": ["bash"]}
        cmd = "grep -n -i -E 'tool|bash|powershell|ssh|linux' /path/to/file.py | head -20"
        decision, _ = evaluate("bash", {"command": cmd}, profile)
        self.assertEqual(decision, "approve")

    def test_shell_command_with_forbidden_executable_blocked(self):
        profile = {"allowed_tools": ["bash"]}
        cmd = "ssh user@host 'ls'"
        decision, reason = evaluate("bash", {"command": cmd}, profile)
        self.assertEqual(decision, "violation")
        self.assertIn("Privileged or forbidden", reason)

    def test_shell_command_with_forbidden_path_blocked(self):
        profile = {"allowed_tools": ["bash"]}
        cmd = "cat /etc/shadow"
        decision, reason = evaluate("bash", {"command": cmd}, profile)
        self.assertEqual(decision, "violation")
        self.assertIn("Privileged or forbidden", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
