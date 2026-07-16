"""
Headless governance gateway.

POST /api/evaluate lets an EXTERNAL agent (or its harness) submit an
input/output pair for governance under a SAFi Policy — Conscience audit,
Will hard gates, Spirit alignment — without SAFi generating anything.
Authentication is the Policy API key (same contract as /bot/process_prompt);
the key alone selects the governing policy, and every evaluation is persisted
to chat_history so it is covered by the hash-chained audit trail, retention
engine, and examiner export exactly like a native turn.

Caller obligations: SAFi governs the output but does not present it. If the
evaluated output is shown to end users, the EU AI Act Art. 50(1) duty to
disclose AI interaction rests with the deploying caller — SAFi's disclosure
covers only its own surfaces. Every response repeats this in
`caller_obligations` so external deployers cannot miss it.
"""
from flask import Blueprint, jsonify, request, current_app

from ..persistence import database as db
from ..config import Config
from .conversations import global_safi_cache

evaluate_bp = Blueprint('evaluate', __name__)


@evaluate_bp.route('/evaluate', methods=['POST'])
async def evaluate_endpoint():
    # 1. Security: Policy API key
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

    persona_key = data.get('persona', 'safi')
    # One rolling session per external agent unless the caller tracks its own;
    # the gw_ namespace keeps gateway sessions from colliding with native
    # conversation ids (Spirit drift continuity accrues per conversation).
    session_id = str(data.get('session_id') or agent_id).strip()
    conversation_id = session_id if session_id.startswith("gw_") else f"gw_{session_id}"
    # Namespaced principal so the 17a-4 actor identifier is unique and can
    # never collide with a human user id.
    user_id = f"gateway:{agent_id}"

    try:
        # 2. Just-in-time registration of the external agent as a principal
        user_details = db.get_user_details(user_id)
        if not user_details:
            db.upsert_user({
                "sub": user_id,
                "id": user_id,
                "name": f"Gateway Agent {agent_id}",
                "email": f"{agent_id}@gateway.safinstitute.org",
                "picture": ""
            })

        # 3. Claim (or verify ownership of) the evaluation session
        if not db.ensure_conversation_access(user_id, conversation_id):
            return jsonify({"error": "session_id belongs to another principal"}), 403

        # 4. Attribution: the governing policy's org owns the record
        policy = db.get_policy(policy_id) or {}
        org_id = policy.get('org_id') or (user_details or {}).get('org_id')

        # 5. Governed instance (cached), policy injected over the persona
        saf_system = global_safi_cache.get_or_create(
            persona_key,
            Config.INTELLECT_MODEL,
            None,
            Config.CONSCIENCE_MODEL,
            policy_id=policy_id
        )

        # 6. Evaluate — never generates, never redirects
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
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Gateway evaluation error: {e}", exc_info=True)
        return jsonify({"error": "Internal error evaluating output"}), 500
