from flask import Blueprint, jsonify, request, current_app, session
import uuid
import json
import dns.resolver
from ..persistence import database as db
from ..core.rbac import require_role, check_permission, get_current_org_id
# Same check the governance compiler uses, applied at save time: what would
# raise at chat time is rejected while the admin is still looking at the form.
from ..core.faculties.synderesis import _has_usable_rubric

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
        return jsonify({"error": "An internal error occurred."}), 500

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
        current_app.logger.error(f"update_organization_policy error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

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
        actor = f"user:{(session.get('user') or {}).get('id')}"
        if name:
            db.update_organization_name(org_id, name)
            db.append_compliance_log(org_id, 'org_renamed', actor, {"name": name})

        if settings:
            # governance_split and spirit_beta change how every agent in the org
            # is scored, so the VALUES are the evidence here, not just the fact
            # that something moved.
            before = {}
            try:
                existing = (db.get_organization(org_id) or {}).get('settings') or {}
                if isinstance(existing, str):
                    existing = json.loads(existing)
                before = {k: existing.get(k) for k in settings.keys()}
            except Exception:
                pass
            db.update_organization_settings(org_id, settings)
            db.append_compliance_log(org_id, 'org_settings_changed', actor,
                                     {"changed": sorted(settings.keys()),
                                      "before": before, "after": settings})

        return jsonify({"status": "updated", "id": org_id, "name": name})
    except Exception as e:
        current_app.logger.error(f"Error updating org: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


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
        return jsonify({"error": "An internal error occurred."}), 500

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
        db.update_member_role(user_id, org_id, new_role, actor=_actor())
        return jsonify({"status": "updated", "user_id": user_id, "role": new_role})
    except db.LastAdminError as e:
        # 409: valid request, conflicts with current state. The message is
        # deliberately surfaced — a generic 500 here would leave the admin with
        # no idea why the change was refused or how to proceed.
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        current_app.logger.error(f"Error updating role: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

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
        db.remove_member_from_org(user_id, org_id, actor=_actor())
        return jsonify({"status": "removed", "user_id": user_id})
    except db.LastAdminError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        current_app.logger.error(f"Error removing member: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


# -------------------------------------------------------------------------
# ENTERPRISE IDENTITY (Phase 1): member sessions, invitations, identity config
# -------------------------------------------------------------------------

def _actor():
    user = session.get('user') or {}
    return user.get('email') or user.get('id') or 'unknown'


def _member_of_org(org_id, user_id):
    details = db.get_user_details(user_id)
    return bool(details and str(details.get('org_id')) == str(org_id))


@organizations_bp.route('/organizations/<org_id>/members/<user_id>/sessions', methods=['GET'])
@require_role('admin')
def list_member_sessions(org_id, user_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    if not _member_of_org(org_id, user_id):
        return jsonify({"error": "Not a member of this organization"}), 404
    rows = db.list_user_sessions(user_id)
    return jsonify({"ok": True, "sessions": [{
        "id": r["id"][:8] + "…",  # opaque preview — admins revoke in bulk, never need the full sid
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "last_seen_at": r["last_seen_at"].isoformat() if r.get("last_seen_at") else None,
        "ip": r.get("ip"), "user_agent": r.get("user_agent"),
    } for r in rows]})


@organizations_bp.route('/organizations/<org_id>/members/<user_id>/sessions', methods=['DELETE'])
@require_role('admin')
def revoke_member_sessions(org_id, user_id):
    """Force-logout a member everywhere (admin off-boarding lever)."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    if not _member_of_org(org_id, user_id):
        return jsonify({"error": "Not a member of this organization"}), 404
    count = db.revoke_user_sessions(user_id, f"admin:{_actor()}")
    return jsonify({"ok": True, "revoked": count})


@organizations_bp.route('/organizations/<org_id>/invitations', methods=['GET'])
@require_role('admin')
def list_invitations(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    rows = db.list_org_invitations(org_id)
    for r in rows:
        for k in ('created_at', 'expires_at', 'accepted_at', 'revoked_at'):
            if r.get(k) is not None:
                r[k] = r[k].isoformat()
    return jsonify({"ok": True, "invitations": rows})


@organizations_bp.route('/organizations/<org_id>/invitations', methods=['POST'])
@require_role('admin')
def create_invitation(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    try:
        inv = db.create_org_invitation(org_id, data.get('email'),
                                       data.get('role', 'member'), _actor())
        return jsonify({"ok": True, "invitation": inv}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating invitation: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@organizations_bp.route('/organizations/<org_id>/invitations/<invite_id>', methods=['DELETE'])
@require_role('admin')
def revoke_invitation(org_id, invite_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    ok = db.revoke_org_invitation(org_id, invite_id, _actor())
    return (jsonify({"ok": True}) if ok
            else (jsonify({"error": "Invitation not found or already resolved"}), 404))


@organizations_bp.route('/organizations/<org_id>/identity', methods=['GET'])
@require_role('admin')
def get_identity_config(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(db.get_org_identity_config(org_id))


@organizations_bp.route('/organizations/<org_id>/identity', methods=['PUT'])
@require_role('admin')
def update_identity_config(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    changes = {k: data[k] for k in
               ('idle_timeout_minutes', 'session_lifetime_hours', 'join_policy',
                'require_mfa', 'ms_tenant_id', 'google_hd') if k in data}
    try:
        return jsonify(db.set_org_identity_config(org_id, changes, _actor()))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating identity config: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

# -------------------------------------------------------------------------
# CHARTER ROUTES
# -------------------------------------------------------------------------

@organizations_bp.route('/organizations/<org_id>/charter', methods=['GET'])
def get_charter(org_id):
    """
    [GET /api/organizations/<org_id>/charter]
    Returns the org charter, or null if none has been written.
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        charter = db.get_charter(org_id)
        return jsonify({"charter": charter})
    except Exception as e:
        current_app.logger.error(f"Error fetching charter: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@organizations_bp.route('/organizations/<org_id>/charter', methods=['PUT'])
@require_role('admin')
def upsert_charter(org_id):
    """
    [PUT /api/organizations/<org_id>/charter]
    Creates or updates the org charter (Admin only).
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    mission = data.get('mission', '')
    core_values = data.get('core_values', [])

    if not isinstance(core_values, list):
        return jsonify({"error": "core_values must be an array"}), 400

    try:
        user = session.get('user', {})
        # Counts and a diff summary, never the text itself — the convention the
        # log already follows. Enough to answer "who changed the charter, when,
        # and did the values change or only the mission".
        prev = db.get_charter(org_id) or {}
        db.upsert_charter(org_id, mission, core_values, created_by=user.get('id'))
        db.append_compliance_log(org_id, 'charter_saved', f"user:{user.get('id')}", {
            "created": not prev,
            "mission_changed": (prev.get('mission') or '') != (mission or ''),
            "core_values_before": len(prev.get('core_values') or []),
            "core_values_after": len(core_values),
        })
        return jsonify({"status": "saved", "org_id": org_id})
    except Exception as e:
        current_app.logger.error(f"Error saving charter: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@organizations_bp.route('/organizations/<org_id>/charter', methods=['DELETE'])
@require_role('admin')
def delete_charter(org_id):
    """
    [DELETE /api/organizations/<org_id>/charter]
    Deletes the org charter (Admin only).
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        prev = db.get_charter(org_id) or {}
        db.delete_charter(org_id)
        db.append_compliance_log(
            org_id, 'charter_deleted', f"user:{(session.get('user') or {}).get('id')}",
            {"core_values_removed": len(prev.get('core_values') or [])})
        return jsonify({"status": "deleted", "org_id": org_id})
    except Exception as e:
        current_app.logger.error(f"Error deleting charter: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


# --- Org AI Standards -------------------------------------------------------
# A separate resource from the charter, because they are separate artifacts: a
# charter is who the organization is and every organization has one; AI
# standards say how its AI must behave and are optional. Adopting or dropping
# them must not touch the charter, which is why this is not another field on it.

@organizations_bp.route('/organizations/<org_id>/ai-standards', methods=['GET'])
def get_ai_standards(org_id):
    """[GET] Returns the org's AI standards, or null if none are set."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        return jsonify({"ai_standards": db.get_ai_standards(org_id)})
    except Exception as e:
        current_app.logger.error(f"Error fetching AI standards: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@organizations_bp.route('/organizations/<org_id>/ai-standards', methods=['PUT'])
@require_role('admin')
def upsert_ai_standards(org_id):
    """[PUT] Creates or updates the org's AI standards (Admin only)."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    values = data.get('values', []) or []
    structural = data.get('structural_requirements', {}) or {}
    blacklist = data.get('early_prompt_blacklist', []) or []
    allowed_tools = data.get('allowed_tools', None)

    if not isinstance(values, list):
        return jsonify({"error": "values must be an array"}), 400
    if not isinstance(structural, dict):
        return jsonify({"error": "structural_requirements must be an object"}), 400
    if not isinstance(blacklist, list):
        return jsonify({"error": "early_prompt_blacklist must be an array"}), 400
    if allowed_tools is not None and not isinstance(allowed_tools, list):
        return jsonify({"error": "allowed_tools must be an array or null"}), 400

    # A disclaimer that is required but has no substring to look for is a config
    # error the Will can only log and skip, so it would read as enforced while
    # enforcing nothing — reject it here instead.
    if structural.get('require_disclaimer') and not str(structural.get('mandatory_disclaimer_substring') or '').strip():
        return jsonify({"error": "A required disclaimer needs the exact text to check for."}), 400

    threshold = structural.get('alignment_score_threshold')
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return jsonify({"error": "alignment_score_threshold must be a number"}), 400
        if not 0.0 <= threshold <= 1.0:
            return jsonify({"error": "alignment_score_threshold must be between 0 and 1"}), 400
        structural['alignment_score_threshold'] = threshold

    # Each standard is BLOCKING (a hard gate) or SCORED, chosen per standard.
    # Both are audited, so both need criteria: a blocking one the Conscience
    # cannot score fails closed on every request across the whole organization,
    # and a scored one it cannot score is silently stripped by the compiler and
    # freezes the Spirit average. Reject either at save time.
    cleaned = []
    for v in values:
        if not isinstance(v, dict):
            continue
        name = str(v.get('name') or v.get('value') or '').strip()
        if not name:
            continue
        blocking = bool(v.get('hard_gate'))
        if not _has_usable_rubric(v):
            return jsonify({"error": (
                f"'{name}' has no scoring criteria. " + (
                    "A blocking standard the auditor cannot score would block every response "
                    "from every agent." if blocking else
                    "A scored standard without criteria can never be scored, so it would be "
                    "dropped and would freeze the alignment average."
                )
            )}), 400
        try:
            weight = float(v.get('weight') or 0)
        except (TypeError, ValueError):
            weight = 0.0
        cleaned.append({
            **v, "name": name, "hard_gate": blocking,
            # Blocking standards sit outside the weight split at 0. Scored ones
            # share the organization's slice with the charter's values, so they
            # need a positive weight to be normalized against.
            "weight": 0.0 if blocking else (weight if weight > 0 else 1.0),
        })

    try:
        user = session.get('user', {})
        prev = db.get_ai_standards(org_id) or {}
        db.upsert_ai_standards(
            org_id, values=cleaned, structural_requirements=structural,
            early_prompt_blacklist=blacklist, allowed_tools=allowed_tools,
            created_by=user.get('id'),
        )
        # Blocking standards get named individually: each one can stop every
        # response from every agent, so "which ones were blocking on the day
        # traffic stopped" has to be answerable from the log alone.
        db.append_compliance_log(org_id, 'ai_standards_saved', f"user:{user.get('id')}", {
            "created": not prev,
            "standards_before": len(prev.get('values') or []),
            "standards_after": len(cleaned),
            "blocking": sorted(v['name'] for v in cleaned if v.get('hard_gate')),
            "requires_disclaimer": bool(structural.get('require_disclaimer')),
            "blocked_phrases": len(blacklist),
            "tool_cap": None if allowed_tools is None else len(allowed_tools),
        })
        return jsonify({"status": "saved", "org_id": org_id})
    except Exception as e:
        current_app.logger.error(f"Error saving AI standards: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@organizations_bp.route('/organizations/<org_id>/ai-standards', methods=['DELETE'])
@require_role('admin')
def delete_ai_standards(org_id):
    """[DELETE] Removes the org's AI standards, leaving the charter untouched."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        prev = db.get_ai_standards(org_id) or {}
        db.delete_ai_standards(org_id)
        db.append_compliance_log(
            org_id, 'ai_standards_deleted', f"user:{(session.get('user') or {}).get('id')}",
            {"standards_removed": len(prev.get('values') or [])})
        return jsonify({"status": "deleted", "org_id": org_id})
    except Exception as e:
        current_app.logger.error(f"Error deleting AI standards: {e}")
        return jsonify({"error": "An internal error occurred."}), 500
