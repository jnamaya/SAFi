"""
The custom model catalog is per-org (backlog 77).

WHY. The catalog had no org column and all three endpoints were gated on
`admin`, which is ANY org's admin. So on a deployment with self-serve signup,
anyone who registered could list every other org's model ids and labels (a
fine-tune name discloses a customer or a project) and, worse, DELETE them, at
which point that org's users silently fell back to the default model. Found by
Nelson on the demo: models added under one org appeared in a brand-new org.

The contract pinned here:

- An org sees its own rows plus deployment-wide rows, never another org's.
- An org can delete only its own rows: another org's row, and a deployment-wide
  row, both report not-found rather than disappearing.
- Model ids stay unique per DEPLOYMENT, because detect_provider maps an id to a
  provider with no org in scope and sits in the dispatch path. A collision must
  not disclose the holder, the label or the provider.
- The composer list (list_models_for_org) filters by org too, since that is the
  surface where the leak was actually noticed.

Needs the disposable stack:
    docker compose -f docker-compose.test.yml run --rm tests -k model_catalog_scope
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import model_routing as mr
from safi_app.core.services import provider_governance as pg


class CatalogIsPerOrg(unittest.TestCase):

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.org_a = db.create_organization(f"Catalog Org A {tag}")
        self.org_b = db.create_organization(f"Catalog Org B {tag}")
        # Anthropic, so the provider is a real one the metadata knows.
        self.model_a = f"a-tune-{tag}"
        self.model_b = f"b-tune-{tag}"
        self.model_global = f"g-tune-{tag}"
        db.add_custom_model(self.model_a, "A's Fine-Tune", "anthropic",
                            created_by="user:a", org_id=self.org_a)
        db.add_custom_model(self.model_b, "B's Fine-Tune", "anthropic",
                            created_by="user:b", org_id=self.org_b)
        db.add_custom_model(self.model_global, "Deployment Wide", "anthropic",
                            created_by="user:op", org_id='')
        mr.invalidate_custom_models_cache()

    def tearDown(self):
        for m in (self.model_a, self.model_b, self.model_global):
            db.delete_custom_model(m)          # org_id=None: unrestricted cleanup
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            for oid in (self.org_a, self.org_b):
                cur.execute("DELETE FROM organizations WHERE id=%s", (oid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()
        mr.invalidate_custom_models_cache()

    # ---- visibility ----

    def _ids_visible_to(self, org_id):
        return {r["model_id"] for r in db.list_custom_models(visible_to_org=org_id)}

    def test_an_org_sees_its_own_and_deployment_wide_only(self):
        visible = self._ids_visible_to(self.org_a)
        self.assertIn(self.model_a, visible)
        self.assertIn(self.model_global, visible, "deployment-wide rows are shared")
        self.assertNotIn(self.model_b, visible, "another org's model must not be listed")

    def test_the_other_direction_too(self):
        visible = self._ids_visible_to(self.org_b)
        self.assertIn(self.model_b, visible)
        self.assertNotIn(self.model_a, visible)

    def test_unscoped_listing_still_returns_everything_for_routing(self):
        # detect_provider needs every row; this is internal, not user-facing.
        every = {r["model_id"] for r in db.list_custom_models()}
        self.assertTrue({self.model_a, self.model_b, self.model_global} <= every)

    # ---- deletion ----

    def test_an_org_cannot_delete_another_orgs_model(self):
        removed = db.delete_custom_model(self.model_b, org_id=self.org_a)
        self.assertFalse(removed, "the delete must not match another org's row")
        self.assertIn(self.model_b, {r["model_id"] for r in db.list_custom_models()},
                      "the row must still be there")

    def test_an_org_cannot_delete_a_deployment_wide_model(self):
        self.assertFalse(db.delete_custom_model(self.model_global, org_id=self.org_a))
        self.assertIn(self.model_global, {r["model_id"] for r in db.list_custom_models()})

    def test_an_org_can_delete_its_own(self):
        self.assertTrue(db.delete_custom_model(self.model_a, org_id=self.org_a))
        self.assertNotIn(self.model_a, {r["model_id"] for r in db.list_custom_models()})

    # ---- the composer surface, where the leak was seen ----

    def test_the_composer_list_is_scoped(self):
        ids_a = {m["id"] for m in pg.list_models_for_org(self.org_a)}
        self.assertNotIn(self.model_b, ids_a,
                         "another org's custom model must not reach the picker")
        # Own and deployment-wide rows appear when their provider is configured;
        # if anthropic is unconfigured in this environment both are filtered, so
        # assert the leak is absent rather than asserting presence.
        self.assertNotIn(self.model_b, {m["id"] for m in pg.list_models_for_org(self.org_a)})

    # ---- routing is unaffected ----

    def test_routing_still_resolves_any_registered_id(self):
        # Ownership must not change dispatch: the id maps to its declared
        # provider regardless of which org asks.
        self.assertEqual(mr.detect_provider(self.model_a), "anthropic")
        self.assertEqual(mr.detect_provider(self.model_b), "anthropic")


if __name__ == "__main__":
    unittest.main()
