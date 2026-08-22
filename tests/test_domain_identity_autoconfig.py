"""
A DNS-verified domain auto-populates the login restriction (backlog 52
follow-up), instead of leaving google_hd/ms_tenant_id for the admin to set
by hand after already proving ownership via TXT record.

WHY. domain_verified gates nothing on its own in single-tenant deployments —
_resolve_single_tenant_membership never looks at it. google_hd/ms_tenant_id
are what _org_claim_gate actually checks, on every tenancy mode. Populating
them at verification time is what makes "verify your domain" actually
restrict who can log in, rather than being a purely cosmetic step.

Each field is only set when there is a real signal the domain is hosted
there: Google's hosted-domain claim has no per-domain discovery endpoint, so
_domain_uses_google_workspace checks MX records instead; Microsoft's tenant
id is a GUID that _discover_ms_tenant_id resolves via the standard,
unauthenticated OIDC discovery lookup. A domain on neither (a third-party
mail host) must get neither field set — there's nothing to restrict against
on a provider nobody at that org will ever log in through.

Needs the disposable stack:
    docker compose -f docker-compose.test.yml run --rm tests -k domain_identity_autoconfig
"""
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.api import organizations as orgs_api

from support import login_as, new_user


class _FakeMxAnswer:
    def __init__(self, exchange):
        self.exchange = exchange


class GoogleWorkspaceDetection(unittest.TestCase):

    @patch('dns.resolver.resolve')
    def test_google_mx_records_are_detected(self, mock_resolve):
        mock_resolve.return_value = [_FakeMxAnswer('aspmx.l.google.com.')]
        self.assertTrue(orgs_api._domain_uses_google_workspace('example.com'))

    @patch('dns.resolver.resolve')
    def test_googlemail_mx_variant_is_detected(self, mock_resolve):
        mock_resolve.return_value = [_FakeMxAnswer('alt1.aspmx.googlemail.com.')]
        self.assertTrue(orgs_api._domain_uses_google_workspace('example.com'))

    @patch('dns.resolver.resolve')
    def test_non_google_mx_is_not_detected(self, mock_resolve):
        mock_resolve.return_value = [_FakeMxAnswer('mail.protection.outlook.com.')]
        self.assertFalse(orgs_api._domain_uses_google_workspace('example.com'))

    @patch('dns.resolver.resolve')
    def test_a_lookup_failure_is_treated_as_not_google(self, mock_resolve):
        mock_resolve.side_effect = Exception('NXDOMAIN')
        self.assertFalse(orgs_api._domain_uses_google_workspace('example.com'))


class MicrosoftTenantDiscovery(unittest.TestCase):

    @patch('requests.get')
    def test_a_real_tenant_guid_is_extracted(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            "issuer": "https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0"
        })
        self.assertEqual(
            orgs_api._discover_ms_tenant_id('example.com'),
            '72f988bf-86f1-41af-91ab-2d7cd011db47')

    @patch('requests.get')
    def test_a_non_200_response_is_not_on_microsoft(self, mock_get):
        mock_get.return_value = MagicMock(status_code=400, json=lambda: {"error": "invalid_tenant"})
        self.assertIsNone(orgs_api._discover_ms_tenant_id('example.com'))

    @patch('requests.get')
    def test_a_malformed_issuer_is_rejected(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"issuer": "not-a-url"})
        self.assertIsNone(orgs_api._discover_ms_tenant_id('example.com'))

    @patch('requests.get')
    def test_a_network_failure_is_not_on_microsoft(self, mock_get):
        mock_get.side_effect = Exception('connection refused')
        self.assertIsNone(orgs_api._discover_ms_tenant_id('example.com'))


class VerificationAutoConfiguresIdentity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.domain = f"autocfg{tag}.example"
        self.org_id = db.create_organization(f"Autoconfig Org {tag}")
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE organizations SET domain_to_verify=%s, verification_token=%s WHERE id=%s",
                (self.domain, "safi-verification=test-token", self.org_id),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        self.admin = f"autocfg-admin-{tag}"
        new_user(user_id=self.admin, org_id=self.org_id, role="admin")
        self.client = self.app.test_client()
        login_as(self.client, self.admin, "admin", org_id=self.org_id)

    def tearDown(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE users SET org_id=NULL WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM auth_events WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM organizations WHERE id=%s", (self.org_id,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _verify_with(self, mx_exchange, ms_status, ms_issuer):
        with patch('dns.resolver.resolve') as mock_resolve, \
             patch('requests.get') as mock_get:
            def resolve_side_effect(domain, rdtype):
                if rdtype == 'TXT':
                    return [MagicMock(to_text=lambda: '"safi-verification=test-token"')]
                return [_FakeMxAnswer(mx_exchange)] if mx_exchange else []
            mock_resolve.side_effect = resolve_side_effect
            mock_get.return_value = MagicMock(status_code=ms_status, json=lambda: {"issuer": ms_issuer})
            return self.client.post('/api/organizations/domain/verify', json={"org_id": self.org_id})

    def test_a_google_workspace_domain_gets_google_hd_set(self):
        res = self._verify_with('aspmx.l.google.com.', 400, '')
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['identity_configured'], {"google_hd": self.domain})
        cfg = db.get_org_identity_config(self.org_id)
        self.assertEqual(cfg['google_hd'], self.domain)
        self.assertIsNone(cfg['ms_tenant_id'])

    def test_a_microsoft_tenant_domain_gets_ms_tenant_id_set(self):
        guid = '72f988bf-86f1-41af-91ab-2d7cd011db47'
        res = self._verify_with(None, 200, f'https://login.microsoftonline.com/{guid}/v2.0')
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['identity_configured'], {"ms_tenant_id": guid})
        cfg = db.get_org_identity_config(self.org_id)
        self.assertEqual(cfg['ms_tenant_id'], guid)
        self.assertIsNone(cfg['google_hd'])

    def test_a_domain_on_neither_provider_gets_nothing_set(self):
        res = self._verify_with('mail.protection.outlook.com.', 400, '')
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['identity_configured'], {})
        cfg = db.get_org_identity_config(self.org_id)
        self.assertIsNone(cfg['google_hd'])
        self.assertIsNone(cfg['ms_tenant_id'])


if __name__ == "__main__":
    unittest.main()
