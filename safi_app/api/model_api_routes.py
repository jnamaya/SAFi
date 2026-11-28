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

_MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$')


def _is_deployment_operator():
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    if user_id == 'local_admin':
        return True
    details = db.get_user_details(user_id) or {}
    email = (details.get('email') or user.get('email') or '').lower()
    supers = {e.lower() for e in Config.SUPER_ADMIN_EMAILS}
    return bool(email) and email in supers


def _deployment_keys_forbidden():
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
    user = session.get('user')
    org_id = None
    user_id = None
    user_role = None
    if user:
        user_id = user.get('sub') or user.get('id')
        details = db.get_user_details(user_id) or {}
        org_id = details.get('org_id')
        user_role = details.get('role') or user.get('role')
    else:
        raw_key = request.headers.get("X-API-KEY") or request.headers.get("Authorization", "")
        if raw_key.startswith("Bearer "):
            raw_key = raw_key.split(" ", 1)[1]
        raw_key = raw_key.strip()
        if raw_key:
            from ._api_key_auth import resolve_api_key_identity
            policy_id, key_uid, key_org, key_role = resolve_api_key_identity(raw_key)
            if policy_id:
                org_id = key_org
                user_id = key_uid
                user_role = key_role
            else:
                return jsonify({"error": "Unauthorized: Invalid API Key"}), 401
        else:
            return jsonify({"error": "Unauthorized"}), 401

    x_user_id = request.headers.get("X-User-ID")
    if x_user_id and user and user_role == "admin" and org_id:
        u_det = db.get_user_details(x_user_id)
        if u_det and u_det.get("org_id") == org_id:
            user_id = u_det["id"]
            user_role = u_det.get("role") or user_role

    from ..core.services.provider_governance import list_models_for_user
    return jsonify({
        "ok": True,
        "models": list_models_for_user(user_id, org_id, user_role),
        "public_demo_ui": Config.PUBLIC_DEMO_UI,
    })


@model_api_bp.route('/models/local', methods=['GET'])
@require_role('admin')
def list_local_models():
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
        current_app.logger.warning("Local model management unavailable for %s: %s", model_id, exc)
        return jsonify({'error': 'Local model management is unavailable.'}), 503
    if result.returncode:
        current_app.logger.warning(
            "safi-model-manage failed for %s (rc=%s): %s",
            model_id,
            result.returncode,
            (result.stderr or result.stdout or "").strip()[:500],
        )
        fallback = 'Unable to load model.' if activate else 'Unable to start local model download.'
        return jsonify({'error': fallback}), 409
    return jsonify({'ok': True})


@model_api_bp.route('/models/custom', methods=['GET'])
@require_role('admin')
def list_custom():
    from ..core.services.model_routing import effective_configured_providers
    configured = effective_configured_providers(Config, get_current_org_id())

    is_operator = _is_deployment_operator()
    rows = (db.list_custom_models() if is_operator
            else db.list_custom_models(visible_to_org=get_current_org_id() or ''))
    return jsonify({
        "ok": True,
        "models": [
            {"id": r["model_id"], "label": r["label"], "provider": r["provider"],
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
    from ..core.services.provider_governance import installed_local_models
    if any(m["id"].lower() == model_id.lower() for m in installed_local_models()):
        return jsonify({"error": "That model is already provided by the appliance."}), 409
    if any(r["model_id"].lower() == model_id.lower() for r in db.list_custom_models()):
        return jsonify({"error": "That model id is already registered on this deployment."}), 409

    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    org_id = get_current_org_id()
    db.add_custom_model(model_id, label[:120], provider,
                        created_by=user_id, org_id=org_id or '')
    invalidate_custom_models_cache()

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
    model_id = (request.args.get('model_id') or '').strip()
    if not model_id:
        return jsonify({"error": "Missing model_id."}), 400
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


@model_api_bp.route('/providers/keys', methods=['GET'])
@require_role('admin')
def list_deployment_keys():
    from ..core.services.model_routing import configured_providers
    denied = _deployment_keys_forbidden()
    if denied:
        return denied
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
        invalidate_custom_models_cache()
        return jsonify({"ok": True, "provider": provider, "last4": key[-4:]})
    except Exception as e:
        current_app.logger.error(f"Error storing deployment provider key: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@model_api_bp.route('/providers/keys', methods=['DELETE'])
@require_role('admin')
def delete_deployment_key():
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
