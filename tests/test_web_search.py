import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.mcp_servers.web_search import (
    _canonical_result_url,
    _deduplicate_results,
)


class WebSearchDeduplicationTests(unittest.TestCase):
    def test_linkedin_tracking_variants_share_one_identity(self):
        first = "https://www.linkedin.com/in/Jane-Doe/?trk=abc"
        second = "http://linkedin.com/in/jane-doe#about"

        self.assertEqual(_canonical_result_url(first), _canonical_result_url(second))

    def test_keeps_first_result_and_removes_duplicate_profile(self):
        results = [
            {"title": "First", "url": "https://linkedin.com/in/jane-doe/?utm_source=x"},
            {"title": "Second", "url": "https://www.linkedin.com/in/Jane-Doe/"},
            {"title": "Other", "url": "https://linkedin.com/in/john-doe"},
        ]

        self.assertEqual(_deduplicate_results(results), [results[0], results[2]])

    def test_discards_results_without_urls(self):
        results = [{"title": "No URL", "url": ""}, {"title": "Valid", "url": "https://example.com/page"}]

        self.assertEqual(_deduplicate_results(results), [results[1]])

    def test_batch_results_are_deduplicated_across_queries(self):
        batches = [
            [{"title": "First", "url": "https://linkedin.com/in/jane-doe"}],
            [{"title": "Duplicate", "url": "https://linkedin.com/in/jane-doe/?trk=x"}],
        ]
        merged = _deduplicate_results([item for batch in batches for item in batch])

        self.assertEqual(merged, batches[0])


if __name__ == "__main__":
    unittest.main()
