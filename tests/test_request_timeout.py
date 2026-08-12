"""
The request timeout, and the two places it has to agree with.

WHY. gunicorn's `--timeout` was 120s in the entrypoint. A 50k-character document
injected into the prompt, through a slow model, can plausibly exceed two minutes,
and the ceiling is a hard cut with no useful error at the browser.

WHAT BOUNDS THE CHOICE. Apache in front of the bare-metal deployment is
`Timeout 300`, so 300 is where the proxy becomes the next limit. Raising gunicorn
past the proxy's ceiling buys nothing and hides the reason — the proxy cuts first.
The two numbers are one decision.

WHAT THIS DOES NOT FIX, and the comment must keep saying so: exceeding the timeout
kills the whole worker rather than the offending request, taking its in-flight
siblings with it. A higher ceiling makes that rarer without shrinking the blast
radius. Streaming is the actual fix for minute-long generations.

Run:  venv/bin/python tests/test_request_timeout.py
"""
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
        """Past Apache's `Timeout 300` the proxy cuts first, so the extra is
        invisible and the setting lies about what it does."""
        m = re.search(r'--timeout "\$\{SAFI_GUNICORN_TIMEOUT:-(\d+)\}"', ENTRY)
        self.assertLessEqual(int(m.group(1)), APACHE_CEILING)


class TheReasoningStaysWithIt(unittest.TestCase):

    def test_the_proxy_ceiling_is_documented_where_the_number_is(self):
        """Whoever raises this next needs to know Apache has to move too."""
        self.assertIn("Timeout 300", ENTRY)

    def test_the_worker_blast_radius_is_documented(self):
        """The dangerous misreading of this change is 'slow requests are now
        safe'. They are not — they just fail less often."""
        low = ENTRY.lower()
        self.assertIn("kills the whole worker", low)
        self.assertIn("streaming", low)


class NoStaleReferences(unittest.TestCase):

    def test_no_comment_still_claims_the_timeout_is_120(self):
        """Two comments reasoned explicitly about the 120s — it is why index
        building was moved out of the request path. A comment naming a number
        that changed is worse than none.

        Matches the CLAIM forms ("timeout 120", "runs 120s"), not the digits:
        "300s, not 120" is the changelog for this very setting and has to stay
        sayable."""
        stale = re.compile(r"(--)?timeout\s+120|runs\s+120|120\s*(s|seconds)\b", re.I)
        for line in ENTRY.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                self.assertIsNone(stale.search(stripped),
                                  f"stale timeout reference in a comment: {stripped}")

    def test_the_out_of_request_reasoning_survives(self):
        """The indexer and model warm-up moved out of the request path BECAUSE of
        a bounded timeout. Raising the ceiling does not invalidate that, and the
        explanation should still be there."""
        self.assertIn("bounded --timeout", ENTRY)
        self.assertIn("in-request", ENTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
