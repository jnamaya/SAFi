"""
Per-organization LLM provider allow-list — the shared keystone control for
HIPAA (BAA-covered provider chains) and EU data residency.

Contract:
- The allow-list lives in organizations.settings.provider_allowlist as a list
  of provider keys from model_routing.PROVIDER_METADATA. Absent/None means
  unrestricted. Writes go through db.set_org_provider_allowlist, which
  evidence-logs the change to org_compliance_log in the same transaction.
- Org context is established once per request/turn with activate_org(org_id); a
  ContextVar carries it so it survives awaits, and SAFi._submit_bg copies the
  context into background executor threads.
- Every LLM dispatch point calls assert_provider_allowed(provider). FAIL
  CLOSED: a disallowed provider raises ProviderNotAllowedError — there is
  never a silent fallback to another provider, because silent fallback to the
  default (Groq) is exactly the breach scenario this control exists to prevent.
- No active org context (unset/None) = unrestricted; the request-time model
  validation in the chat endpoints is the second net for that case.
"""
from __future__ import annotations
import json
import time
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import FrozenSet, List, Optional

from .model_routing import (PROVIDER_METADATA, configured_providers, detect_provider,
                            effective_configured_providers)

# The appliance catalogue, installed by the ISO's 070 hook. It alone knows which
# local models this build can offer, so the list is read from it, not hardcoded.
LOCAL_CATALOGUE_PATH = "/etc/safi/local-models.json"

_ACTIVE_ALLOWLIST: ContextVar[Optional[FrozenSet[str]]] = ContextVar(
    "safi_provider_allowlist", default=None
)
# The governing org itself, carried alongside the allow-list so downstream
# persistence (trail org attribution, review-queue sampling) can resolve the
# turn's org without threading it through every call signature.
_ACTIVE_ORG: ContextVar[Optional[str]] = ContextVar("safi_active_org", default=None)

_CACHE_TTL_SECONDS = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


class ProviderNotAllowedError(RuntimeError):
    """Raised when a dispatch would send content to a provider the governing
    organization has not allowed. Deliberately terminal — never caught to
    reroute."""

    def __init__(self, provider: str, context: str = ""):
        self.provider = provider
        super().__init__(
            f"LLM provider '{provider}' is blocked by this organization's provider policy"
            + (f" ({context})" if context else "")
        )


def get_org_allowlist(org_id) -> Optional[FrozenSet[str]]:
    """Resolve an org's provider allow-list (60s cache). None = unrestricted.
    Unknown provider keys are dropped on read; a stored-but-empty list blocks
    every provider (fail closed) — the write path refuses to store one."""
    if not org_id:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(org_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]
    from ...persistence import database as db  # lazy: avoids import cycle at module load
    raw = db.get_org_provider_config(org_id).get("allowlist")
    allow = None if raw is None else frozenset(p for p in raw if p in PROVIDER_METADATA)
    with _cache_lock:
        _cache[org_id] = (allow, now)
    return allow


def invalidate_org(org_id) -> None:
    with _cache_lock:
        _cache.pop(org_id, None)


def activate_org(org_id) -> None:
    _ACTIVE_ORG.set(str(org_id) if org_id else None)
    _ACTIVE_ALLOWLIST.set(get_org_allowlist(org_id))


def active_allowlist() -> Optional[FrozenSet[str]]:
    return _ACTIVE_ALLOWLIST.get()


def active_org() -> Optional[str]:
    """The org governing this execution context. None = ungoverned."""
    return _ACTIVE_ORG.get()


def assert_provider_allowed(provider_name: str, context: str = "") -> None:
    allow = _ACTIVE_ALLOWLIST.get()
    if allow is not None and provider_name not in allow:
        raise ProviderNotAllowedError(provider_name, context)


def model_allowed(model_id: str, allowlist: Optional[FrozenSet[str]]) -> bool:
    return allowlist is None or detect_provider(model_id) in allowlist


def local_model_inventory(catalogue_path: str | None = None) -> List[dict]:
    """Every local model in the appliance catalogue, with what is on disk.

    Shapes each entry with installed/active so a catalog UI can show the whole
    choice without pretending an absent model can be dispatched. Returns [] on any
    problem: this is an appliance-only file, absent on a normal deployment, and
    must never be able to fail a request.
    """
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
        # Per-model, not per-catalogue. A single malformed entry must cost only
        # that entry: an outer try around the whole loop turns one bad key into
        # an empty catalog, which reads as "this box has no models" and hides
        # the very model the operator is looking at.
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
                # Only the model the server was started with is dispatchable.
                # llama-server takes a single --alias, so a second downloaded
                # model is installed but not being served.
                "active": installed and model["alias"] == live,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def local_catalog_payload(catalogue_path: str | None = None) -> dict:
    """Response body for GET /api/models/local.

    Answers a different question from /models: not "what may be dispatched" but
    "what could be downloaded, what is on disk, and what is being served". The
    Model Catalog needs the middle and last of those, which a dispatch-only
    endpoint cannot express.

    An off-appliance install has no catalogue and reports available=False — an
    ordinary state, not an error, because most SAFi deployments are not
    appliances.
    """
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
    for model in inventory:
        model["downloading"] = model["id"] == downloading
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
    """Local (safi-*) models that can actually be dispatched right now.

    Synthesized rather than stored: the operator picks a model in the setup
    wizard, and a DB row would have to be written and rewritten on every change.
    Reading the catalogue means a model swap shows up on the next request with no
    write path at all, and there is no second source of truth to fall out of step
    with the file the downloader used.

    Only the model the server is actually serving is returned. The rest of this
    module's contract is that a model which cannot be dispatched is never
    offered, and llama-server answers to exactly one --alias: offering a second
    downloaded model would store a selection that 404s on first use. The catalog
    UI shows the rest via local_model_inventory().

    Returns [] on any problem, or when no model is live.
    """
    return [{"id": m["alias"], "label": m["label"], "provider": "local",
             "local": True, "size_bytes": m["size"],
             "size_human": m["size_human"],
             "context_window": m["context_window"]}
            for m in local_model_inventory(catalogue_path) if m["active"]]


def list_models_for_org(org_id) -> List[dict]:
    """Config.AVAILABLE_MODELS plus local and operator-added rows, enriched with
    provider metadata, filtered to configured providers and then by the org's
    allow-list. Single source of truth for every model picker — a model that
    can't actually be dispatched is never offered."""
    from ...config import Config
    from .model_routing import custom_models
    allow = get_org_allowlist(org_id)
    # A provider is usable with a deployment .env key, a deployment key stored
    # from the UI, OR the org's own key (backlog 64) — any of them dispatches for
    # this org, so the catalog must offer its models. Reading this from the
    # .env-only set made a deployment-key-only provider show up in the add-model
    # form while its models were missing from the list that form writes into.
    configured = effective_configured_providers(Config, org_id)
    # Built-ins first, then the appliance's installed local models, then
    # operator-added rows (backlog 63) marked custom so the catalog UI knows
    # which entries are deletable. All pass the same configured-provider and
    # allow-list filters.
    merged = [dict(m) for m in Config.AVAILABLE_MODELS]
    merged += installed_local_models()
    # Custom rows are scoped: this org's own entries plus the deployment-wide
    # ones (org_id ''). Unscoped, every org's picker listed every other org's
    # models, disclosing ids and labels across tenants (backlog 77).
    merged += [{"id": r["model_id"], "label": r["label"], "custom": True}
               for r in custom_models()
               if str(r.get("org_id") or "") in ("", str(org_id or ""))]
    out = []
    for m in merged:
        prov = detect_provider(m["id"])
        if prov not in configured:
            continue
        if allow is not None and prov not in allow:
            continue
        meta = PROVIDER_METADATA.get(prov, {})
        out.append({
            **m,
            "provider": prov,
            "provider_label": meta.get("label", prov),
            "baa_capable": bool(meta.get("baa_capable")),
            "eu_hostable": bool(meta.get("eu_hostable")),
        })
    return out
