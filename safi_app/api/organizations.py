from flask import Blueprint, jsonify, request, current_app, session
import uuid
import dns.resolver
from ..persistence import database as db
from ..core.rbac import require_role, check_permission, get_current_org_id

organizations_bp = Blueprint('organizations', __name__)

@organizations_bp.route('/organizations/domain/start', methods=['POST'])
@require_role('admin')
def start_domain_verification():
    """
    [POST /api/organizations/domain/start]
    Generates a verification token for the given domain.
    """
    data = request.json or {}
    org_id = data.get('org_id')
    domain = data.get('domain')
    
    current_org_id = get_current_org_id()
    current_app.logger.info(f"VERIFY START: Payload org_id={org_id}, Session org_id={current_org_id}")

    # Security check: Ensure user belongs to this org
    if str(org_id) != str(current_org_id):
        return jsonify({"error": f"Forbidden: Mismatch {org_id} vs {current_org_id}"}), 403
    
    if not org_id or not domain:
        return jsonify({"error": "Missing org_id or domain"}), 400
        
    token = f"safi-verification={uuid.uuid4()}"
    
    try:
        db.update_verification_token(org_id, domain, token)
        return jsonify({
            "status": "pending",
            "domain": domain,
            "verification_token": token,
            "instruction": f"Add a TXT record to {domain} with the value: {token}"
        })
    except Exception as e:
        current_app.logger.error(f"Error starting verification: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@organizations_bp.route('/organizations/domain/verify', methods=['POST'])
@require_role('admin')
def verify_domain_dns():
    """
    [POST /api/organizations/domain/verify]
    Checks DNS TXT records for the verification token.
    """
    data = request.json or {}
    org_id = data.get('org_id')
    
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    
    if not org_id:
        return jsonify({"error": "Missing org_id"}), 400
        
    try:
        org = db.get_organization(org_id)
        if not org:
            return jsonify({"error": "Organization not found"}), 404
            
        domain = org.get('domain_to_verify')
        token = org.get('verification_token')
        
        if not domain or not token:
            return jsonify({"error": "No verification in progress."}), 400
            
        current_app.logger.info(f"Looking up TXT records for {domain}...")
        answers = dns.resolver.resolve(domain, 'TXT')
        found = False
        for rdata in answers:
            txt_value = rdata.to_text().strip('"')
            if token in txt_value:
                found = True
                break
        
        if found:
            db.confirm_domain_verification(org_id)
            
            # NEW: Auto-rename organization to match verified domain
            # This standardizes the org name (e.g., "My Org" -> "safinstitute.org")
            try:
                db.update_organization_name(org_id, domain)
                current_app.logger.info(f"Auto-renamed Org {org_id} to {domain}")
            except Exception as e:
                current_app.logger.error(f"Failed to auto-rename org verify: {e}")

            return jsonify({"status": "verified", "domain": domain})
        else:
            return jsonify({
                "status": "failed", 
                "error": "Token not found in DNS TXT records."
            }), 200 # Return 200 so frontend handles it gracefully
            
    except dns.resolver.NXDOMAIN:
        return jsonify({"status": "failed", "error": "Domain does not exist."}), 200
        current_app.logger.error(f"DNS Lookup Failed: {e}")
        return jsonify({"error": f"DNS Lookup Failed: {str(e)}"}), 500

@organizations_bp.route('/organizations/domain/cancel', methods=['POST'])
@require_role('admin')
def cancel_domain_verification():
    """
    [POST /api/organizations/domain/cancel]
    Cancels a pending domain verification.
    """
    data = request.json or {}
    org_id = data.get('org_id')
    
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    
    if not org_id:
        return jsonify({"error": "Missing org_id"}), 400
        
    try:
        db.reset_domain_verification(org_id)
        current_app.logger.info(f"Verification cancelled for org {org_id}")
        return jsonify({"status": "cancelled", "org_id": org_id})
    except Exception as e:
        current_app.logger.error(f"Error cancelling verification: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@organizations_bp.route('/organizations', methods=['POST'])
# No Role required strictly, but usually only authenticated users can create orgs
# If we want to limit org creation, we can add a check. For now, any user can create.
def create_organization():
    """
    [POST /api/organizations]
    Creates Organization + Default Policy (Atomic).
    """
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    name = data.get('name')
    if not name: return jsonify({"error": "Organization Name is required"}), 400
        
    try:
        result = db.create_organization_atomic(name, user_id)
        
        # Determine logic for session update? 
        # Ideally the user's generic session should update, but for now we just return ID
        
        return jsonify({
            "status": "created", 
            "id": result['org_id'], 
            "name": name,
            "default_policy_id": result['policy_id']
        })
    except Exception as e:
        current_app.logger.error(f"Error creating org: {e}")
        return jsonify({"error": str(e)}), 500

@organizations_bp.route('/organizations/<org_id>/policy', methods=['POST'])
@require_role('admin')
def update_organization_policy(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    policy_id = data.get('policy_id') or None
    try:
        db.set_organization_global_policy(org_id, policy_id)
        return jsonify({"status": "updated", "global_policy_id": policy_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@organizations_bp.route('/organizations/me', methods=['GET'])
def get_my_organization():
    user = session.get('user')
    if not user or not user.get('email'): return jsonify({"organization": None})
    
    # FIX: Prefer DB org_id over email domain if available
    if user.get('org_id'):
       org = db.get_organization(user['org_id'])
       return jsonify({"organization": org})
       
    return jsonify({"organization": None})

@organizations_bp.route('/organizations/<org_id>', methods=['PUT'])
@require_role('admin')
def update_organization(org_id):
    """
    [PUT /api/organizations/<org_id>]
    Updates organization details (e.g., name).
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    name = data.get('name')
    settings = data.get('settings')
    
    if not name and not settings:
        return jsonify({"error": "No changes provided (name or settings required)"}), 400
        
    try:
        if name:
            db.update_organization_name(org_id, name)
        
        if settings:
            db.update_organization_settings(org_id, settings)

        return jsonify({"status": "updated", "id": org_id, "name": name})
    except Exception as e:
        current_app.logger.error(f"Error updating org: {e}")
        return jsonify({"error": str(e)}), 500


@organizations_bp.route('/organizations/<org_id>/members', methods=['GET'])
def list_organization_members(org_id):
    """
    [GET /api/organizations/<org_id>/members]
    Lists all members of the organization.
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        members = db.get_organization_members(org_id)
        return jsonify({"members": members})
    except Exception as e:
        current_app.logger.error(f"Error listing members: {e}")
        return jsonify({"error": str(e)}), 500

@organizations_bp.route('/organizations/<org_id>/members/<user_id>/role', methods=['PUT'])
@require_role('admin')
def update_user_role(org_id, user_id):
    """
    [PUT /api/organizations/<org_id>/members/<user_id>/role]
    Updates a member's role (Admin only).
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
        
    data = request.json or {}
    new_role = data.get('role')
    
    valid_roles = ['admin', 'editor', 'auditor', 'member']
    if new_role not in valid_roles:
        return jsonify({"error": "Invalid role"}), 400
        
    try:
        db.update_member_role(user_id, org_id, new_role)
        return jsonify({"status": "updated", "user_id": user_id, "role": new_role})
    except Exception as e:
        current_app.logger.error(f"Error updating role: {e}")
        return jsonify({"error": str(e)}), 500

@organizations_bp.route('/organizations/<org_id>/members/<user_id>', methods=['DELETE'])
@require_role('admin')
def remove_organization_member(org_id, user_id):
    """
    [DELETE /api/organizations/<org_id>/members/<user_id>]
    Removes a member from the organization (Admin only).
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
        
    try:
        db.remove_member_from_org(user_id, org_id)
        return jsonify({"status": "removed", "user_id": user_id})
    except Exception as e:
        current_app.logger.error(f"Error removing member: {e}")
        return jsonify({"error": str(e)}), 500
