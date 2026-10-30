"""Tests for client-side context management, response schema, and keyring fallback."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safi_cli.context import truncate_tool_results, _bound_result
from safi_cli.schema import SchemaError, normalize_turn_response
from safi_cli import config


class TestTruncation(unittest.TestCase):
    def _results(self, n, size=100, tag="r"):
        return [
            {"tool_name": "read", "arguments": {"path": f"{i}.py"}, "result": f"{tag}{i}:" + "x" * size}
            for i in range(n)
        ]

    def test_small_list_untouched(self):
        res = self._results(2)
        out = truncate_tool_results(res)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["result"], res[0]["result"])

    def test_newest_kept_verbatim_older_bounded(self):
        res = self._results(6, size=5000)
        out = truncate_tool_results(res, max_chars=1000, new_kept=3)
        self.assertEqual(len(out), 6)
        self.assertEqual(out[-1]["result"], res[-1]["result"])
        self.assertLess(len(out[0]["result"]), len(res[0]["result"]))
        self.assertIn("truncated", out[0]["result"])

    def test_entries_never_dropped_below_total_cap(self):
        res = self._results(10)
        out = truncate_tool_results(res, total_cap=60)
        self.assertEqual(len(out), 10)

    def test_overflow_summarized_in_harness_note(self):
        res = self._results(70)
        out = truncate_tool_results(res, total_cap=60)
        self.assertEqual(len(out), 61)  # 60 entries + 1 harness_note
        self.assertEqual(out[0]["tool_name"], "harness_note")
        self.assertIn("dropped", out[0]["result"])

    def test_result_ids_stable_and_unique(self):
        res = self._results(5)
        out = truncate_tool_results(res)
        ids = [e.get("result_id") for e in out if e.get("tool_name") != "harness_note"]
        self.assertEqual(len(ids), len(set(ids)))
        again = truncate_tool_results(res)
        self.assertEqual(ids, [e.get("result_id") for e in again if e.get("tool_name") != "harness_note"])

    def test_bound_result_head_tail_window(self):
        body = "A" * 400 + "B" * 400 + "C" * 200
        out = _bound_result(body, 400)
        self.assertLessEqual(len(out), 400 + 200)
        self.assertTrue(out.startswith("A"))
        self.assertTrue(out.endswith("C"))

    def test_large_write_arguments_bounded_with_head_tail(self):
        big_html = "<!DOCTYPE html>" + ("X" * 40000) + "</html>"
        res = [
            {
                "tool_name": "write",
                "arguments": {"path": "report.html", "content": big_html},
                "result": "Successfully wrote 40022 chars to report.html",
            }
        ]
        out = truncate_tool_results(res)
        self.assertEqual(out[0]["arguments"]["path"], "report.html")
        compacted_content = out[0]["arguments"]["content"]
        self.assertLess(len(compacted_content), 3500)
        self.assertTrue(compacted_content.startswith("<!DOCTYPE html>"))
        self.assertTrue(compacted_content.endswith("</html>"))
        self.assertIn("argument compacted", compacted_content)


class TestSchema(unittest.TestCase):
    def test_tool_call_batch_normalized(self):
        out = normalize_turn_response(
            {"type": "tool_call", "tool_calls": [{"tool_name": "read", "arguments": {"path": "x"}}]}
        )
        self.assertEqual(out["type"], "tool_call")
        self.assertEqual(len(out["tool_calls"]), 1)
        self.assertEqual(out["tool_calls"][0]["tool_name"], "read")
        self.assertEqual(out["tool_calls"][0]["arguments"], {"path": "x"})

    def test_single_proposal_normalized(self):
        out = normalize_turn_response({"type": "tool_call", "tool_name": "bash"})
        self.assertEqual(len(out["tool_calls"]), 1)
        self.assertEqual(out["tool_calls"][0]["tool_name"], "bash")

    def test_defaults_filled(self):
        out = normalize_turn_response({"type": "final", "finalOutput": "done"})
        self.assertEqual(out["willDecision"], "approve")
        self.assertEqual(out["tool_calls"], [])
        self.assertEqual(out["usage"], {})

    def test_non_dict_raises(self):
        with self.assertRaises(SchemaError):
            normalize_turn_response(["nope"])

    def test_payload_with_neither_type_nor_final_raises(self):
        with self.assertRaises(SchemaError):
            normalize_turn_response({"ok": False})

    def test_legacy_ok_only_payload_is_empty_final(self):
        out = normalize_turn_response({"ok": True})
        self.assertEqual(out["type"], "final")
        self.assertEqual(out["finalOutput"], "")


class TestKeyringFallback(unittest.TestCase):
    def test_save_uses_config_when_keyring_unavailable(self):
        with mock.patch.object(config, "keyring", None):
            with mock.patch.object(config, "save_config") as save, mock.patch.object(config, "load_config", return_value={}):
                config.save_agent_api_key("software_engineer", "sk-123")
            save.assert_called_once()
            saved = save.call_args[0][0]
            self.assertEqual(saved["agent_keys"]["software_engineer"], "sk-123")

    def test_save_prefers_keyring_and_scrubs_plaintext(self):
        with mock.patch.object(config, "keyring", mock.Mock()):
            with mock.patch.object(config, "_keyring_set", return_value=True) as ks:
                with mock.patch.object(config, "save_config") as save, mock.patch.object(config, "load_config", return_value={"agent_keys": {"software_engineer": "sk-old"}}):
                    config.save_agent_api_key("software_engineer", "sk-new")
            ks.assert_called_once_with("software_engineer", "sk-new")
            saved = save.call_args[0][0]
            self.assertNotIn("software_engineer", saved["agent_keys"])

    def test_resolve_prefers_keyring_over_config(self):
        with mock.patch.object(config, "_keyring_get", return_value="sk-ring"):
            with mock.patch.object(config, "load_config", return_value={"agent_keys": {"software_engineer": "sk-file"}}):
                self.assertEqual(config.resolve_agent_api_key("software_engineer"), "sk-ring")

    def test_resolve_falls_back_to_config(self):
        with mock.patch.object(config, "_keyring_get", return_value=None):
            with mock.patch.object(config, "load_config", return_value={"agent_keys": {"software_engineer": "sk-file"}}):
                self.assertEqual(config.resolve_agent_api_key("software_engineer"), "sk-file")


if __name__ == "__main__":
    unittest.main()
