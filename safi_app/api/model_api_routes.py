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
    return jsonify({
        "ok": True,
        "models": [
            {"id": r["model_id"], "label": r["label"], "provider": r["provider"]}
            for r in db.list_custom_models()
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
    if any(r["model_id"].lower() == model_id.lower() for r in db.list_custom_models()):
        return jsonify({"error": "That model is already in the catalog."}), 409

    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    db.add_custom_model(model_id, label[:120], provider, created_by=user_id)
    invalidate_custom_models_cache()

    # A catalog change alters what every org can be offered — evidence it.
    org_id = get_current_org_id()
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
    if not db.delete_custom_model(model_id):
        return jsonify({"error": "Not found."}), 404
    invalidate_custom_models_cache()

    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    org_id = get_current_org_id()
    if org_id:
        try:
            db.append_compliance_log(org_id, 'model_catalog_change', f"user:{user_id}",
                                     {"action": "remove", "model": model_id})
        except Exception as e:
            current_app.logger.error(f"model catalog evidence failed: {e}")

    return jsonify({"ok": True})
