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
            db.delete_custom_model(m)
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
        every = {r["model_id"] for r in db.list_custom_models()}
        self.assertTrue({self.model_a, self.model_b, self.model_global} <= every)


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


    def test_the_composer_list_is_scoped(self):
        ids_a = {m["id"] for m in pg.list_models_for_org(self.org_a)}
        self.assertNotIn(self.model_b, ids_a,
                         "another org's custom model must not reach the picker")
        self.assertNotIn(self.model_b, {m["id"] for m in pg.list_models_for_org(self.org_a)})


    def test_an_operator_can_delete_a_deployment_wide_model(self):
        self.assertTrue(db.delete_custom_model(self.model_global, org_id=None))
        self.assertNotIn(self.model_global,
                         {r["model_id"] for r in db.list_custom_models()})

    def test_the_operator_scope_can_also_reach_an_orgs_row(self):
        self.assertTrue(db.delete_custom_model(self.model_a, org_id=None))


    def test_routing_still_resolves_any_registered_id(self):
        self.assertEqual(mr.detect_provider(self.model_a), "anthropic")
        self.assertEqual(mr.detect_provider(self.model_b), "anthropic")


if __name__ == "__main__":
    unittest.main()
