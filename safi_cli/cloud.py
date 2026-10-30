"""Microsoft 365 and Azure Cloud administration module for SAFi CLI.

Provides governed, credential-safe administration across Microsoft 365 (Entra ID,
licenses, users, sign-in logs) and Azure Resource Manager (VMs, resource groups, resources)
without leaking secrets into the model context.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

from . import ui

logger = logging.getLogger("safi.cloud")

CONFIG_DIR = Path.home() / ".config" / "safi"
CLOUD_CONFIG_FILE = CONFIG_DIR / "cloud.json"

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
ARM_ENDPOINT = "https://management.azure.com"
LOGIN_ENDPOINT = "https://login.microsoftonline.com"

# In-memory token cache: {(tenant_id, scope): (token, expires_at)}
_TOKEN_CACHE: Dict[Tuple[str, str], Tuple[str, float]] = {}


def ensure_cloud_config_dir() -> Path:
    """Ensure ~/.config/safi exists with 0700 permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    return CONFIG_DIR


def load_cloud_config() -> Dict[str, Any]:
    """Load cloud configurations from ~/.config/safi/cloud.json."""
    if not CLOUD_CONFIG_FILE.exists():
        return {}
    try:
        with open(CLOUD_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load cloud config: %s", exc)
        return {}


def save_cloud_config(config: Dict[str, Any]) -> None:
    """Save cloud configurations to ~/.config/safi/cloud.json with 0600 permissions."""
    ensure_cloud_config_dir()
    CLOUD_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        os.chmod(CLOUD_CONFIG_FILE, 0o600)
    except OSError:
        pass


def get_tenant_config(tenant_alias: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Resolve M365 / Entra ID tenant config from cloud.json or environment."""
    cfg = load_cloud_config()
    tenants = cfg.get("tenants", {})

    if tenant_alias and tenant_alias in tenants:
        return tenants[tenant_alias]

    # Check default tenant
    default_alias = cfg.get("default_tenant")
    if default_alias and default_alias in tenants:
        return tenants[default_alias]

    # Pick first configured tenant if any
    if tenants:
        first_key = next(iter(tenants))
        return tenants[first_key]

    # Environment fallback
    tenant_id = os.environ.get("AZURE_TENANT_ID") or os.environ.get("M365_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID") or os.environ.get("M365_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET") or os.environ.get("M365_CLIENT_SECRET")

    if tenant_id and client_id and client_secret:
        return {
            "name": "env-tenant",
            "tenant_id": tenant_id.strip(),
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "description": "Configured via environment variables",
        }

    return None


def get_subscription_config(sub_alias: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Resolve Azure subscription config from cloud.json or environment."""
    cfg = load_cloud_config()
    subs = cfg.get("subscriptions", {})

    if sub_alias and sub_alias in subs:
        return subs[sub_alias]

    # Check default subscription
    default_alias = cfg.get("default_subscription")
    if default_alias and default_alias in subs:
        return subs[default_alias]

    # Pick first configured subscription
    if subs:
        first_key = next(iter(subs))
        return subs[first_key]

    # Environment fallback
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID")

    if tenant_id and client_id and client_secret and sub_id:
        return {
            "name": "env-azure",
            "tenant_id": tenant_id.strip(),
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "subscription_id": sub_id.strip(),
            "description": "Configured via environment variables",
        }

    return None


def acquire_oauth_token(tenant_id: str, client_id: str, client_secret: str, scope: str) -> str:
    """Acquire an OAuth2 bearer token using client_credentials grant with local memory caching."""
    cache_key = (tenant_id, scope)
    now = time.time()
    if cache_key in _TOKEN_CACHE:
        token, expires_at = _TOKEN_CACHE[cache_key]
        if now < expires_at - 60:  # 60s buffer
            return token

    url = f"{LOGIN_ENDPOINT}/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
    }

    resp = requests.post(url, data=payload, timeout=15)
    if resp.status_code != 200:
        err_msg = f"OAuth token request failed ({resp.status_code}): {resp.text}"
        try:
            err_json = resp.json()
            err_msg = f"OAuth error: {err_json.get('error_description', err_json.get('error', resp.text))}"
        except Exception:
            pass
        raise ConnectionError(err_msg)

    data = resp.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    _TOKEN_CACHE[cache_key] = (token, now + expires_in)
    return token


# --- Microsoft 365 Operations ---

def execute_m365_admin(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    tenant_alias: Optional[str] = None,
) -> str:
    """Execute a governed Microsoft 365 / Entra ID operation."""
    p = params or {}
    tenant = get_tenant_config(tenant_alias)
    if not tenant:
        return (
            "Error: No Microsoft 365 / Entra ID tenant configured.\n"
            "Run '/setup-cloud' or 'safi setup-cloud' in the terminal to configure your tenant credentials."
        )

    try:
        token = acquire_oauth_token(
            tenant_id=tenant["tenant_id"],
            client_id=tenant["client_id"],
            client_secret=tenant["client_secret"],
            scope="https://graph.microsoft.com/.default",
        )
    except Exception as exc:
        return f"Authentication Error: Could not connect to Microsoft 365 tenant: {exc}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    action_clean = action.strip().lower()

    try:
        if action_clean in ("list_users", "users"):
            query = p.get("query") or p.get("search") or ""
            limit = min(int(p.get("limit") or 25), 100)
            url = f"{GRAPH_ENDPOINT}/users?$top={limit}&$select=id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department"
            if query:
                url += f"&$filter=startswith(displayName,'{query}') or startswith(userPrincipalName,'{query}') or startswith(mail,'{query}')"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing users ({resp.status_code}): {resp.text}"
            users = resp.json().get("value", [])
            if not users:
                return "No users found matching query."
            lines = [f"Found {len(users)} user(s):"]
            for u in users:
                status = "Enabled" if u.get("accountEnabled") else "DISABLED"
                dept = f" ({u.get('department')})" if u.get("department") else ""
                lines.append(f"- {u.get('displayName')} <{u.get('userPrincipalName')}> [{status}]{dept}")
            return "\n".join(lines)

        elif action_clean in ("get_user", "user"):
            user_id = p.get("user_id") or p.get("upn") or p.get("email")
            if not user_id:
                return "Error: 'user_id' (email or User Principal Name) is required."
            url = f"{GRAPH_ENDPOINT}/users/{user_id}?$select=id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department,officeLocation,createdDateTime,assignedLicenses"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 404:
                return f"User '{user_id}' not found in tenant."
            if resp.status_code != 200:
                return f"Error getting user ({resp.status_code}): {resp.text}"
            u = resp.json()
            lines = [
                f"User Profile: {u.get('displayName')}",
                f"  UPN: {u.get('userPrincipalName')}",
                f"  Mail: {u.get('mail') or 'N/A'}",
                f"  Status: {'Active / Enabled' if u.get('accountEnabled') else 'DISABLED'}",
                f"  Title: {u.get('jobTitle') or 'N/A'}",
                f"  Department: {u.get('department') or 'N/A'}",
                f"  Office: {u.get('officeLocation') or 'N/A'}",
                f"  Created: {u.get('createdDateTime') or 'N/A'}",
                f"  Assigned Licenses: {len(u.get('assignedLicenses', []))}",
            ]
            return "\n".join(lines)

        elif action_clean in ("reset_password", "password_reset"):
            user_id = p.get("user_id") or p.get("upn") or p.get("email")
            temp_password = p.get("temp_password") or p.get("password")
            force_change = p.get("force_change", True)
            if not user_id:
                return "Error: 'user_id' (UPN or email) is required."
            if not temp_password:
                return "Error: 'temp_password' is required."

            url = f"{GRAPH_ENDPOINT}/users/{user_id}"
            body = {
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": force_change,
                    "password": temp_password,
                }
            }
            resp = requests.patch(url, headers=headers, json=body, timeout=20)
            if resp.status_code not in (200, 204):
                return f"Error resetting password ({resp.status_code}): {resp.text}"
            return (
                f"✓ Successfully reset password for user '{user_id}'.\n"
                f"Temporary password set. (Must change on next login: {force_change})"
            )

        elif action_clean in ("list_licenses", "licenses"):
            url = f"{GRAPH_ENDPOINT}/subscribedSkus"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing licenses ({resp.status_code}): {resp.text}"
            skus = resp.json().get("value", [])
            if not skus:
                return "No license subscriptions found."
            lines = ["Tenant Subscribed Licenses (SKUs):"]
            for s in skus:
                part = s.get("skuPartNumber", "Unknown")
                sku_id = s.get("skuId", "")
                enabled = s.get("prepaidUnits", {}).get("enabled", 0)
                consumed = s.get("consumedUnits", 0)
                available = max(0, enabled - consumed)
                lines.append(f"- {part} (ID: {sku_id}): {consumed}/{enabled} consumed ({available} available)")
            return "\n".join(lines)

        elif action_clean in ("assign_license", "revoke_license"):
            user_id = p.get("user_id") or p.get("upn") or p.get("email")
            sku_id = p.get("sku_id")
            if not user_id or not sku_id:
                return "Error: Both 'user_id' and 'sku_id' are required."
            url = f"{GRAPH_ENDPOINT}/users/{user_id}/assignLicense"
            if action_clean == "assign_license":
                body = {
                    "addLicenses": [{"skuId": sku_id}],
                    "removeLicenses": [],
                }
                action_label = "assigned"
            else:
                body = {
                    "addLicenses": [],
                    "removeLicenses": [sku_id],
                }
                action_label = "revoked"

            resp = requests.post(url, headers=headers, json=body, timeout=20)
            if resp.status_code not in (200, 204):
                return f"Error updating license ({resp.status_code}): {resp.text}"
            return f"✓ Successfully {action_label} license '{sku_id}' for '{user_id}'."

        elif action_clean in ("list_groups", "groups"):
            query = p.get("query") or p.get("search") or ""
            limit = min(int(p.get("limit") or 25), 100)
            url = f"{GRAPH_ENDPOINT}/groups?$top={limit}&$select=id,displayName,groupTypes,mailEnabled,securityEnabled,description"
            if query:
                url += f"&$filter=startswith(displayName,'{query}')"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing groups ({resp.status_code}): {resp.text}"
            groups = resp.json().get("value", [])
            if not groups:
                return "No groups found."
            lines = [f"Found {len(groups)} group(s):"]
            for g in groups:
                g_type = "M365" if "Unified" in g.get("groupTypes", []) else ("Security" if g.get("securityEnabled") else "Distribution")
                lines.append(f"- {g.get('displayName')} [{g_type}] (ID: {g.get('id')})")
            return "\n".join(lines)

        elif action_clean in ("get_sign_ins", "sign_ins", "audit_logs"):
            user_id = p.get("user_id") or p.get("upn")
            limit = min(int(p.get("limit") or 10), 50)
            url = f"{GRAPH_ENDPOINT}/auditLogs/signIns?$top={limit}"
            if user_id:
                url += f"&$filter=userPrincipalName eq '{user_id}'"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error fetching sign-in logs ({resp.status_code}): {resp.text}"
            logs = resp.json().get("value", [])
            if not logs:
                return f"No recent sign-in events found{' for ' + user_id if user_id else ''}."
            lines = [f"Recent Sign-in Activity ({len(logs)} events):"]
            for log in logs:
                created = log.get("createdDateTime", "")[:19].replace("T", " ")
                user_p = log.get("userPrincipalName", "Unknown")
                app_name = log.get("appDisplayName", "App")
                ip = log.get("ipAddress", "")
                status_obj = log.get("status", {})
                success = status_obj.get("errorCode", 0) == 0
                status_str = "SUCCESS" if success else f"FAILED ({status_obj.get('failureReason', 'Error')})"
                lines.append(f"- [{created} UTC] {user_p} via {app_name} from {ip} -> {status_str}")
            return "\n".join(lines)

        else:
            return (
                f"Unknown M365 action: '{action}'. Available actions:\n"
                "- list_users, get_user, reset_password\n"
                "- list_licenses, assign_license, revoke_license\n"
                "- list_groups, get_sign_ins"
            )

    except requests.RequestException as exc:
        return f"Network/API Error communicating with Microsoft Graph: {exc}"


# --- Azure Resource Manager Operations ---

def execute_azure_admin(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    subscription_alias: Optional[str] = None,
) -> str:
    """Execute a governed Azure Resource Manager operation."""
    p = params or {}
    sub_cfg = get_subscription_config(subscription_alias)
    if not sub_cfg:
        return (
            "Error: No Azure subscription configured.\n"
            "Run '/setup-cloud' or 'safi setup-cloud' in the terminal to configure Azure credentials."
        )

    sub_id = sub_cfg.get("subscription_id")
    if not sub_id:
        return "Error: Configured Azure target is missing 'subscription_id'."

    try:
        token = acquire_oauth_token(
            tenant_id=sub_cfg["tenant_id"],
            client_id=sub_cfg["client_id"],
            client_secret=sub_cfg["client_secret"],
            scope="https://management.azure.com/.default",
        )
    except Exception as exc:
        return f"Authentication Error: Could not connect to Azure: {exc}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    action_clean = action.strip().lower()

    try:
        if action_clean in ("list_resource_groups", "resource_groups"):
            url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resourcegroups?api-version=2021-04-01"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing resource groups ({resp.status_code}): {resp.text}"
            rgs = resp.json().get("value", [])
            if not rgs:
                return "No resource groups found in subscription."
            lines = [f"Resource Groups ({len(rgs)}):"]
            for rg in rgs:
                lines.append(f"- {rg.get('name')} (Location: {rg.get('location')})")
            return "\n".join(lines)

        elif action_clean in ("list_vms", "vms"):
            rg = p.get("resource_group")
            if rg:
                url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01"
            else:
                url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing VMs ({resp.status_code}): {resp.text}"
            vms = resp.json().get("value", [])
            if not vms:
                return f"No virtual machines found{' in ' + rg if rg else ''}."
            lines = [f"Virtual Machines ({len(vms)}):"]
            for vm in vms:
                vm_name = vm.get("name")
                loc = vm.get("location")
                vm_size = vm.get("properties", {}).get("hardwareProfile", {}).get("vmSize", "N/A")
                vm_rg = vm.get("id", "").split("/resourceGroups/")[1].split("/")[0] if "/resourceGroups/" in vm.get("id", "") else ""
                lines.append(f"- {vm_name} ({vm_size}) in RG '{vm_rg}' [{loc}]")
            return "\n".join(lines)

        elif action_clean in ("get_vm", "vm_status"):
            rg = p.get("resource_group")
            vm_name = p.get("vm_name") or p.get("name")
            if not rg or not vm_name:
                return "Error: Both 'resource_group' and 'vm_name' are required."
            url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm_name}/instanceView?api-version=2023-09-01"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 404:
                return f"VM '{vm_name}' not found in resource group '{rg}'."
            if resp.status_code != 200:
                return f"Error fetching VM details ({resp.status_code}): {resp.text}"
            view = resp.json()
            statuses = [s.get("displayStatus", "") for s in view.get("statuses", [])]
            return f"VM '{vm_name}' Status:\n  " + "\n  ".join(statuses)

        elif action_clean in ("vm_action", "restart_vm", "start_vm", "stop_vm"):
            rg = p.get("resource_group")
            vm_name = p.get("vm_name") or p.get("name")
            sub_action = (p.get("action") or action_clean.replace("_vm", "")).lower()
            if not rg or not vm_name:
                return "Error: Both 'resource_group' and 'vm_name' are required."

            valid_actions = {
                "start": "start",
                "stop": "powerOff",
                "poweroff": "powerOff",
                "restart": "restart",
                "deallocate": "deallocate",
            }
            arm_action = valid_actions.get(sub_action)
            if not arm_action:
                return f"Error: Unknown VM action '{sub_action}'. Valid: start, stop, restart, deallocate."

            url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm_name}/{arm_action}?api-version=2023-09-01"
            resp = requests.post(url, headers=headers, timeout=30)
            if resp.status_code not in (200, 202, 204):
                return f"Error executing '{sub_action}' on VM ({resp.status_code}): {resp.text}"
            return f"✓ Dispatched action '{sub_action}' on VM '{vm_name}' in resource group '{rg}'."

        elif action_clean in ("list_resources", "resources"):
            rg = p.get("resource_group")
            if rg:
                url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resourceGroups/{rg}/resources?api-version=2021-04-01"
            else:
                url = f"{ARM_ENDPOINT}/subscriptions/{sub_id}/resources?api-version=2021-04-01"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return f"Error listing resources ({resp.status_code}): {resp.text}"
            res_list = resp.json().get("value", [])
            if not res_list:
                return "No resources found."
            lines = [f"Azure Resources ({len(res_list)}):"]
            for r in res_list[:50]:
                r_type = r.get("type", "").split("/")[-1]
                lines.append(f"- {r.get('name')} [{r_type}] (Location: {r.get('location')})")
            if len(res_list) > 50:
                lines.append(f"... [{len(res_list) - 50} more resources truncated]")
            return "\n".join(lines)

        else:
            return (
                f"Unknown Azure action: '{action}'. Available actions:\n"
                "- list_resource_groups\n"
                "- list_vms, get_vm, vm_action (start/stop/restart/deallocate)\n"
                "- list_resources"
            )

    except requests.RequestException as exc:
        return f"Network/API Error communicating with Azure ARM: {exc}"


# --- Unified Status & Interactive Setup ---

def execute_cloud_status() -> str:
    """Return status summary of configured Microsoft 365 and Azure environments."""
    cfg = load_cloud_config()
    tenants = cfg.get("tenants", {})
    subs = cfg.get("subscriptions", {})

    lines = ["☁️ SAFi Cloud Environment Status:"]

    # M365 section
    if tenants:
        lines.append(f"\nMicrosoft 365 Tenants ({len(tenants)} configured):")
        for alias, t in tenants.items():
            t_id = t.get("tenant_id", "")
            masked_id = t_id[:8] + "..." if len(t_id) > 8 else t_id
            lines.append(f"  - [{alias}] {t.get('name', alias)} (Tenant: {masked_id}) — {t.get('description', '')}")
    else:
        lines.append("\nMicrosoft 365: No tenant configured. (Run '/setup-cloud')")

    # Azure section
    if subs:
        lines.append(f"\nAzure Subscriptions ({len(subs)} configured):")
        for alias, s in subs.items():
            s_id = s.get("subscription_id", "")
            masked_sub = s_id[:8] + "..." if len(s_id) > 8 else s_id
            lines.append(f"  - [{alias}] {s.get('name', alias)} (Subscription: {masked_sub}) — {s.get('description', '')}")
    else:
        lines.append("\nAzure: No subscription configured. (Run '/setup-cloud')")

    return "\n".join(lines)


def interactive_setup_cloud() -> None:
    """Interactive CLI setup for Microsoft 365 and Azure credentials (matching /setup-key)."""
    ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]☁️ Configure Cloud Environments (M365 & Azure)[/]")
    ui.console.print("[dim]Configure Service Principal credentials for Microsoft 365 and Azure administration.[/dim]\n")

    cfg = load_cloud_config()
    if "tenants" not in cfg:
        cfg["tenants"] = {}
    if "subscriptions" not in cfg:
        cfg["subscriptions"] = {}

    ui.console.print("Select an option:")
    ui.console.print("  1) Configure Microsoft 365 / Entra ID Tenant")
    ui.console.print("  2) Configure Azure Subscription")
    ui.console.print("  3) View Configured Cloud Targets")
    ui.console.print("  4) Test Connectivity")
    ui.console.print("  5) Exit\n")

    try:
        choice = input("Choice (1-5): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.console.print()
        return

    if choice == "1":
        _setup_m365_interactive(cfg)
    elif choice == "2":
        _setup_azure_interactive(cfg)
    elif choice == "3":
        ui.console.print(execute_cloud_status())
    elif choice == "4":
        _test_connectivity_interactive()
    else:
        ui.console.print("Setup cancelled.")


def _setup_m365_interactive(cfg: Dict[str, Any]) -> None:
    ui.console.print(f"\n[bold {ui.COLOR_BRAND_500}]Configure Microsoft 365 Tenant[/]")
    try:
        alias = input("Target Alias [default: primary]: ").strip() or "primary"
        name = input("Display Name [e.g. Corporate M365]: ").strip() or alias
        tenant_id = input("Tenant ID (GUID): ").strip()
        client_id = input("Client / Application ID (GUID): ").strip()
        import getpass
        client_secret = getpass.getpass("Client Secret: ").strip()
        desc = input("Description: ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.console.print()
        return

    if not tenant_id or not client_id or not client_secret:
        ui.print_error("Tenant ID, Client ID, and Client Secret are required.")
        return

    # Test token acquisition
    ui.console.print("Verifying credentials with Microsoft Entra ID...")
    try:
        acquire_oauth_token(tenant_id, client_id, client_secret, "https://graph.microsoft.com/.default")
        ui.console.print(f"[{ui.COLOR_SUCCESS}]✓ Credentials verified successfully![/]")
    except Exception as exc:
        ui.print_error(f"Credential test failed: {exc}")
        save_anyway = input("Save configuration anyway? [y/N]: ").strip().lower()
        if save_anyway != "y":
            return

    cfg["tenants"][alias] = {
        "name": name,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "description": desc or "Microsoft 365 Tenant",
    }
    if not cfg.get("default_tenant"):
        cfg["default_tenant"] = alias

    save_cloud_config(cfg)
    ui.console.print(f"[{ui.COLOR_SUCCESS}]✓ Saved Microsoft 365 configuration to {CLOUD_CONFIG_FILE}[/]")


def _setup_azure_interactive(cfg: Dict[str, Any]) -> None:
    ui.console.print(f"\n[bold {ui.COLOR_BRAND_500}]Configure Azure Subscription[/]")
    try:
        alias = input("Target Alias [default: primary]: ").strip() or "primary"
        name = input("Display Name [e.g. Production Azure]: ").strip() or alias
        tenant_id = input("Tenant ID (GUID): ").strip()
        client_id = input("Client / Application ID (GUID): ").strip()
        import getpass
        client_secret = getpass.getpass("Client Secret: ").strip()
        sub_id = input("Subscription ID (GUID): ").strip()
        desc = input("Description: ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.console.print()
        return

    if not tenant_id or not client_id or not client_secret or not sub_id:
        ui.print_error("Tenant ID, Client ID, Client Secret, and Subscription ID are required.")
        return

    # Test token acquisition
    ui.console.print("Verifying credentials with Azure ARM...")
    try:
        acquire_oauth_token(tenant_id, client_id, client_secret, "https://management.azure.com/.default")
        ui.console.print(f"[{ui.COLOR_SUCCESS}]✓ Credentials verified successfully![/]")
    except Exception as exc:
        ui.print_error(f"Credential test failed: {exc}")
        save_anyway = input("Save configuration anyway? [y/N]: ").strip().lower()
        if save_anyway != "y":
            return

    cfg["subscriptions"][alias] = {
        "name": name,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "subscription_id": sub_id,
        "description": desc or "Azure Subscription",
    }
    if not cfg.get("default_subscription"):
        cfg["default_subscription"] = alias

    save_cloud_config(cfg)
    ui.console.print(f"[{ui.COLOR_SUCCESS}]✓ Saved Azure configuration to {CLOUD_CONFIG_FILE}[/]")


def _test_connectivity_interactive() -> None:
    ui.console.print("\n[bold]Testing Cloud Connectivity...[/]")
    cfg = load_cloud_config()
    tenants = cfg.get("tenants", {})
    subs = cfg.get("subscriptions", {})

    if not tenants and not subs:
        ui.console.print(f"[{ui.COLOR_WARN}]No cloud targets configured in {CLOUD_CONFIG_FILE}.[/]")
        return

    for alias, t in tenants.items():
        ui.console.print(f"Testing M365 tenant '{alias}'...")
        try:
            acquire_oauth_token(t["tenant_id"], t["client_id"], t["client_secret"], "https://graph.microsoft.com/.default")
            ui.console.print(f"  [{ui.COLOR_SUCCESS}]✓ M365 Connected[/]")
        except Exception as exc:
            ui.console.print(f"  [{ui.COLOR_ERROR}]✗ M365 Failed: {exc}[/]")

    for alias, s in subs.items():
        ui.console.print(f"Testing Azure subscription '{alias}'...")
        try:
            acquire_oauth_token(s["tenant_id"], s["client_id"], s["client_secret"], "https://management.azure.com/.default")
            ui.console.print(f"  [{ui.COLOR_SUCCESS}]✓ Azure Connected[/]")
        except Exception as exc:
            ui.console.print(f"  [{ui.COLOR_ERROR}]✗ Azure Failed: {exc}[/]")
