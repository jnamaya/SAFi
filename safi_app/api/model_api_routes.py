import re

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
    """A named deployment operator (SAFI_SUPER_ADMINS), never an org role.

    Deployment-wide catalog rows (org_id '') belong to the deployment, not to a
    tenant, so scoping deletes to the caller's org left them unmanageable by
    ANYONE holding an org: every org-scoped delete misses them. Operators are who
    the deployment-wide catalog was always for, so they are who can remove from
    it. Blank SAFI_SUPER_ADMINS = nobody, the same safe default the usage
    rollup uses.
    """
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    details = db.get_user_details(user_id) or {}
    email = (details.get('email') or user.get('email') or '').lower()
    supers = {e.lower() for e in Config.SUPER_ADMIN_EMAILS}
    return bool(email) and email in supers


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


@model_api_bp.route('/models/custom', methods=['GET'])
@require_role('admin')
def list_custom():
    """The operator-added rows plus the provider options for the add form
    (backlog 63). Reads the DB directly, NOT the 60s custom_models() cache:
    that cache is per gunicorn worker, so right after an add the worker
    serving this list may still hold the pre-add copy — the management view
    must always show what is actually stored. Only providers with a
    configured .env key are offered: a model that cannot dispatch must not
    be addable."""
    from ..core.services.model_routing import configured_providers
    configured = configured_providers(Config)
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
    from ..core.services.model_routing import configured_providers
    if provider not in configured_providers(Config):
        return jsonify({"error": f"No API key is configured for '{provider}', so this model could never dispatch."}), 400
    if any(m["id"].lower() == model_id.lower() for m in Config.AVAILABLE_MODELS):
        return jsonify({"error": "That model is already in the built-in catalog."}), 409
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
