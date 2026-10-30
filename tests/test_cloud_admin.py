"""Unit tests for Microsoft 365 and Azure cloud administration in SAFi CLI."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from safi_cli import cloud, tools


class TestCloudAdmin(unittest.TestCase):

    def setUp(self):
        cloud._TOKEN_CACHE.clear()

    @patch("safi_cli.cloud.load_cloud_config")
    def test_01_get_tenant_config_from_file(self, mock_load):
        mock_load.return_value = {
            "default_tenant": "corp",
            "tenants": {
                "corp": {
                    "name": "Corporate Tenant",
                    "tenant_id": "test-tenant-123",
                    "client_id": "test-client-456",
                    "client_secret": "secret-xyz",
                }
            }
        }
        tenant = cloud.get_tenant_config("corp")
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant["tenant_id"], "test-tenant-123")
        self.assertEqual(tenant["client_id"], "test-client-456")

    @patch("safi_cli.cloud.load_cloud_config")
    def test_02_get_subscription_config_from_file(self, mock_load):
        mock_load.return_value = {
            "default_subscription": "prod",
            "subscriptions": {
                "prod": {
                    "name": "Production Azure",
                    "tenant_id": "test-tenant-123",
                    "client_id": "test-client-456",
                    "client_secret": "secret-xyz",
                    "subscription_id": "sub-789",
                }
            }
        }
        sub = cloud.get_subscription_config()
        self.assertIsNotNone(sub)
        self.assertEqual(sub["subscription_id"], "sub-789")

    @patch("requests.post")
    def test_03_acquire_oauth_token_caching(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "token-abc-123",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_resp

        # First call hits network
        token1 = cloud.acquire_oauth_token("tenant-1", "client-1", "secret-1", "https://graph.microsoft.com/.default")
        self.assertEqual(token1, "token-abc-123")
        self.assertEqual(mock_post.call_count, 1)

        # Second call uses memory cache
        token2 = cloud.acquire_oauth_token("tenant-1", "client-1", "secret-1", "https://graph.microsoft.com/.default")
        self.assertEqual(token2, "token-abc-123")
        self.assertEqual(mock_post.call_count, 1)

    @patch("safi_cli.cloud.get_tenant_config")
    @patch("safi_cli.cloud.acquire_oauth_token")
    @patch("requests.get")
    def test_04_m365_list_users(self, mock_get, mock_token, mock_tenant):
        mock_tenant.return_value = {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
        }
        mock_token.return_value = "fake-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "displayName": "Alice Admin",
                    "userPrincipalName": "alice@company.com",
                    "accountEnabled": True,
                    "department": "IT",
                },
                {
                    "displayName": "Bob Builder",
                    "userPrincipalName": "bob@company.com",
                    "accountEnabled": False,
                    "department": "Engineering",
                }
            ]
        }
        mock_get.return_value = mock_resp

        out = cloud.execute_m365_admin("list_users", {"query": "alice"})
        self.assertIn("Found 2 user(s):", out)
        self.assertIn("Alice Admin <alice@company.com> [Enabled] (IT)", out)
        self.assertIn("Bob Builder <bob@company.com> [DISABLED]", out)

    @patch("safi_cli.cloud.get_tenant_config")
    @patch("safi_cli.cloud.acquire_oauth_token")
    @patch("requests.patch")
    def test_05_m365_reset_password(self, mock_patch, mock_token, mock_tenant):
        mock_tenant.return_value = {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
        }
        mock_token.return_value = "fake-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_patch.return_value = mock_resp

        out = cloud.execute_m365_admin(
            "reset_password",
            {"user_id": "alice@company.com", "temp_password": "TempPass123!"}
        )
        self.assertIn("Successfully reset password for user 'alice@company.com'", out)

    @patch("safi_cli.cloud.get_tenant_config")
    @patch("safi_cli.cloud.acquire_oauth_token")
    @patch("requests.get")
    def test_06_m365_list_licenses(self, mock_get, mock_token, mock_tenant):
        mock_tenant.return_value = {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
        }
        mock_token.return_value = "fake-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "skuPartNumber": "SPE_E5",
                    "skuId": "sku-e5-id",
                    "prepaidUnits": {"enabled": 100},
                    "consumedUnits": 85,
                }
            ]
        }
        mock_get.return_value = mock_resp

        out = cloud.execute_m365_admin("list_licenses")
        self.assertIn("Tenant Subscribed Licenses (SKUs):", out)
        self.assertIn("SPE_E5 (ID: sku-e5-id): 85/100 consumed (15 available)", out)

    @patch("safi_cli.cloud.get_subscription_config")
    @patch("safi_cli.cloud.acquire_oauth_token")
    @patch("requests.get")
    def test_07_azure_list_vms(self, mock_get, mock_token, mock_sub):
        mock_sub.return_value = {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
            "subscription_id": "sub-123",
        }
        mock_token.return_value = "fake-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "name": "web-prod-01",
                    "location": "eastus2",
                    "id": "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/web-prod-01",
                    "properties": {
                        "hardwareProfile": {"vmSize": "Standard_D4s_v5"}
                    }
                }
            ]
        }
        mock_get.return_value = mock_resp

        out = cloud.execute_azure_admin("list_vms", {"resource_group": "rg-prod"})
        self.assertIn("Virtual Machines (1):", out)
        self.assertIn("web-prod-01 (Standard_D4s_v5) in RG 'rg-prod' [eastus2]", out)

    @patch("safi_cli.cloud.get_subscription_config")
    @patch("safi_cli.cloud.acquire_oauth_token")
    @patch("requests.post")
    def test_08_azure_vm_action(self, mock_post, mock_token, mock_sub):
        mock_sub.return_value = {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
            "subscription_id": "sub-123",
        }
        mock_token.return_value = "fake-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_post.return_value = mock_resp

        out = cloud.execute_azure_admin("vm_action", {
            "resource_group": "rg-prod",
            "vm_name": "web-prod-01",
            "action": "restart"
        })
        self.assertIn("Dispatched action 'restart' on VM 'web-prod-01' in resource group 'rg-prod'", out)

    @patch("safi_cli.cloud.load_cloud_config")
    def test_09_cloud_status(self, mock_load):
        mock_load.return_value = {
            "tenants": {
                "primary": {
                    "name": "Acme Corp",
                    "tenant_id": "12345678-abcd-1234-abcd-123456789012",
                    "description": "Main M365",
                }
            },
            "subscriptions": {
                "prod": {
                    "name": "Acme Azure",
                    "subscription_id": "87654321-dcba-4321-dcba-210987654321",
                    "description": "Production",
                }
            }
        }
        out = cloud.execute_cloud_status()
        self.assertIn("SAFi Cloud Environment Status:", out)
        self.assertIn("Acme Corp", out)
        self.assertIn("Acme Azure", out)

    @patch("safi_cli.cloud.execute_m365_admin")
    def test_10_tools_execute_m365_admin(self, mock_m365):
        mock_m365.return_value = "Mocked M365 result"
        res = tools.execute_tool(
            "m365_admin",
            {"action": "list_users", "query": "test"},
            workspace_root=Path("."),
            agent="sysadmin",
        )
        self.assertEqual(res, "Mocked M365 result")
        mock_m365.assert_called_once()


if __name__ == "__main__":
    unittest.main()
