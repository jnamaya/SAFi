import sys
import logging
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.parsing_utils import (
    robust_json_parse,
    parse_intellect_response,
    parse_conscience_response,
)

log = logging.getLogger("test.parsing")

ANSWER = "What do you think removing the ether does to the status of both times?"
LATEX_BLOB = (
    '{"reflection": "Coaching: I corrected this by contrasting \\( t \\) and '
    '\\( t\' \\) rather than stating the consequence myself."}'
)


class TestRobustJsonEscapeRepair(unittest.TestCase):

    def test_latex_escapes_are_repaired(self):
        obj = robust_json_parse(LATEX_BLOB, log)
        self.assertNotIn("error", obj)
        self.assertIn("contrasting", obj["reflection"])

    def test_valid_escapes_untouched(self):
        obj = robust_json_parse('{"a": "line\\nbreak \\"quoted\\""}', log)
        self.assertEqual(obj["a"], 'line\nbreak "quoted"')

    def test_conscience_ledger_with_latex_parses(self):
        raw = ('{"evaluations": [{"value": "Textual Fidelity", "score": 1.0, '
               '"confidence": 0.9, "reason": "cites \\( E = mc^2 \\) correctly"}]}')
        ledger = parse_conscience_response(raw, log)
        self.assertEqual(ledger[0]["value"], "Textual Fidelity")


class TestReflectionNeverLeaks(unittest.TestCase):

    def test_latex_reflection_extracted_not_leaked(self):
        answer, reflection, _ = parse_intellect_response(f"{ANSWER}\n\n{LATEX_BLOB}", log)
        self.assertEqual(answer, ANSWER)
        self.assertIn("Coaching", reflection)
        self.assertNotIn('"reflection"', answer)

    def test_unparseable_blob_is_stripped_from_answer(self):
        broken = '{"reflection": "the "coaching" note said "fix it""}'
        answer, reflection, _ = parse_intellect_response(f"{ANSWER}\n\n{broken}", log)
        self.assertEqual(answer, ANSWER)
        self.assertNotIn('"reflection"', answer)
        self.assertIn("coaching", reflection)

    def test_blob_only_response_yields_empty_answer_for_retry(self):
        broken = '{"reflection": "only "a" blob"}'
        answer, _, _ = parse_intellect_response(broken, log)
        self.assertEqual(answer, "")

    def test_clean_delimiter_format_unchanged(self):
        raw = f'{ANSWER}\n---REFLECTION---\n{{"reflection": "plain note"}}'
        answer, reflection, _ = parse_intellect_response(raw, log)
        self.assertEqual(answer, ANSWER)
        self.assertEqual(reflection, "plain note")

    def test_no_reflection_at_all_unchanged(self):
        answer, reflection, _ = parse_intellect_response(ANSWER, log)
        self.assertEqual(answer, ANSWER)
        self.assertEqual(reflection, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
