"""
Per-org provider API keys (backlog 64): BYOK layered over .env.

The contract, pinned here:

- A stored key is Fernet-encrypted at rest; the display read path returns
  provider + last4 only and can never leak the key; the dispatch read path
  decrypts.
- The overlay is per org: org B never sees org A's keys, and no org context
  means no override (deployment default).
- LLMProvider prefers a client bound to the active org's key, and can build
  one for a provider that has NO deployment key at all — that is what makes
  org-only providers work.
- The model catalog treats an org-key provider as configured, so its models
  are offered to that org even when the deployment has no .env key.

Needs the disposable stack (it writes and deletes rows):
    docker compose -f docker-compose.test.yml run --rm tests -k provider_keys
"""
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.core.services import org_keys as ok
from safi_app.core.services import provider_governance as pg
from safi_app.core.services.provider_governance import activate_org


class KeysAreEncryptedAndWriteOnly(unittest.TestCase):

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.key = "sk-test-" + uuid.uuid4().hex
        db.set_org_provider_key(self.org, "anthropic", self.key, updated_by="tester")
        ok.invalidate_org_keys_cache(self.org)

    def tearDown(self):
        db.delete_org_provider_key(self.org, "anthropic")
        ok.invalidate_org_keys_cache()
        activate_org(None)

    def test_the_display_read_never_carries_the_key(self):
        rows = db.list_org_provider_keys(self.org)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "anthropic")
        self.assertEqual(rows[0]["last4"], self.key[-4:])
        self.assertNotIn("key_enc", rows[0])
        self.assertNotIn(self.key, str(rows[0]))

    def test_the_stored_column_is_ciphertext(self):
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT key_enc FROM org_provider_keys WHERE org_id=%s", (self.org,))
            stored = cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()
        self.assertNotEqual(stored, self.key)
        self.assertNotIn(self.key, stored,
                         "the key must never persist in plaintext")

    def test_the_dispatch_read_decrypts(self):
        self.assertEqual(
            db.get_org_provider_keys_decrypted(self.org),
            {"anthropic": self.key})

    def test_replace_updates_in_place(self):
        new_key = "sk-test-" + uuid.uuid4().hex
        db.set_org_provider_key(self.org, "anthropic", new_key)
        self.assertEqual(
            db.get_org_provider_keys_decrypted(self.org)["anthropic"], new_key)
        self.assertEqual(len(db.list_org_provider_keys(self.org)), 1)

    def test_isolation_between_orgs_and_without_context(self):
        other = str(uuid.uuid4())
        self.assertEqual(ok.org_key_map(other), {})
        self.assertIsNone(ok.org_key_map(None) or None)
        activate_org(None)
        self.assertIsNone(ok.active_org_key("anthropic"),
                          "no org context must mean deployment default")

    def test_active_org_key_resolves_through_the_contextvar(self):
        activate_org(self.org)
        ok.invalidate_org_keys_cache(self.org)
        self.assertEqual(ok.active_org_key("anthropic"), self.key)
        self.assertIsNone(ok.active_org_key("groq"),
                          "a provider without a stored key uses the default")


class DispatchPrefersTheOrgClient(unittest.TestCase):

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.key = "sk-live-" + uuid.uuid4().hex
        # anthropic deliberately has NO deployment key in this config: the
        # org's key must be sufficient on its own.
        from safi_app.core.services.llm_provider import LLMProvider
        self.provider = LLMProvider({
            "providers": {
                "anthropic": {"type": "anthropic", "api_key": None},
                "groq": {"type": "openai", "api_key": "deploy-groq-key",
                         "base_url": "https://api.groq.com/openai/v1"},
            },
            "routes": {},
        })
        db.set_org_provider_key(self.org, "anthropic", self.key)
        ok.invalidate_org_keys_cache(self.org)
        activate_org(self.org)

    def tearDown(self):
        db.delete_org_provider_key(self.org, "anthropic")
        ok.invalidate_org_keys_cache()
        activate_org(None)

    def test_org_key_builds_a_client_where_the_deployment_has_none(self):
        client = self.provider._org_override_client(
            "anthropic", {"type": "anthropic"})
        self.assertIsNotNone(client, "org-only providers must dispatch")
        self.assertEqual(client.api_key, self.key)

    def test_no_stored_key_means_no_override(self):
        self.assertIsNone(self.provider._org_override_client(
            "groq", {"type": "openai", "base_url": "https://api.groq.com/openai/v1"}))

    def test_no_org_context_means_no_override(self):
        activate_org(None)
        self.assertIsNone(self.provider._org_override_client(
            "anthropic", {"type": "anthropic"}))

    def test_a_rotated_key_gets_a_fresh_client(self):
        first = self.provider._org_override_client("anthropic", {"type": "anthropic"})
        new_key = "sk-live-" + uuid.uuid4().hex
        db.set_org_provider_key(self.org, "anthropic", new_key)
        ok.invalidate_org_keys_cache(self.org)
        second = self.provider._org_override_client("anthropic", {"type": "anthropic"})
        self.assertIsNot(first, second)
        self.assertEqual(second.api_key, new_key)


class OrgKeyProvidersExtendTheCatalog(unittest.TestCase):

    def setUp(self):
        self.org = str(uuid.uuid4())
        db.set_org_provider_key(self.org, "anthropic", "sk-test-" + uuid.uuid4().hex)
        ok.invalidate_org_keys_cache(self.org)

    def tearDown(self):
        db.delete_org_provider_key(self.org, "anthropic")
        ok.invalidate_org_keys_cache()

    def test_models_appear_for_an_org_key_only_provider(self):
        """Deployment has no keys at all (mocked empty); the org's anthropic
        key alone must surface the built-in Claude model."""
        with mock.patch.object(pg, "configured_providers", return_value=frozenset()):
            models = pg.list_models_for_org(self.org)
        providers = {m["provider"] for m in models}
        self.assertEqual(providers, {"anthropic"})
        other = str(uuid.uuid4())
        with mock.patch.object(pg, "configured_providers", return_value=frozenset()):
            self.assertEqual(pg.list_models_for_org(other), [],
                             "another org must not inherit the key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
