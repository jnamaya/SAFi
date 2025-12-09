from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
import logging

policy_api_bp = Blueprint('policy_api', __name__)

@policy_api_bp.route('/policies', methods=['POST'], strict_slashes=False)
def create_policy():
    """
    [POST /api/policies]
    Creates a new Policy.
    Payload: { "name": "...", "worldview": "...", "will_rules": [...], "values": [...] }
    """
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    if not user_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        data = request.get_json()
        name = data.get("name")
        worldview = data.get("worldview", "")
        will_rules = data.get("will_rules", [])
        values = data.get("values", [])
        
        if not name:
            return jsonify({"ok": False, "error": "Policy name is required"}), 400
            
        policy_id = db.create_policy(name=name, worldview=worldview, will_rules=will_rules, values=values)
        
        return jsonify({"ok": True, "policy_id": policy_id}), 201

    except Exception as e:
        current_app.logger.error(f"Error creating policy: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies', methods=['GET'], strict_slashes=False)
def list_policies():
    """
    [GET /api/policies]
    Lists all policies.
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        policies = db.list_policies()
        return jsonify({"ok": True, "policies": policies})
    except Exception as e:
        current_app.logger.error(f"Error listing policies: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['GET'])
def get_policy(policy_id):
    """
    [GET /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        policy = db.get_policy(policy_id)
        if not policy:
            return jsonify({"ok": False, "error": "Policy not found"}), 404
        return jsonify({"ok": True, "policy": policy})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['PUT'])
def update_policy(policy_id):
    """
    [PUT /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        data = request.get_json()
        db.update_policy(
            policy_id,
            name=data.get("name"),
            worldview=data.get("worldview"),
            will_rules=data.get("will_rules"),
            values=data.get("values")
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['DELETE'])
def delete_policy(policy_id):
    """
    [DELETE /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        db.delete_policy(policy_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['POST'])
def generate_key(policy_id):
    """
    [POST /api/policies/<id>/keys]
    Generates a new API key for the policy.
    Returns the RAW key once.
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        data = request.get_json() or {}
        label = data.get("label", "Default Key")
        
        raw_key = db.create_api_key(policy_id, label)
        
        return jsonify({"ok": True, "api_key": raw_key}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['GET'])
def list_keys(policy_id):
    """
    [GET /api/policies/<id>/keys]
    Returns metadata of keys (masked).
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        keys = db.get_policy_keys(policy_id)
        return jsonify({"ok": True, "keys": keys})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
