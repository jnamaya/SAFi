"""
Per-org LLM token usage tracking (backlog 61, Usage & Cost tab).

The contract, pinned here:

- extract_usage reads token counts from all three provider response shapes
  and never raises on a shape it does not recognize.
- Usage rows aggregate strictly per org: one org's rows never appear in
  another org's result, and NULL-org rows appear in nobody's.
- record_usage is fire-and-forget: a database failure is swallowed, because
  a usage write must never break a chat turn.
- Dollars are never stored. The table carries raw token counts only; the
  price map is display-time config.

Needs the disposable stack (it writes and deletes usage rows):
    docker compose -f docker-compose.test.yml run --rm tests -k llm_usage
"""
import sys
import unittest
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import usage_tracking as ut


class ExtractUsage(unittest.TestCase):

    def test_openai_shape(self):
        resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45))
        self.assertEqual(ut.extract_usage("openai", resp), (120, 45))

    def test_anthropic_shape(self):
        resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=300, output_tokens=80))
        self.assertEqual(ut.extract_usage("anthropic", resp), (300, 80))

    def test_gemini_output_includes_thinking_tokens(self):
        """total - prompt, not candidates alone: thinking tokens are billed
        as output and candidates_token_count excludes them."""
        resp = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=200, candidates_token_count=50, total_token_count=310))
        self.assertEqual(ut.extract_usage("gemini", resp), (200, 110))

    def test_gemini_without_total_falls_back_to_candidates(self):
        resp = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=200, candidates_token_count=50, total_token_count=None))
        self.assertEqual(ut.extract_usage("gemini", resp), (200, 50))

    def test_missing_usage_returns_none_not_an_exception(self):
        self.assertIsNone(ut.extract_usage("openai", SimpleNamespace()))
        self.assertIsNone(ut.extract_usage("anthropic", object()))
        self.assertIsNone(ut.extract_usage("gemini", None))
        self.assertIsNone(ut.extract_usage("unknown_provider", SimpleNamespace()))


class UsageRowsArePerOrg(unittest.TestCase):

    def setUp(self):
        self.org_a = str(uuid.uuid4())
        self.org_b = str(uuid.uuid4())
        db.insert_llm_usage(self.org_a, "fiduciary", "intellect", "groq",
                            "llama-3.3-70b", 1000, 200)
        db.insert_llm_usage(self.org_a, "fiduciary", "conscience", "groq",
                            "llama-3.3-70b", 800, 100)
        db.insert_llm_usage(self.org_b, "tutor", "intellect", "openai",
                            "gpt-5-mini", 500, 50)
        # NULL org: ungoverned context. Must surface in nobody's tab.
        db.insert_llm_usage(None, None, "intellect", "openai", "gpt-5-mini", 10, 5)

    def tearDown(self):
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM llm_usage WHERE org_id IN (%s, %s) OR org_id IS NULL",
                (self.org_a, self.org_b))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def test_org_a_sees_only_its_own_rows(self):
        usage = db.get_org_llm_usage(self.org_a, days=7)
        self.assertEqual(sum(r["calls"] for r in usage["by_route"]), 2)
        self.assertEqual(sum(r["tokens_in"] for r in usage["by_model"]), 1800)
        models = {r["model"] for r in usage["by_model"]}
        self.assertNotIn("gpt-5-mini", models,
                         "another org's rows leaked into this org's usage")

    def test_org_b_sees_only_its_own_rows(self):
        usage = db.get_org_llm_usage(self.org_b, days=7)
        self.assertEqual(sum(r["calls"] for r in usage["by_day"]), 1)
        self.assertEqual(usage["by_agent"][0]["agent"], "tutor")

    def test_the_route_split_separates_the_faculties(self):
        usage = db.get_org_llm_usage(self.org_a, days=7)
        routes = {r["route"]: r for r in usage["by_route"]}
        self.assertEqual(set(routes), {"intellect", "conscience"})
        self.assertEqual(routes["conscience"]["tokens_in"], 800)

    def test_no_dollar_amounts_are_stored(self):
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SHOW COLUMNS FROM llm_usage")
            cols = {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()
            conn.close()
        self.assertFalse(
            any("cost" in c or "usd" in c or "price" in c for c in cols),
            "prices go stale; the table must store raw token counts only")


class RecordUsageNeverBreaksATurn(unittest.TestCase):

    def test_db_failure_is_swallowed(self):
        with mock.patch.object(db, "insert_llm_usage", side_effect=RuntimeError("db down")):
            ut.record_usage("intellect", "groq", "llama-3.3-70b", 100, 10)

    def test_attribution_comes_from_the_context_vars(self):
        from safi_app.core.services.provider_governance import activate_org
        org = str(uuid.uuid4())
        activate_org(org)
        ut.activate_agent("fiduciary")
        captured = {}

        def fake_insert(**kwargs):
            captured.update(kwargs)

        with mock.patch.object(db, "insert_llm_usage", side_effect=fake_insert):
            ut.record_usage("conscience", "groq", "llama-3.3-70b", 100, 10)
        activate_org(None)
        ut.activate_agent(None)
        self.assertEqual(captured["org_id"], org)
        self.assertEqual(captured["agent"], "fiduciary")
        self.assertEqual(captured["route"], "conscience")


class PriceMap(unittest.TestCase):

    def test_defaults_have_prices_for_the_configured_default_models(self):
        prices = ut.get_price_map()
        for needle in ("claude-sonnet", "gpt-5-mini", "llama-3.3-70b"):
            self.assertIn(needle, prices)
            self.assertEqual(len(prices[needle]), 2)

    def test_env_override_wins_and_bad_json_is_ignored(self):
        with mock.patch.dict("os.environ", {"SAFI_LLM_PRICES": '{"my-model": [1.5, 3.0]}'}):
            prices = ut.get_price_map()
            self.assertEqual(prices["my-model"], [1.5, 3.0])
        with mock.patch.dict("os.environ", {"SAFI_LLM_PRICES": "not json"}):
            prices = ut.get_price_map()
            self.assertIn("claude-sonnet", prices)


if __name__ == "__main__":
    unittest.main(verbosity=2)
