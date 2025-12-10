from flask import Blueprint, request, jsonify, session
from ..persistence import database as db
from ..core.permissions import can_perform

members_bp = Blueprint('members_api', __name__)

@members_bp.route('/org/members', methods=['GET'], strict_slashes=False)
def list_members():
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    org_id = user.get('org_id')
    if not org_id: return jsonify({"error": "No Organization Context"}), 400
    
    # Any member can view the team list? Yes, usually.
    members = db.list_org_members(org_id)
    return jsonify({"ok": True, "members": members})

@members_bp.route('/org/members', methods=['POST'], strict_slashes=False)
def invite_member():
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    role = user.get('role', 'member')
    if role != 'admin': return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json(force=True, silent=True)
    email = data.get('email')
    target_role = data.get('role', 'member')
    
    if not email: return jsonify({"error": "Email required"}), 400
    
    org_id = user.get('org_id')
    result = db.add_member_by_email(org_id, email, target_role)
    
    if "error" in result:
        return jsonify(result), 400
        
    return jsonify({"ok": True, "user": result['user']})

@members_bp.route('/org/members/<target_uid>', methods=['PUT'], strict_slashes=False)
def update_member(target_uid):
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    role = user.get('role', 'member')
    if role != 'admin': return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json(force=True, silent=True)
    new_role = data.get('role')
    
    if not new_role: return jsonify({"error": "Role required"}), 400
    if new_role not in ['admin', 'editor', 'auditor', 'member']:
         return jsonify({"error": "Invalid role"}), 400
    
    org_id = user.get('org_id')
    
    # Self-demotion check? 
    # Technically allowed, but dangerous. UI should warn.
    
    db.update_member_role(org_id, target_uid, new_role)
    return jsonify({"ok": True})

@members_bp.route('/org/members/<target_uid>', methods=['DELETE'], strict_slashes=False)
def remove_member(target_uid):
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    role = user.get('role', 'member')
    if role != 'admin': return jsonify({"error": "Forbidden"}), 403
    
    org_id = user.get('org_id')
    
    # Cannot remove self?
    if str(target_uid) == str(user['id']):
         return jsonify({"error": "Cannot remove yourself."}), 400
    
    db.remove_member(org_id, target_uid)
    return jsonify({"ok": True})
