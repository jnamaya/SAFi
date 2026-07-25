from flask import Blueprint, jsonify, session

from ..config import Config
from ..persistence import database as db
from ..core.services.provider_governance import list_models_for_org

model_api_bp = Blueprint('model_api', __name__)


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
