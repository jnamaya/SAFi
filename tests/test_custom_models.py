"""
Operator-added models and the deployment usage rollup (backlog 63 + 65).

The contract, pinned here:

- A custom model carries an EXPLICIT provider, and detect_provider honors it
  by exact id match before any prefix heuristic. This matters because the
  heuristics default to groq: without the override, an unrecognized id would
  silently dispatch to the wrong provider with the wrong key.
- The 60s catalog cache can be invalidated so an add/remove takes effect in
  the process that made it.
- list_models_for_org offers custom rows alongside built-ins, marked
  custom, and still filters both by configured providers.
- get_deployment_llm_usage groups usage by org across the whole install,
  including NULL-org (public bot) rows — the operator's who-spends-what.

Needs the disposable stack (it writes and deletes rows):
    docker compose -f docker-compose.test.yml run --rm tests -k custom_models
"""
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import model_routing as mr
from safi_app.core.services import provider_governance as pg


class CustomModelRouting(unittest.TestCase):

    def setUp(self):
        # An id no prefix heuristic recognizes: the default would be groq.
        self.model_id = f"custom-tune-{uuid.uuid4().hex[:8]}"
        db.add_custom_model(self.model_id, "My Fine-Tune", "anthropic")
        mr.invalidate_custom_models_cache()

    def tearDown(self):
        db.delete_custom_model(self.model_id)
        mr.invalidate_custom_models_cache()

    def test_explicit_provider_beats_the_prefix_heuristics(self):
        self.assertEqual(mr.detect_provider(self.model_id), "anthropic",
                         "custom models must route to their declared provider, "
                         "never to the groq default")

    def test_the_match_is_case_insensitive(self):
        self.assertEqual(mr.detect_provider(self.model_id.upper()), "anthropic")

    def test_builtin_heuristics_are_untouched(self):
        self.assertEqual(mr.detect_provider("claude-haiku-4-5"), "anthropic")
        self.assertEqual(mr.detect_provider("openai/gpt-oss-120b"), "groq")
        self.assertEqual(mr.detect_provider("gpt-oss-120b"), "cerebras")

    def test_removal_returns_routing_to_the_default(self):
        db.delete_custom_model(self.model_id)
        mr.invalidate_custom_models_cache()
        self.assertEqual(mr.detect_provider(self.model_id), "groq")

    def test_catalog_offers_the_custom_row_marked_custom(self):
        with mock.patch.object(pg, "configured_providers",
                               return_value=frozenset(mr.PROVIDER_METADATA)):
            models = pg.list_models_for_org(None)
        row = next((m for m in models if m["id"] == self.model_id), None)
        self.assertIsNotNone(row, "custom model missing from the catalog")
        self.assertTrue(row.get("custom"))
        self.assertEqual(row["provider"], "anthropic")
        builtin = next((m for m in models if not m.get("custom")), None)
        self.assertIsNotNone(builtin, "built-ins must survive the merge")

    def test_unconfigured_provider_hides_the_model(self):
        """A model that cannot dispatch is never offered — same rule as
        built-ins."""
        with mock.patch.object(pg, "configured_providers",
                               return_value=frozenset({"groq"})):
            models = pg.list_models_for_org(None)
        self.assertNotIn(self.model_id, [m["id"] for m in models])


class DeploymentUsageRollup(unittest.TestCase):

    def setUp(self):
        self.org_a = str(uuid.uuid4())
        self.org_b = str(uuid.uuid4())
        db.insert_llm_usage(self.org_a, "fiduciary", "intellect", "groq",
                            "llama-3.3-70b", 1000, 200)
        db.insert_llm_usage(self.org_b, "tutor", "conscience", "openai",
                            "gpt-5-mini", 500, 50)
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

    def test_every_org_and_the_public_bucket_appear(self):
        rollup = db.get_deployment_llm_usage(days=7)
        org_ids = {r["org_id"] for r in rollup["by_org_model"]}
        self.assertIn(self.org_a, org_ids)
        self.assertIn(self.org_b, org_ids)
        self.assertIn(None, org_ids,
                      "NULL-org (public bot) usage must be visible to the "
                      "operator, or shared-key spend is understated")

    def test_rows_keep_the_model_so_the_ui_can_price_them(self):
        rollup = db.get_deployment_llm_usage(days=7)
        row = next(r for r in rollup["by_org_model"] if r["org_id"] == self.org_a)
        self.assertEqual(row["model"], "llama-3.3-70b")
        self.assertEqual(row["tokens_in"], 1000)


class OperatorGateIsDeploymentConfig(unittest.TestCase):

    def test_operator_emails_come_from_config_not_roles(self):
        """The gate reads Config.SUPER_ADMIN_EMAILS (deployment config, its
        first real consumer); the source check pins that the endpoint compares
        the session email against it and 403s."""
        src = (Path(__file__).resolve().parent.parent /
               "safi_app" / "api" / "organizations.py").read_text(encoding="utf-8")
        self.assertIn("SUPER_ADMIN_EMAILS", src)
        self.assertIn("Forbidden: not a deployment operator", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
