"""
Unit tests for tool call salvage parsing in parsing_utils.

Guards against regressions when open-source LLMs (such as Qwen 2.5 / Hermes)
leak internal XML tool calling tokens (<tool_call><function=...><parameter=...>...</tool_call>)
or embedded JSON into message text during deep-context attention drift.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.parsing_utils import parse_tool_calls_from_text


class TestToolCallSalvage(unittest.TestCase):

    def test_empty_or_plain_text(self):
        self.assertEqual(parse_tool_calls_from_text(""), [])
        self.assertEqual(parse_tool_calls_from_text(None), [])
        self.assertEqual(
            parse_tool_calls_from_text("Hello, how can I help you today?"), []
        )
        self.assertEqual(
            parse_tool_calls_from_text("Just mentioning <xml> tags without tool_call"),
            [],
        )

    def test_single_xml_tool_call(self):
        raw = (
            "<tool_call>\n"
            "<function=bash>\n"
            "<parameter=command>pytest tests/test_core.py</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "bash")
        self.assertEqual(calls[0]["arguments"], {"command": "pytest tests/test_core.py"})
        self.assertTrue(calls[0]["id"].startswith("call_salvage_"))

    def test_xml_with_attribute_syntax(self):
        raw = (
            '<tool_call>\n'
            '<function name="read_file">\n'
            '<parameter name="path">/var/log/syslog</parameter>\n'
            '</function>\n'
            '</tool_call>'
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["arguments"], {"path": "/var/log/syslog"})

    def test_xml_with_single_quotes(self):
        raw = (
            "<tool_call>\n"
            "<function name='fetch_url'>\n"
            "<parameter name='url'>https://example.com/api</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "fetch_url")
        self.assertEqual(calls[0]["arguments"], {"url": "https://example.com/api"})

    def test_multiple_parameters(self):
        raw = (
            "<tool_call>\n"
            "<function=edit_file>\n"
            "<parameter=path>/tmp/test.txt</parameter>\n"
            "<parameter=old_string>foo</parameter>\n"
            "<parameter=new_string>bar</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "edit_file")
        self.assertEqual(
            calls[0]["arguments"],
            {
                "path": "/tmp/test.txt",
                "old_string": "foo",
                "new_string": "bar",
            },
        )

    def test_unclosed_xml_tags(self):
        # Format drift occasionally omits closing </parameter> or </function>
        raw = (
            "<tool_call>\n"
            "<function=bash>\n"
            "<parameter=command>cat /etc/hosts\n"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "bash")
        self.assertEqual(calls[0]["arguments"], {"command": "cat /etc/hosts"})

    def test_embedded_json_in_tool_call(self):
        raw = (
            '<tool_call>\n'
            '{"name": "database_query", "arguments": {"query": "SELECT 1;", "limit": 10}}\n'
            '</tool_call>'
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "database_query")
        self.assertEqual(
            calls[0]["arguments"],
            {"query": "SELECT 1;", "limit": 10},
        )

    def test_embedded_json_alternate_keys(self):
        # Testing "function" and "parameters" keys
        raw = (
            '<tool_call>\n'
            '{"function": "search_docs", "parameters": {"q": "tamper evident"}}\n'
            '</tool_call>'
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "search_docs")
        self.assertEqual(calls[0]["arguments"], {"q": "tamper evident"})

    def test_json_value_inside_xml_parameter(self):
        # Parameters that serialize arrays or objects
        raw = (
            "<tool_call>\n"
            "<function=batch_run>\n"
            "<parameter=items>[1, 2, 3]</parameter>\n"
            "<parameter=options>{\"force\": true}</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "batch_run")
        self.assertEqual(calls[0]["arguments"]["items"], [1, 2, 3])
        self.assertEqual(calls[0]["arguments"]["options"], {"force": True})

    def test_multiple_consecutive_tool_calls(self):
        raw = (
            "I will check both files now.\n"
            "<tool_call>\n"
            "<function=read_file><parameter=path>file_a.txt</parameter></function>\n"
            "</tool_call>\n"
            "<tool_call>\n"
            "<function=read_file><parameter=path>file_b.txt</parameter></function>\n"
            "</tool_call>\n"
            "Waiting for the results."
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["arguments"], {"path": "file_a.txt"})
        self.assertEqual(calls[1]["name"], "read_file")
        self.assertEqual(calls[1]["arguments"], {"path": "file_b.txt"})

    def test_mini_pc_exact_reproduction(self):
        # Exact reproduction of the leaked format observed on the Mini-PC
        raw = (
            "<tool_call>\n"
            "<function=bash>\n"
            "<parameter=command>grep -rn 'audit' /var/www/safi/safi_app/</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )
        calls = parse_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "bash")
        self.assertEqual(
            calls[0]["arguments"]["command"],
            "grep -rn 'audit' /var/www/safi/safi_app/",
        )


if __name__ == "__main__":
    unittest.main()
