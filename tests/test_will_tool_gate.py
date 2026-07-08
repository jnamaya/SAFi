"""
Unit tests for WillGate.evaluate_tool_intent (Phase 6):

- Allow-list block, read-only fast pass, deterministic approve.
- Parameter constraints default-deny: an omitted constrained parameter is a
  violation (a tool's server-side default is unvetted), not a bypass.

Run:  venv/bin/python tests/test_will_tool_gate.py
"""
import sys
import asyncio
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.faculties.will import WillGate

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

    def test_empty_allowlist_means_no_restriction(self):
        decision, _ = evaluate("some_write_tool", {}, {})
        self.assertEqual(decision, "approve")


if __name__ == "__main__":
    unittest.main(verbosity=2)
