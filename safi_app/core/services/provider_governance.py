from __future__ import annotations
import json
import time
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import FrozenSet, List, Optional

from .model_routing import (PROVIDER_METADATA, configured_providers, detect_provider,
                            effective_configured_providers)

LOCAL_CATALOGUE_PATH = "/etc/safi/local-models.json"

_ACTIVE_ALLOWLIST: ContextVar[Optional[FrozenSet[str]]] = ContextVar(
    "safi_provider_allowlist", default=None
)
_ACTIVE_ORG: ContextVar[Optional[str]] = ContextVar("safi_active_org", default=None)

_CACHE_TTL_SECONDS = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ProviderNotAllowedError(RuntimeError):

    def __init__(self, provider: str, context: str = ""):
        self.provider = provider
        super().__init__(
            f"LLM provider '{provider}' is blocked by this organization's provider policy"
            + (f" ({context})" if context else "")
        )


def get_org_allowlist(org_id) -> Optional[FrozenSet[str]]:
    if not org_id:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(org_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]
    try:
        from ...persistence import database as db
        raw = db.get_org_provider_config(org_id).get("allowlist")
    except Exception:
        raw = None
    allow = None if raw is None else frozenset(p for p in raw if p in PROVIDER_METADATA)
    with _cache_lock:
        _cache[org_id] = (allow, now)
    return allow


def invalidate_org(org_id) -> None:
    with _cache_lock:
        _cache.pop(org_id, None)


def activate_org(org_id, allowlist: Optional[FrozenSet[str]] = None) -> None:
    _ACTIVE_ORG.set(str(org_id) if org_id else None)
    if allowlist is not None:
        _ACTIVE_ALLOWLIST.set(allowlist)
    else:
        _ACTIVE_ALLOWLIST.set(get_org_allowlist(org_id))


def active_allowlist() -> Optional[FrozenSet[str]]:
    return _ACTIVE_ALLOWLIST.get()


def active_org() -> Optional[str]:
    return _ACTIVE_ORG.get()


def assert_provider_allowed(provider_name: str, context: str = "") -> None:
    allow = _ACTIVE_ALLOWLIST.get()
    if allow is not None and provider_name not in allow:
        raise ProviderNotAllowedError(provider_name, context)


def model_allowed(model_id: str, allowlist: Optional[FrozenSet[str]]) -> bool:
    if not model_id:
        return False
    try:
        return allowlist is None or detect_provider(model_id) in allowlist
    except Exception:
        return False


def local_model_inventory(catalogue_path: str | None = None) -> List[dict]:
    from ...config import active_local_model

    if catalogue_path is None:
        catalogue_path = LOCAL_CATALOGUE_PATH
    try:
        with open(catalogue_path, encoding="utf-8") as handle:
            catalogue = json.load(handle)
        if catalogue.get("schema") != 1:
            return []
        root = Path(catalogue["model_root"])
        live = active_local_model()
        context = int(catalogue.get("context_size", 0) or 0)
    except (OSError, ValueError, KeyError, TypeError):
        return []

    out = []
    for model in catalogue.get("models", []) or []:
        if model.get("conscience_only"):
            continue
        try:
            size = int(model["size"])
            path = root / model["id"] / model["file"]
            try:
                installed = path.stat().st_size == size
            except OSError:
                installed = False
            out.append({
                "id": model["id"],
                "alias": model["alias"],
                "label": model.get("label") or model["alias"],
                "summary": model.get("summary", ""),
                "size": size,
                "size_human": f"{size / 1e9:.1f} GB",
                "context_window": context,
                "min_ram": int(model.get("min_ram", 0) or 0),
                "installed": installed,
                "active": installed and model["alias"] == live,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def local_catalog_payload(catalogue_path: str | None = None) -> dict:
    inventory = local_model_inventory(catalogue_path)
    try:
        from ...config import LOCAL_MODEL_STATUS_PATH
        with open(LOCAL_MODEL_STATUS_PATH, encoding="utf-8") as handle:
            status = json.load(handle)
    except (OSError, ValueError):
        status = {}
    downloading = status.get("model") if status.get("state") in (
        "running", "downloading", "verifying", "installing", "configuring", "starting"
    ) else None
    is_activating = bool(status.get("activated", False))
    for model in inventory:
        is_this_model = (model["id"] == downloading)
        model["downloading"] = is_this_model
        model["loading"] = is_this_model and (model.get("installed") or is_activating)
    if not inventory:
        return {
            "ok": True, "available": False, "models": [], "active": None,
            "reason": "This deployment has no on-appliance model catalogue.",
        }
    return {
        "ok": True,
        "available": True,
        "models": inventory,
        "active": next((m["alias"] for m in inventory if m["active"]), None),
    }


def installed_local_models(catalogue_path: str | None = None) -> List[dict]:
    return [{"id": m["alias"], "label": m["label"], "provider": "local",
             "local": True, "size_bytes": m["size"],
             "size_human": m["size_human"],
             "context_window": m["context_window"],
             "active": bool(m.get("active"))}
            for m in local_model_inventory(catalogue_path) if m.get("installed") or m.get("active")]


def get_user_model_allowlist(user_id: Optional[str], org_id: Optional[str], user_role: Optional[str] = None) -> Optional[FrozenSet[str]]:
    if not user_id:
        return get_org_allowlist(org_id)

    from ...role_config import ROLE_CONFIG
    admin_roles = set(ROLE_CONFIG.get("organization_admin_roles") or ["admin"])
    if user_role and user_role in admin_roles:
        return None

    u_det = None
    if not user_role:
        try:
            from ...persistence import database as db
            u_det = db.get_user_details(user_id)
        except Exception:
            u_det = None
    if u_det and (u_det.get("role") in admin_roles):
        return None

    effective_org = org_id or (u_det.get("org_id") if u_det else None)
    from ...persistence import sharing_store
    user_groups = sharing_store.get_user_group_details(user_id, effective_org)

    can_use_cloud = False
    cloud_entitlement_names = {
        "cloud ai access", "cloud ai", "cloud models", "cloud-ai-access",
        "cloud_ai_access", "cloud-models"
    }

    for g in user_groups:
        gname = str(g.get("name") or "").lower().strip()
        gpol = str(g.get("model_policy") or "default").lower().strip()
        if gpol == "cloud" or gname in cloud_entitlement_names:
            can_use_cloud = True
            break

    org_allow = get_org_allowlist(effective_org)
    if can_use_cloud:
        all_providers = frozenset(PROVIDER_METADATA.keys())
        if org_allow is not None:
            return all_providers & org_allow
        return None

    return frozenset(["local"])


def list_models_for_org(org_id, allow=None) -> List[dict]:
    from ...config import Config
    from .model_routing import custom_models
    if allow is None:
        allow = get_org_allowlist(org_id)
    configured = effective_configured_providers(Config, org_id)
    merged = [dict(m) for m in Config.AVAILABLE_MODELS]
    merged += installed_local_models()
    merged += [{"id": r["model_id"], "label": r["label"], "custom": True}
               for r in custom_models()
               if str(r.get("org_id") or "") in ("", str(org_id or ""))]
    out = []
    seen_ids = set()
    for m in merged:
        if m["id"] in seen_ids:
            continue
        prov = detect_provider(m["id"])
        if prov not in configured:
            continue
        if allow is not None and prov not in allow:
            continue
        seen_ids.add(m["id"])
        meta = PROVIDER_METADATA.get(prov, {})
        out.append({
            **m,
            "provider": prov,
            "provider_label": meta.get("label", prov),
            "baa_capable": bool(meta.get("baa_capable")),
            "eu_hostable": bool(meta.get("eu_hostable")),
        })
    return out


def list_models_for_user(user_id: Optional[str], org_id: Optional[str], user_role: Optional[str] = None) -> List[dict]:
    allow = get_user_model_allowlist(user_id, org_id, user_role)
    return list_models_for_org(org_id, allow=allow)


def get_model_id_for_alias(alias: str, catalogue_path: str | None = None) -> Optional[str]:
    for m in local_model_inventory(catalogue_path):
        if m.get("alias") == alias or m.get("id") == alias:
            return m.get("id")
    return None


async def ensure_local_model(target_alias: str, catalogue_path: str | None = None, timeout: float = 60.0) -> bool:
    import asyncio
    import subprocess
    import urllib.request
    from ...config import active_local_model

    current_live = active_local_model()
    if current_live == target_alias:
        return True

    model_id = get_model_id_for_alias(target_alias, catalogue_path)
    if not model_id:
        return False

    def _activate():
        try:
            res = subprocess.run(
                ["sudo", "/usr/local/sbin/safi-model-manage", model_id, "--activate"],
                capture_output=True, text=True, timeout=15, check=False
            )
            return res.returncode == 0
        except Exception:
            return False

    success = await asyncio.to_thread(_activate)
    if not success:
        return False

    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        await asyncio.sleep(1.0)
        try:
            def _check_models():
                req = urllib.request.Request("http://127.0.0.1:8081/v1/models", headers={"User-Agent": "SAFi-Local-Check"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        for item in data.get("data", []):
                            if item.get("id") == target_alias or target_alias in item.get("aliases", []):
                                return True
                        for m in data.get("models", []):
                            if m.get("name") == target_alias or m.get("model") == target_alias:
                                return True
                return False
            is_ready = await asyncio.to_thread(_check_models)
            if is_ready:
                return True
        except Exception:
            pass

    return False
