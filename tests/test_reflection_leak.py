"""
Unit tests for the reflection-leak fix in parsing_utils.

Regression guard for 2026-07-11: the Intellect appends {"reflection": "..."}
after its answer, but math-heavy reflections contain LaTeX markers (\\( t \\),
\\alpha) that are invalid JSON escapes. json.loads rejected the blob, every
strategy failed, and the Strategy-3 fallback shipped the RAW text — reflection
blob included, sometimes quoting internal reflexion-retry coaching — to the
frontend. Two layers now prevent this:
  1. robust_json_parse repairs invalid escape sequences and retries, and
  2. parse_intellect_response Strategy 3 strips an unparseable reflection
     blob from the answer instead of ever shipping it.

Run:  venv/bin/python tests/test_reflection_leak.py
"""
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
        # Broken beyond repair: unescaped inner quotes.
        broken = '{"reflection": "the "coaching" note said "fix it""}'
        answer, reflection, _ = parse_intellect_response(f"{ANSWER}\n\n{broken}", log)
        self.assertEqual(answer, ANSWER)
        self.assertNotIn('"reflection"', answer)
        self.assertIn("coaching", reflection)

    def test_blob_only_response_yields_empty_answer_for_retry(self):
        # Whole message is an unparseable blob: answer must come back empty
        # (run_intellect resamples on contentless) — not the raw blob.
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
