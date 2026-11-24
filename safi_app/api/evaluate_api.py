import os

from flask import Blueprint, jsonify, request, current_app

from ..persistence import database as db
from ..config import Config
from ..core import provenance
from ..core.services.model_routing import resolve_effective_faculty_models
from .conversations import global_safi_cache

evaluate_bp = Blueprint('evaluate', __name__)


@evaluate_bp.route('/evaluate', methods=['POST'])
async def evaluate_endpoint():
    api_key = request.headers.get("X-API-KEY") or request.headers.get("Authorization", "")
    if api_key.startswith("Bearer "):
        api_key = api_key.split(" ")[1]

    policy_id = db.get_policy_id_by_api_key(api_key)
    if not policy_id:
        return jsonify({"error": "Unauthorized: Invalid Policy API Key"}), 401

    data = request.get_json(silent=True) or {}
    agent_id = str(data.get('agent_id') or "").strip()
    user_prompt = data.get('input')
    agent_output = data.get('output')
    if not agent_id or not user_prompt or not agent_output:
        return jsonify({"error": "Missing required fields: agent_id, input, output"}), 400

    agent_key = data.get('agent', 'safi')
    session_id = str(data.get('session_id') or agent_id).strip()
    conversation_id = session_id if session_id.startswith("gw_") else f"gw_{session_id}"
    user_id = f"gateway:{agent_id}"

    try:
        user_details = db.get_user_details(user_id)
        if not user_details:
            db.upsert_user({
                "sub": user_id,
                "id": user_id,
                "name": f"Gateway Agent {agent_id}",
                "email": f"{agent_id}@{Config.GATEWAY_EMAIL_DOMAIN}",
                "picture": ""
            })

        if not db.ensure_conversation_access(user_id, conversation_id):
            return jsonify({"error": "session_id belongs to another principal"}), 403

        policy = db.get_policy(policy_id) or {}
        org_id = policy.get('org_id') or (user_details or {}).get('org_id')

        intellect_model, conscience_model = resolve_effective_faculty_models(
            Config,
            Config.INTELLECT_MODEL,
            Config.CONSCIENCE_MODEL,
            org_id,
            intellect_explicit=bool(os.environ.get("SAFI_INTELLECT_MODEL")),
            conscience_explicit=bool(os.environ.get("SAFI_CONSCIENCE_MODEL")),
        )
        saf_system = global_safi_cache.get_or_create(
            agent_key,
            intellect_model,
            None,
            conscience_model,
            policy_id=policy_id,
            org_id=org_id,
        )

        result = await saf_system.evaluate_output(
            user_prompt=user_prompt,
            agent_output=agent_output,
            user_id=user_id,
            conversation_id=conversation_id,
            org_id=org_id,
        )
        if isinstance(result, dict):
            result.setdefault("caller_obligations", {
                "eu_ai_act_art_50_1": (
                    "If this output is presented to end users, the duty to "
                    "disclose that they are interacting with an AI system "
                    "rests with the deploying caller."
                )
            })
            result["aiProvenance"] = provenance.ai_marker(evaluator_only=True)
        return provenance.mark_json_response(jsonify(result))

    except Exception as e:
        current_app.logger.error(f"Gateway evaluation error: {e}", exc_info=True)
        return jsonify({"error": "Internal error evaluating output"}), 500
