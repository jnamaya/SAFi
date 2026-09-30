import json
from flask import Blueprint, request, jsonify, g, session, current_app
from ..persistence import database as db

profile_bp = Blueprint('profile_api', __name__)

@profile_bp.route('/me/profile', methods=['GET'])
def get_user_profile():
    """Reads the authenticated user's persistent profile (facts, values, interests)."""
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    
    g.user_id = user_id
    
    try:
        profile_json_string = db.fetch_user_profile_memory(g.user_id)
        profile_data = json.loads(profile_json_string)
        return jsonify(profile_data), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching profile for {g.user_id}: {e}")
        return jsonify({"error": "Could not fetch profile"}), 500

@profile_bp.route('/me/profile', methods=['POST'])
def update_user_profile():
    """Overwrites the authenticated user's persistent profile."""
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    
    g.user_id = user_id
        
    try:
        new_profile_data = request.json
        if not isinstance(new_profile_data, dict):
            return jsonify({"error": "Invalid JSON payload"}), 400
            
        new_profile_json_string = json.dumps(new_profile_data)
        db.upsert_user_profile_memory(g.user_id, new_profile_json_string)
        
        return jsonify({"status": "success", "profile": new_profile_data}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating profile for {g.user_id}: {e}")
        return jsonify({"error": "Could not update profile"}), 500