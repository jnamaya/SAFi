import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENTRY = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")

APACHE_CEILING = 300


class TheTimeoutIsRaisedAndTunable(unittest.TestCase):

    def test_the_literal_120_is_gone(self):
        self.assertNotIn("--timeout 120", ENTRY)

    def test_it_reads_an_env_var_with_a_default(self):
        m = re.search(r'--timeout "\$\{SAFI_GUNICORN_TIMEOUT:-(\d+)\}"', ENTRY)
        self.assertIsNotNone(m, "the timeout should be env-tunable without an edit")
        self.assertGreaterEqual(int(m.group(1)), 300)

    def test_the_default_does_not_exceed_the_proxy_ceiling(self):
        m = re.search(r'--timeout "\$\{SAFI_GUNICORN_TIMEOUT:-(\d+)\}"', ENTRY)
        self.assertLessEqual(int(m.group(1)), APACHE_CEILING)

    def test_keepalive_is_configured_and_tunable(self):
        m = re.search(r'--keep-alive "\$\{SAFI_GUNICORN_KEEPALIVE:-(\d+)\}"', ENTRY)
        self.assertIsNotNone(m, "keepalive should be env-tunable")
        self.assertGreaterEqual(int(m.group(1)), 60)


class TheReasoningStaysWithIt(unittest.TestCase):

    def test_the_proxy_ceiling_is_documented_where_the_number_is(self):
        self.assertIn("Timeout 300", ENTRY)

    def test_the_worker_blast_radius_is_documented(self):
        low = ENTRY.lower()
        self.assertIn("kills the whole worker", low)
        self.assertIn("streaming", low)


class NoStaleReferences(unittest.TestCase):

    def test_no_comment_still_claims_the_timeout_is_120(self):
        stale = re.compile(r"(--)?timeout\s+120|runs\s+120|120\s*(s|seconds)\b", re.I)
        for line in ENTRY.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                self.assertIsNone(stale.search(stripped),
                                  f"stale timeout reference in a comment: {stripped}")

    def test_the_out_of_request_reasoning_survives(self):
        self.assertIn("bounded --timeout", ENTRY)
        self.assertIn("in-request", ENTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
