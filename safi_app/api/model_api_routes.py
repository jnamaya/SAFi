import re
import subprocess

from flask import Blueprint, jsonify, request, session, current_app

from ..config import Config
from ..persistence import database as db
from ..core.rbac import require_role, get_current_org_id
from ..core.services.provider_governance import list_models_for_org
from ..core.services.model_routing import (
    PROVIDER_METADATA, invalidate_custom_models_cache)

model_api_bp = Blueprint('model_api', __name__)

# Provider ids are ours; model ids are the provider's spelling — letters,
# digits, and the separators seen in the wild (openai/gpt-oss-120b, gpt-5.6).
_MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$')


def _is_deployment_operator():
    """A named deployment operator (SAFI_SUPER_ADMINS), or the box's own local
    admin. Never an org role.

    Deployment-wide catalog rows (org_id '') belong to the deployment, not to a
    tenant, so scoping deletes to the caller's org left them unmanageable by
    ANYONE holding an org: every org-scoped delete misses them. Operators are who
    the deployment-wide catalog was always for, so they are who can remove from
    it. Blank SAFI_SUPER_ADMINS = nobody, the same safe default the usage
    rollup uses.

    The local admin is admitted by ID and not by email, because it is created
    without one (see database.ensure_local_admin) and so could never match an
    email list. Matching on "has no email" instead would be far broader than
    intended — any half-registered account would qualify. It is the box owner,
    which is exactly the role the appliance path already trusts when it has no
    organizations, and it already holds full org/policy authority, so this
    widens nothing an operator could not already do.
    """
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    if user_id == 'local_admin':
        return True
    details = db.get_user_details(user_id) or {}
    email = (details.get('email') or user.get('email') or '').lower()
    supers = {e.lower() for e in Config.SUPER_ADMIN_EMAILS}
    return bool(email) and email in supers


def _deployment_keys_forbidden():
    """Shared guard for the deployment-wide provider-key endpoints.

    A deployment key changes what every org on this install dispatches against,
    so on a multi-tenant install only a named operator may set one. Gating on
    the operator alone, though, would lock the appliance out entirely:
    SAFI_SUPER_ADMINS defaults to blank (nobody), and an appliance with no
    organizations has no other tenant to protect — the admin there IS the
    deployment. So the operator always qualifies, and a plain admin qualifies
    only on a genuinely single-tenant deployment.

    "Genuinely single-tenant" is BOTH signals agreeing, not either one:

      SAFI_TENANCY_MODE == 'single'   the deployment's declared shape
      at most one organization          the shape it actually has

    Reading only the org count is what made this wrong for the commonest
    install there is. Single-tenant mode still CREATES one org on first login —
    that org is the whole deployment — so a default install has exactly one
    row, not zero, and a count-only test called it multi-tenant and locked the
    ordinary admin out of the very pane built for them. Reading only the
    declared mode is the mirror-image bug: an install left on 'single' after
    several orgs were created would let any one of those orgs retarget
    everyone else's dispatch.

    Deliberately fails closed: if the org count cannot be read, this returns
    403 rather than assuming single-tenant.
    """
    if _is_deployment_operator():
        return None
    try:
        if Config.TENANCY_MODE == 'single' and db.count_organizations() <= 1:
            return None
    except Exception as e:
        current_app.logger.error(f"deployment key guard failed closed: {type(e).__name__}")
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({"error": "Forbidden"}), 403


@model_api_bp.route('/models', methods=['GET'], strict_slashes=False)
def list_models():
    """Canonical model list: Config.AVAILABLE_MODELS enriched with provider
    metadata (provider, baa_capable, eu_hostable) and filtered by the caller
    org's provider allow-list — so a model on a blocked provider is never
    even offered in a picker.

    Also carries public_demo_ui, which tells the front end whether to show the
    showcase framing around model choice. It rides along here because the model
    picker is the surface that framing is about."""
    user = session.get('user')
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = user.get('sub') or user.get('id')
    details = db.get_user_details(user_id) or {}
    return jsonify({
        "ok": True,
        "models": list_models_for_org(details.get('org_id')),
        "public_demo_ui": Config.PUBLIC_DEMO_UI,
    })


@model_api_bp.route('/models/local', methods=['GET'])
@require_role('admin')
def list_local_models():
    """The appliance catalogue: available, installed, and what is being served.

    Backs the Local side of the Model Catalog. Distinct from /models, which
    answers "what may this org dispatch right now" and so returns only the live
    model -- here an admin needs to see the whole choice, including models that
    are absent (to download) or present but not currently served.
    """
    from ..core.services.provider_governance import local_catalog_payload
    return jsonify(local_catalog_payload())


@model_api_bp.route('/models/local/status', methods=['GET'])
@require_role('admin')
def local_model_status():
    from pathlib import Path
    import json
    path = Path('/var/lib/safi/model-fetch.json')
    try:
        status = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        status = {}
    return jsonify({'ok': True, 'available': path.exists(), 'status': status})


@model_api_bp.route('/models/local/download', methods=['POST'])
@require_role('admin')
def download_local_model():
    model_id = (request.json or {}).get('model_id', '').strip()
    activate = bool((request.json or {}).get('activate', False))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}', model_id):
        return jsonify({'error': 'Invalid local model id.'}), 400
    try:
        result = subprocess.run(
            ['sudo', '/usr/local/sbin/safi-model-manage', model_id]
            + (['--activate'] if activate else []),
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return jsonify({'error': f'Local model management is unavailable: {exc}'}), 503
    if result.returncode:
        return jsonify({'error': result.stderr.strip() or result.stdout.strip() or 'Unable to start local model download.'}), 409
    return jsonify({'ok': True})


@model_api_bp.route('/models/custom', methods=['GET'])
@require_role('admin')
def list_custom():
    """The operator-added rows plus the provider options for the add form
    (backlog 63). Reads the DB directly, NOT the 60s custom_models() cache:
    that cache is per gunicorn worker, so right after an add the worker
    serving this list may still hold the pre-add copy — the management view
    must always show what is actually stored. Only providers that can actually
    dispatch are offered (.env key, a deployment key, or the caller's own org
    key): a model that cannot dispatch must not be addable."""
    from ..core.services.model_routing import effective_configured_providers
    configured = effective_configured_providers(Config, get_current_org_id())

    # Scoped to the caller's org plus the deployment-wide rows (backlog 77).
    # This used to list every org's entries to every admin. A deployment
    # operator sees everything, because they are the only one who can manage
    # the deployment-wide rows and cannot curate what they cannot see.
    is_operator = _is_deployment_operator()
    rows = (db.list_custom_models() if is_operator
            else db.list_custom_models(visible_to_org=get_current_org_id() or ''))
    return jsonify({
        "ok": True,
        "models": [
            {"id": r["model_id"], "label": r["label"], "provider": r["provider"],
             # Deployment-wide rows are not a tenant's to remove, so the UI can
             # render them read-only instead of offering a Remove that 404s.
             # An operator can remove them, so for them nothing is read-only.
             "deployment_wide": bool(not (r.get("org_id") or "") and not is_operator)}
            for r in rows
        ],
        "providers": [
            {"id": p, "label": PROVIDER_METADATA[p]["label"]}
            for p in sorted(PROVIDER_METADATA) if p in configured
        ],
    })


@model_api_bp.route('/models/custom', methods=['POST'])
@require_role('admin')
def add_custom():
    data = request.json or {}
    model_id = (data.get('id') or '').strip()
    label = (data.get('label') or '').strip() or model_id
    provider = (data.get('provider') or '').strip().lower()

    if not _MODEL_ID_RE.match(model_id):
        return jsonify({"error": "Model id must be the provider's exact spelling (letters, digits, . _ / : -)."}), 400
    if provider not in PROVIDER_METADATA:
        return jsonify({"error": f"Unknown provider '{provider}'."}), 400
    from ..core.services.model_routing import effective_configured_providers
    if provider not in effective_configured_providers(Config, get_current_org_id()):
        return jsonify({"error": f"No API key is configured for '{provider}', so this model could never dispatch."}), 400

    if any(m["id"].lower() == model_id.lower() for m in Config.AVAILABLE_MODELS):
        return jsonify({"error": "That model is already in the built-in catalog."}), 409
    # Same check against the appliance's installed local models. Without this an
    # operator could add a shadow row for an id the catalogue already supplies,
    # and the picker would list it twice.
    from ..core.services.provider_governance import installed_local_models
    if any(m["id"].lower() == model_id.lower() for m in installed_local_models()):
        return jsonify({"error": "That model is already provided by the appliance."}), 409
    # Fresh read, not the worker-local cache: a stale cache here would let a
    # duplicate through to the primary-key constraint as a raw 500.
    #
    # Checked UNSCOPED on purpose, because model_id is unique per deployment
    # (see the schema comment: detect_provider resolves an id to a provider with
    # no org in scope). The wording says only that the id is taken, never which
    # org holds it, its label or its provider.
    if any(r["model_id"].lower() == model_id.lower() for r in db.list_custom_models()):
        return jsonify({"error": "That model id is already registered on this deployment."}), 409

    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    # Owned by the caller's org, so only that org sees it and only that org can
    # remove it. An org-less caller (an operator on a deployment with no org)
    # publishes deployment-wide, which is the original operator-catalog intent.
    org_id = get_current_org_id()
    db.add_custom_model(model_id, label[:120], provider,
                        created_by=user_id, org_id=org_id or '')
    invalidate_custom_models_cache()

    # A catalog change alters what this org can be offered, so evidence it.
    if org_id:
        try:
            db.append_compliance_log(org_id, 'model_catalog_change', f"user:{user_id}",
                                     {"action": "add", "model": model_id, "provider": provider})
        except Exception as e:
            current_app.logger.error(f"model catalog evidence failed: {e}")

    return jsonify({"ok": True})


@model_api_bp.route('/models/custom', methods=['DELETE'])
@require_role('admin')
def delete_custom():
    # Query param, not a path segment: model ids contain '/' (e.g.
    # openai/gpt-oss-120b) and encoded slashes are unreliable behind Apache.
    model_id = (request.args.get('model_id') or '').strip()
    if not model_id:
        return jsonify({"error": "Missing model_id."}), 400
    # Restricted to the caller's own org (backlog 77): any tenant admin used to
    # be able to delete another org's model, or a deployment-wide one, and the
    # affected org's users would silently fall back to the default model. A row
    # this org does not own is reported as not found, which is both true from
    # the caller's scope and free of information about other tenants.
    #
    # A deployment operator is unrestricted, because deployment-wide rows
    # (org_id '') belong to no org: without this they were deletable by nobody
    # holding an org, which is every admin on a normal install.
    org_id = get_current_org_id()
    scope = None if _is_deployment_operator() else (org_id or '')
    if not db.delete_custom_model(model_id, org_id=scope):
        return jsonify({"error": "Not found."}), 404
    invalidate_custom_models_cache()

    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    if org_id:
        try:
            db.append_compliance_log(org_id, 'model_catalog_change', f"user:{user_id}",
                                     {"action": "remove", "model": model_id})
        except Exception as e:
            current_app.logger.error(f"model catalog evidence failed: {e}")

    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# deployment-wide provider keys
# --------------------------------------------------------------------------
# The org-scoped equivalents live in api/organizations.py. These exist because
# an appliance has no organization: without them the Cloud pane's key table was
# org-gated, so the only way to give an org-less deployment a cloud provider
# was to edit .env over SSH. Layering is org key > deployment key > .env, so a
# tenant key still wins over anything stored here.

@model_api_bp.route('/providers/keys', methods=['GET'])
@require_role('admin')
def list_deployment_keys():
    """Display shape only (provider, last 4, updated). The key is write-only
    from the UI's point of view and is never returned by any endpoint."""
    from ..core.services.model_routing import configured_providers
    denied = _deployment_keys_forbidden()
    if denied:
        return denied
    # .env-only on purpose. This flag answers "do I need to add a fallback to
    # .env for this?", and it must stay true after a key is stored in the DB —
    # reading the effective set instead made a stored key immediately report
    # itself as .env-configured, which is the one thing it isn't.
    env_configured = configured_providers(Config)
    try:
        return jsonify({
            "ok": True,
            "keys": [
                {"provider": r["provider"], "last4": r["last4"],
                 "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None}
                for r in db.list_deployment_provider_keys()
            ],
            "providers": [
                {"id": p, "label": PROVIDER_METADATA[p]["label"],
                 "env_configured": p in env_configured}
                for p in sorted(PROVIDER_METADATA)
            ],
        })
    except Exception as e:
        current_app.logger.error(f"Error listing deployment provider keys: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@model_api_bp.route('/providers/keys', methods=['PUT'])
@require_role('admin')
def set_deployment_key():
    """Stores the deployment's own key for one provider, encrypted. It
    overlays the .env default for every call that has no org key, within a
    minute. Never echoed back, never logged."""
    from ..core.services.deployment_keys import invalidate_deployment_keys_cache
    denied = _deployment_keys_forbidden()
    if denied:
        return denied
    data = request.json or {}
    provider = (data.get('provider') or '').strip().lower()
    key = (data.get('key') or '').strip()
    if provider not in PROVIDER_METADATA:
        return jsonify({"error": f"Unknown provider '{provider}'."}), 400
    if len(key) < 8 or len(key) > 512 or any(c.isspace() for c in key):
        return jsonify({"error": "That does not look like an API key."}), 400
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    try:
        db.set_deployment_provider_key(provider, key, updated_by=user_id)
        invalidate_deployment_keys_cache()
        # The custom-model list is cached per worker too, and a new key changes
        # which providers it offers; drop it so the new provider appears now.
        invalidate_custom_models_cache()
        return jsonify({"ok": True, "provider": provider, "last4": key[-4:]})
    except Exception as e:
        current_app.logger.error(f"Error storing deployment provider key: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@model_api_bp.route('/providers/keys', methods=['DELETE'])
@require_role('admin')
def delete_deployment_key():
    """Removes the deployment key; calls fall back to the .env default."""
    from ..core.services.deployment_keys import invalidate_deployment_keys_cache
    denied = _deployment_keys_forbidden()
    if denied:
        return denied
    provider = (request.args.get('provider') or '').strip().lower()
    if not provider:
        return jsonify({"error": "Missing provider."}), 400
    try:
        if not db.delete_deployment_provider_key(provider):
            return jsonify({"error": "No deployment key stored for that provider."}), 404
        invalidate_deployment_keys_cache()
        invalidate_custom_models_cache()
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"Error deleting deployment provider key: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500
