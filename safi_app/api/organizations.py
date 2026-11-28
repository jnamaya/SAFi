from flask import Blueprint, jsonify, request, current_app, session
import uuid
import base64
import json
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
import requests
import dns.resolver
import dns.exception
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ..persistence import database as db
from ..bootstrap import create_organization
from ..role_config import ROLE_CONFIG
from ..timeutil import utc_isoformat
from ..config import Config
from ..core import pii_validators
from .. import security_policy
from ..core.rbac import require_role, check_permission, get_current_org_id
from ..core import integrity
from ..core.faculties.synderesis import _has_usable_rubric

organizations_bp = Blueprint('organizations', __name__)


def _domain_uses_google_workspace(domain):
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        return any(
            host in str(rdata.exchange).lower()
            for rdata in answers
            for host in ('google.com', 'googlemail.com')
        )
    except Exception:
        return False


def _discover_ms_tenant_id(domain):
    try:
        resp = requests.get(
            f"https://login.microsoftonline.com/{domain}/v2.0/.well-known/openid-configuration",
            timeout=5,
        )
        if resp.status_code != 200:
            return None
        issuer = (resp.json().get("issuer") or "").rstrip("/")
        candidate = issuer.split("/")[-2] if issuer.count("/") >= 2 else ""
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", candidate, re.I):
            return candidate.lower()
        return None
    except Exception:
        return None


@organizations_bp.route('/organizations/domain/start', methods=['POST'])
@require_role('admin')
def start_domain_verification():
    data = request.json or {}
    org_id = data.get('org_id')
    domain = data.get('domain')
    
    current_org_id = get_current_org_id()
    current_app.logger.info(f"VERIFY START: Payload org_id={org_id}, Session org_id={current_org_id}")

    if str(org_id) != str(current_org_id):
        return jsonify({"error": f"Forbidden: Mismatch {org_id} vs {current_org_id}"}), 403
    
    if not org_id or not domain:
        return jsonify({"error": "Missing org_id or domain"}), 400

    existing = db.get_organization_by_domain(str(domain).strip().lower())
    if existing and str(existing['id']) != str(org_id):
        return jsonify({
            "error": "That domain is already verified by another organization on "
                     "this deployment. If it belongs to you, contact support to "
                     "reconcile the two organizations."
        }), 409

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

        owner = db.get_organization_by_domain(str(domain).strip().lower())
        if owner and str(owner['id']) != str(org_id):
            return jsonify({
                "status": "failed",
                "error": "That domain has since been verified by another "
                         "organization on this deployment. Contact support to "
                         "reconcile the two organizations."
            }), 409

        current_app.logger.info(f"Looking up TXT records for {domain}...")
        answers = dns.resolver.resolve(domain, 'TXT')
        found = False
        for rdata in answers:
            txt_value = "".join(
                s.decode("utf-8", errors="ignore") if isinstance(s, bytes) else str(s)
                for s in getattr(rdata, "strings", ())
            ).strip() or rdata.to_text().strip('"').strip()
            if txt_value == token:
                found = True
                break
        
        if found:
            db.confirm_domain_verification(org_id)
            
            try:
                db.update_organization_name(org_id, domain)
                current_app.logger.info(f"Auto-renamed Org {org_id} to {domain}")
            except Exception as e:
                current_app.logger.error(f"Failed to auto-rename org verify: {e}")

            absorbed = {"moved": [], "skipped": [], "emptied_orgs": [],
                        "orgs_without_authority": []}
            try:
                absorbed = db.absorb_domain_users(
                    org_id, domain, f"user:{_actor()}",
                    administrator_roles=ROLE_CONFIG["organization_admin_roles"],
                    default_role=ROLE_CONFIG["default_role"],
                )
                if absorbed["moved"]:
                    current_app.logger.info(
                        f"Domain {domain} verified: absorbed {len(absorbed['moved'])} "
                        f"account(s) into org {org_id} as members")
            except Exception as e:
                current_app.logger.error(f"Domain absorption failed for {domain}: {e}")

            identity_configured = {}
            try:
                identity_changes = {}
                if _domain_uses_google_workspace(domain):
                    identity_changes["google_hd"] = domain
                tenant_id = _discover_ms_tenant_id(domain)
                if tenant_id:
                    identity_changes["ms_tenant_id"] = tenant_id
                if identity_changes:
                    db.set_org_identity_config(org_id, identity_changes, f"user:{_actor()}")
                    identity_configured = identity_changes
            except Exception as e:
                current_app.logger.error(
                    f"Failed to auto-configure login restriction after domain "
                    f"verification for {domain}: {e}")

            return jsonify({
                "status": "verified",
                "domain": domain,
                "identity_configured": identity_configured,
                "absorbed": absorbed["moved"],
                "orgs_without_admin": absorbed["orgs_without_authority"],
                "emptied_orgs": absorbed["emptied_orgs"],
            })
        else:
            return jsonify({
                "status": "failed", 
                "error": "Token not found in DNS TXT records."
            }), 200
            
    except dns.resolver.NXDOMAIN:
        return jsonify({"status": "failed", "error": "Domain does not exist."}), 200
    except dns.resolver.NoAnswer:
        return jsonify({
            "status": "failed",
            "error": "No TXT records found on the domain yet. DNS changes can take a few minutes to a few hours to propagate."
        }), 200
    except (dns.resolver.NoNameservers, dns.exception.Timeout):
        return jsonify({
            "status": "failed",
            "error": "DNS lookup failed or timed out. Try again in a few minutes."
        }), 200
    except Exception as e:
        current_app.logger.error(f"DNS Lookup Failed: {e}")
        return jsonify({"error": f"DNS Lookup Failed: {str(e)}"}), 500


@organizations_bp.route('/organizations/domain/verify-directory', methods=['POST'])
@require_role('admin')
def verify_domain_directory():
    from ..core import ldap_client

    data = request.json or {}
    org_id = data.get('org_id')

    if not org_id:
        return jsonify({"error": "Missing org_id"}), 400
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    org = db.get_organization(org_id)
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    domain = (org.get('domain_to_verify') or '').strip().lower()
    token = org.get('verification_token')
    if not domain or not token:
        return jsonify({"error": "No verification in progress."}), 400

    owner = db.get_organization_by_domain(domain)
    if owner and str(owner['id']) != str(org_id):
        return jsonify({
            "status": "failed",
            "error": "That domain has since been verified by another "
                     "organization on this deployment. Contact support to "
                     "reconcile the two organizations."
        }), 409

    if not Config.ldap_configured():
        return jsonify({
            "status": "failed",
            "error": "Directory verification is unavailable: this deployment "
                     "has no LDAP/AD directory configured. Use DNS TXT "
                     "verification instead."
        }), 200

    try:
        dns.resolver.resolve(domain, 'SOA')
        return jsonify({
            "status": "failed",
            "error": "This domain resolves in public DNS, so it must be "
                     "verified with a TXT record (the stronger proof). "
                     "Directory verification is only for internal "
                     "namespaces without public DNS."
        }), 200
    except dns.exception.DNSException:
        pass
    except Exception as e:
        current_app.logger.error(f"SOA precheck failed for {domain}: {e}")

    proof = ldap_client.directory_owns_domain(domain)
    if proof is None:
        return jsonify({
            "status": "failed",
            "error": "The directory could not be reached to answer. Try "
                     "again in a minute, or check the LDAP configuration."
        }), 200
    if not proof["ok"]:
        return jsonify({
            "status": "failed",
            "error": f"The configured directory does not own '{domain}'. Its "
                     f"naming contexts are: {', '.join(proof['contexts']) or '(none)'}."
        }), 200

    db.confirm_domain_verification(org_id)
    db.log_auth_event("domain_verified_by_directory",
                      f"user:{_actor()}", org_id=org_id,
                      detail={"domain": domain,
                              "directory_contexts": proof["contexts"]})

    absorbed = {"moved": [], "skipped": [], "emptied_orgs": [],
                "orgs_without_authority": []}
    try:
        absorbed = db.absorb_domain_users(
            org_id, domain, f"user:{_actor()}",
            administrator_roles=ROLE_CONFIG["organization_admin_roles"],
            default_role=ROLE_CONFIG["default_role"],
        )
    except Exception as e:
        current_app.logger.error(f"Domain absorption failed for {domain}: {e}")

    return jsonify({
        "status": "verified",
        "domain": domain,
        "method": "directory",
        "directory_contexts": proof["contexts"],
        "absorbed": absorbed["moved"],
        "orgs_without_admin": absorbed["orgs_without_authority"],
        "emptied_orgs": absorbed["emptied_orgs"],
    })


@organizations_bp.route('/organizations/<org_id>/usage', methods=['GET'])
@require_role('admin')
def get_org_usage(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        days = request.args.get('days', 30, type=int)
        from ..core.services.usage_tracking import get_price_map
        return jsonify({
            "ok": True,
            "usage": db.get_org_llm_usage(org_id, days=days),
            "prices": get_price_map(),
        })
    except Exception as e:
        current_app.logger.error(f"Error fetching org usage: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@organizations_bp.route('/organizations/usage/deployment', methods=['GET'])
@require_role('admin')
def get_deployment_usage():
    from ..config import Config
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    details = db.get_user_details(user_id) or {}
    email = (details.get('email') or user.get('email') or '').lower()
    supers = {e.lower() for e in Config.SUPER_ADMIN_EMAILS}
    if not email or email not in supers:
        return jsonify({"error": "Forbidden: not a deployment operator."}), 403
    try:
        days = request.args.get('days', 30, type=int)
        from ..core.services.usage_tracking import get_price_map
        return jsonify({
            "ok": True,
            "usage": db.get_deployment_llm_usage(days=days),
            "prices": get_price_map(),
        })
    except Exception as e:
        current_app.logger.error(f"Error fetching deployment usage: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

def _provider_keys_forbidden(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return None


@organizations_bp.route('/organizations/<org_id>/provider-keys', methods=['GET'])
@require_role('admin')
def list_provider_keys(org_id):
    forbidden = _provider_keys_forbidden(org_id)
    if forbidden:
        return forbidden
    from ..core.services.deployment_keys import deployment_key_providers
    from ..core.services.model_routing import PROVIDER_METADATA, configured_providers
    from ..config import Config
    deployment = configured_providers(Config) | deployment_key_providers()
    try:
        return jsonify({
            "ok": True,
            "keys": [
                {"provider": r["provider"], "last4": r["last4"],
                 "updated_at": utc_isoformat(r["updated_at"])}
                for r in db.list_org_provider_keys(org_id)
            ],
            "providers": [
                {"id": p, "label": PROVIDER_METADATA[p]["label"],
                 "deployment_configured": p in deployment}
                for p in sorted(PROVIDER_METADATA)
            ],
        })
    except Exception as e:
        current_app.logger.error(f"Error listing provider keys: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/provider-keys', methods=['PUT'])
@require_role('admin')
def set_provider_key(org_id):
    forbidden = _provider_keys_forbidden(org_id)
    if forbidden:
        return forbidden
    from ..core.services.model_routing import PROVIDER_METADATA
    from ..core.services.org_keys import invalidate_org_keys_cache
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
        db.set_org_provider_key(org_id, provider, key, updated_by=user_id)
        invalidate_org_keys_cache(org_id)
        db.append_compliance_log(org_id, 'provider_key_change', f"user:{user_id}",
                                 {"action": "set", "provider": provider,
                                  "last4": key[-4:]})
        return jsonify({"ok": True, "provider": provider, "last4": key[-4:]})
    except Exception as e:
        current_app.logger.error(f"Error storing provider key: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/provider-keys', methods=['DELETE'])
@require_role('admin')
def delete_provider_key(org_id):
    forbidden = _provider_keys_forbidden(org_id)
    if forbidden:
        return forbidden
    from ..core.services.org_keys import invalidate_org_keys_cache
    provider = (request.args.get('provider') or '').strip().lower()
    if not provider:
        return jsonify({"error": "Missing provider."}), 400
    user = session.get('user') or {}
    user_id = user.get('sub') or user.get('id')
    try:
        if not db.delete_org_provider_key(org_id, provider):
            return jsonify({"error": "Not found."}), 404
        invalidate_org_keys_cache(org_id)
        db.append_compliance_log(org_id, 'provider_key_change', f"user:{user_id}",
                                 {"action": "remove", "provider": provider})
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"Error removing provider key: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/scim', methods=['GET'])
@require_role('admin')
def get_scim_config(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    from ..config import Config
    try:
        cfg = scim_store.get_config(org_id)
        base = Config.WEB_BASE_URL.rstrip('/') + '/scim/v2'
        return jsonify({
            "ok": True,
            "enabled": cfg["enabled"],
            "has_token": cfg["has_token"],
            "base_url": base,
            "secure": Config.WEB_BASE_URL.startswith("https"),
            "group_roles": scim_store.list_group_role_map(org_id),
            "resource_count": len(scim_store.list_resources(org_id)),
            "roles": sorted(scim_store.VALID_ROLES),
        })
    except Exception as e:
        current_app.logger.error(f"SCIM config read failed: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/scim', methods=['PUT'])
@require_role('admin')
def set_scim_enabled(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    enabled = bool((request.json or {}).get('enabled'))
    try:
        scim_store.set_enabled(org_id, enabled)
        db.append_compliance_log(org_id, 'scim_config_changed', f"user:{_actor()}",
                                 {"action": "enabled" if enabled else "disabled"})
        return jsonify({"ok": True, "enabled": enabled})
    except Exception as e:
        current_app.logger.error(f"SCIM enable failed: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/scim/token', methods=['POST'])
@require_role('admin')
def rotate_scim_token(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    try:
        token = scim_store.rotate_token(org_id)
        db.append_compliance_log(org_id, 'scim_config_changed', f"user:{_actor()}",
                                 {"action": "token_rotated"})
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        current_app.logger.error(f"SCIM token rotate failed: {type(e).__name__}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/scim/group-roles', methods=['PUT'])
@require_role('admin')
def set_scim_group_role(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    data = request.json or {}
    group_name = (data.get('group_name') or '').strip()
    role = (data.get('role') or '').strip().lower()
    if not group_name:
        return jsonify({"error": "group_name is required."}), 400
    if role not in scim_store.VALID_ROLES:
        return jsonify({"error": "Invalid role."}), 400
    try:
        scim_store.set_group_role(org_id, group_name, role)
        db.append_compliance_log(org_id, 'scim_config_changed', f"user:{_actor()}",
                                 {"action": "group_role_set", "group": group_name, "role": role})
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"SCIM group-role set failed: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/<org_id>/scim/group-roles', methods=['DELETE'])
@require_role('admin')
def delete_scim_group_role(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    group_name = (request.args.get('group_name') or '').strip()
    if not group_name:
        return jsonify({"error": "group_name is required."}), 400
    try:
        scim_store.delete_group_role(org_id, group_name)
        db.append_compliance_log(org_id, 'scim_config_changed', f"user:{_actor()}",
                                 {"action": "group_role_removed", "group": group_name})
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"SCIM group-role delete failed: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@organizations_bp.route('/organizations/domain/cancel', methods=['POST'])
@require_role('admin')
def cancel_domain_verification():
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
def create_organization():
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    name = data.get('name')
    if not name: return jsonify({"error": "Organization Name is required"}), 400
        
    try:
        result = create_organization(name, user_id)
        
        
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
    if not user: return jsonify({"organization": None})
    
    if user.get('org_id'):
       org = db.get_organization(user['org_id'])
       return jsonify({"organization": org})
       
    return jsonify({"organization": None})

@organizations_bp.route('/organizations/<org_id>', methods=['PUT'])
@require_role('admin')
def update_organization(org_id):
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
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 25))))
        search = (request.args.get('search') or '').strip() or None

        role_order = sorted(ROLE_CONFIG["levels"], key=ROLE_CONFIG["levels"].get, reverse=True)
        members, total = db.get_organization_members(org_id, role_order, search=search, page=page, per_page=per_page)
        return jsonify({"members": members, "total": total, "page": page, "per_page": per_page})
    except Exception as e:
        current_app.logger.error(f"Error listing members: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@organizations_bp.route('/organizations/<org_id>/members/<user_id>/role', methods=['PUT'])
@require_role('admin')
def update_user_role(org_id, user_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
        
    data = request.json or {}
    new_role = data.get('role')
    
    valid_roles = ['admin', 'editor', 'auditor', 'member']
    if new_role not in valid_roles:
        return jsonify({"error": "Invalid role"}), 400
        
    try:
        prior = (db.get_user_details(user_id) or {}).get('role')
        db.update_member_role(
            user_id, org_id, new_role, actor=_actor(),
            administrator_roles=ROLE_CONFIG["organization_admin_roles"],
        )
        db.append_compliance_log(org_id, 'member_role_changed', f"user:{_actor()}", {
            "member": user_id,
            "prior_role": prior,
            "new_role": new_role,
            "admin_granted": new_role == 'admin' and prior != 'admin',
            "admin_revoked": prior == 'admin' and new_role != 'admin',
        })
        return jsonify({"status": "updated", "user_id": user_id, "role": new_role})
    except db.LastAuthorityRoleError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        current_app.logger.error(f"Error updating role: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@organizations_bp.route('/organizations/<org_id>/members/<user_id>', methods=['DELETE'])
@require_role('admin')
def remove_organization_member(org_id, user_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        prior = (db.get_user_details(user_id) or {}).get('role')
        from ..core.services import mcp_oauth
        revoked = mcp_oauth.revoke_all_mcp_tokens(user_id)
        for key in revoked:
            db.delete_oauth_token(user_id, mcp_oauth.provider_key(key), org_id=org_id)
        db.remove_member_from_org(
            user_id, org_id, actor=_actor(),
            administrator_roles=ROLE_CONFIG["organization_admin_roles"],
            default_role=ROLE_CONFIG["default_role"],
        )
        from ..persistence import sharing_store, conversation_sharing_store
        sharing_store.remove_user_from_org_sharing(user_id, org_id)
        conversation_sharing_store.remove_user_from_org_sharing(user_id, org_id)
        db.append_compliance_log(org_id, 'member_removed', f"user:{_actor()}",
                                 {"member": user_id, "prior_role": prior,
                                  "tool_tokens_revoked": revoked})
        return jsonify({"status": "removed", "user_id": user_id})
    except db.LastAuthorityRoleError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        current_app.logger.error(f"Error removing member: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


def _generate_local_password():
    import secrets
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(20))


@organizations_bp.route('/organizations/<org_id>/members/local', methods=['POST'])
@require_role('admin')
def create_local_member(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    if str(_actor() or "").startswith("demo_"):
        return jsonify({"error": "Local account creation is not available in guest demo sessions."}), 403

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip().lower()
    name = (data.get('name') or '').strip()
    role = (data.get('role') or ROLE_CONFIG["default_role"]).strip().lower()
    if role not in ('admin', 'editor', 'auditor', 'member'):
        return jsonify({"error": "Invalid role"}), 400

    raw_password = (data.get('password') or '').strip()
    if raw_password and len(raw_password) < 8:
        return jsonify({"error": "Password must be at least 8 characters long."}), 400

    password = raw_password or _generate_local_password()

    try:
        created = db.create_local_account(username, password, name=name,
                                          org_id=org_id, role=role)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not created:
        return jsonify({"error": "That username (or matching email) is already in use."}), 409

    from ..persistence import sharing_store
    groups = data.get('groups') or []
    added_groups = []
    if isinstance(groups, list):
        for g in groups:
            gid = str(g).strip()
            if not gid:
                continue
            if not re.fullmatch(r"[0-9a-f-]{36}", gid):
                named_group = sharing_store.get_group_by_name(org_id, gid)
                if named_group:
                    gid = named_group["id"]
            try:
                sharing_store.add_group_member(gid, created["user_id"], _actor())
                added_groups.append(gid)
            except Exception as ge:
                current_app.logger.warning("Failed to add user %s to group %s: %s", created["user_id"], gid, ge)

    db.append_compliance_log(org_id, 'local_account_created', f"user:{_actor()}", {
        "member": created["user_id"],
        "username": username,
        "role": role,
        "admin_granted": role == 'admin',
        "groups": added_groups,
    })
    current_app.logger.info("Local account created: %s (by %s) with %d group(s)", username, _actor(), len(added_groups))
    return jsonify({"status": "created", "user_id": created["user_id"],
                    "username": created["username"],
                    "initial_password": password,
                    "groups": added_groups}), 201


@organizations_bp.route('/organizations/<org_id>/members/<user_id>/password', methods=['POST'])
@require_role('admin')
def reset_member_password(org_id, user_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    password = _generate_local_password()
    if not db.reset_local_account_password(user_id, password):
        return jsonify({"error": "User not found or not a local (password) account."}), 404

    db.append_compliance_log(org_id, 'local_password_reset', f"user:{_actor()}",
                             {"member": user_id})
    return jsonify({"status": "reset", "user_id": user_id,
                    "initial_password": password})


def _actor():
    user = session.get('user') or {}
    return user.get('email') or user.get('id') or 'unknown'


_INVITE_CLAIM_EXPIRES_DAYS = 14


def _send_invite_claim_email(inv, org):
    from .auth import issue_invite_claim_token

    token = issue_invite_claim_token(inv['id'], inv['email'], _INVITE_CLAIM_EXPIRES_DAYS)
    claim_url = f"{Config.WEB_BASE_URL}/?invite={token}"
    org_name = (org or {}).get('name') or 'an organization'

    msg = EmailMessage()
    msg["From"] = Config.SMTP_FROM
    msg["To"] = inv['email']
    msg["Subject"] = f"You've been invited to join {org_name} on SAFi"
    msg.set_content(
        f"You've been invited to join {org_name} on SAFi as a {inv['role']}.\n\n"
        f"Set up your account: {claim_url}\n\n"
        f"This link expires in {_INVITE_CLAIM_EXPIRES_DAYS} days and can only be used once."
    )
    msg.add_alternative(
        f"<p>You've been invited to join <b>{org_name}</b> on SAFi as a "
        f"<b>{inv['role']}</b>.</p>"
        f'<p><a href="{claim_url}">Set up your account</a></p>'
        f"<p>This link expires in {_INVITE_CLAIM_EXPIRES_DAYS} days and can only be used once.</p>",
        subtype="html",
    )

    port = int(Config.SMTP_PORT)
    server = smtplib.SMTP_SSL(Config.SMTP_HOST, port, timeout=30) if port == 465 \
        else smtplib.SMTP(Config.SMTP_HOST, port, timeout=30)
    with server as s:
        if port != 465:
            s.starttls()
        if Config.SMTP_USERNAME:
            s.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        s.send_message(msg)
    return True


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
        "id": r["id"][:8] + "…",
        "created_at": utc_isoformat(r.get("created_at")),
        "last_seen_at": utc_isoformat(r.get("last_seen_at")),
        "ip": r.get("ip"), "user_agent": r.get("user_agent"),
    } for r in rows]})


@organizations_bp.route('/organizations/<org_id>/members/<user_id>/sessions', methods=['DELETE'])
@require_role('admin')
def revoke_member_sessions(org_id, user_id):
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
                r[k] = utc_isoformat(r[k])
    return jsonify({"ok": True, "invitations": rows})


@organizations_bp.route('/organizations/<org_id>/invitations', methods=['POST'])
@require_role('admin')
def create_invitation(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    try:
        inv = db.create_org_invitation(org_id, data.get('email'),
                                       data.get('role') or ROLE_CONFIG["default_role"], _actor(),
                                       allowed_roles=ROLE_CONFIG["levels"].keys())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating invitation: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

    claim_email_sent = False
    if Config.smtp_configured():
        try:
            claim_email_sent = _send_invite_claim_email(inv, db.get_organization(org_id))
        except Exception as e:
            current_app.logger.error(f"Error sending invite-claim email to {inv['email']}: {e}")
    inv['claim_email_sent'] = claim_email_sent
    return jsonify({"ok": True, "invitation": inv}), 201


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
                'require_mfa', 'ms_tenant_id', 'google_hd',
                'ldap_enabled', 'ldap_auto_provision') if k in data}
    try:
        return jsonify(db.set_org_identity_config(org_id, changes, _actor()))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating identity config: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@organizations_bp.route('/organizations/<org_id>/ldap/group-mappings', methods=['GET'])
@require_role('admin')
def list_ldap_group_mappings(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    return jsonify({"mappings": db.list_ldap_group_mappings(org_id),
                    "roles": sorted(scim_store.VALID_ROLES)})


@organizations_bp.route('/organizations/<org_id>/ldap/group-mappings', methods=['PUT'])
@require_role('admin')
def upsert_ldap_group_mapping(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    group_dn = (data.get('group_dn') or '').strip()
    role = data.get('role')
    from ..persistence import scim_store
    if not group_dn:
        return jsonify({"error": "group_dn is required"}), 400
    if role not in scim_store.VALID_ROLES:
        return jsonify({"error": f"role must be one of: {', '.join(sorted(scim_store.VALID_ROLES))}"}), 400
    try:
        return jsonify(db.upsert_ldap_group_mapping(org_id, group_dn, role, _actor()))
    except Exception as e:
        current_app.logger.error(f"Error upserting LDAP group mapping: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@organizations_bp.route('/organizations/<org_id>/ldap/group-mappings/<mapping_id>', methods=['DELETE'])
@require_role('admin')
def delete_ldap_group_mapping(org_id, mapping_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    ok = db.delete_ldap_group_mapping(org_id, mapping_id)
    return (jsonify({"ok": True}) if ok
            else (jsonify({"error": "Mapping not found"}), 404))


@organizations_bp.route('/organizations/<org_id>/charter', methods=['GET'])
def get_charter(org_id):
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
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    mission = data.get('mission', '')
    core_values = data.get('core_values', [])

    if not isinstance(core_values, list):
        return jsonify({"error": "core_values must be an array"}), 400

    try:
        user = session.get('user', {})
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


@organizations_bp.route('/organizations/<org_id>/pii-checks', methods=['GET'])
@require_role('admin')
def list_pii_checks(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({"checks": pii_validators.catalogue(security_policy.PII_CATALOGUE)})


@organizations_bp.route('/organizations/<org_id>/ai-standards', methods=['GET'])
def get_ai_standards(org_id):
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

    if structural.get('require_disclaimer') and not str(structural.get('mandatory_disclaimer_substring') or '').strip():
        return jsonify({"error": "A required disclaimer needs the exact text to check for."}), 400

    pii = structural.get('pii_validators')
    if pii is not None:
        if not isinstance(pii, list):
            return jsonify({"error": "pii_validators must be an array"}), 400
        known = set(security_policy.PII_CATALOGUE)
        unknown = [str(k) for k in pii if str(k).strip().lower() not in known]
        if unknown:
            return jsonify({"error": (
                "Unknown sensitive-data check(s): %s. Valid options are: %s."
                % (", ".join(unknown[:5]), ", ".join(security_policy.PII_CATALOGUE))
            )}), 400
        structural['pii_validators'] = pii_validators.normalize(
            pii, security_policy.PII_CATALOGUE
        )

    threshold = structural.get('alignment_score_threshold')
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return jsonify({"error": "alignment_score_threshold must be a number"}), 400
        if not 0.0 <= threshold <= 1.0:
            return jsonify({"error": "alignment_score_threshold must be between 0 and 1"}), 400
        structural['alignment_score_threshold'] = threshold

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
        db.append_compliance_log(org_id, 'ai_standards_saved', f"user:{user.get('id')}", {
            "created": not prev,
            "standards_before": len(prev.get('values') or []),
            "standards_after": len(cleaned),
            "non_negotiable": sorted(v['name'] for v in cleaned if v.get('hard_gate')),
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


_TCB_RELEASES_URL = os.environ.get(
    "SAFI_TCB_RELEASES_URL",
    "https://selfalignmentframework.com/tcb/releases.json",
)
_TCB_SIG_URL = _TCB_RELEASES_URL + ".minisig"
_TCB_PUBKEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcb_key.pub")
_TCB_CACHE_TTL_SECONDS = 300
_tcb_cache = {"at": 0.0, "releases": None}


def _parse_minisign_pubkey(text):
    try:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2 or not lines[0].startswith("untrusted comment:"):
            return None
        raw = base64.b64decode(lines[1], validate=True)
        if len(raw) != 42 or raw[:2] != b"Ed":
            return None
        return raw[2:10], raw[10:42]
    except Exception:
        return None


def _verify_minisig(payload, sig_text, keynum, public_key):
    try:
        lines = [ln.strip() for ln in sig_text.splitlines() if ln.strip()]
        if len(lines) < 2 or not lines[0].startswith("untrusted comment:"):
            return False, "signature file is malformed"
        raw = base64.b64decode(lines[1], validate=True)
        if len(raw) != 74 or raw[:2] != b"Ed":
            return False, "signature format is not supported"
        if raw[2:10] != keynum:
            return False, "signature was made with a different key"
        Ed25519PublicKey.from_public_bytes(public_key).verify(raw[10:74], payload)
        return True, None
    except InvalidSignature:
        return False, "signature does not match the published list"
    except Exception:
        return False, "signature could not be checked"


def _load_tcb_pubkey():
    try:
        with open(_TCB_PUBKEY_PATH, encoding="utf-8") as f:
            return _parse_minisign_pubkey(f.read())
    except Exception:
        return None


def _fetch_tcb_releases():
    now = time.time()
    if _tcb_cache["releases"] is not None and now - _tcb_cache["at"] < _TCB_CACHE_TTL_SECONDS:
        return True, True, _tcb_cache["releases"], None
    reachable = False
    verified = False
    releases = None
    error = None
    try:
        resp = requests.get(_TCB_RELEASES_URL, timeout=10)
        if resp.status_code != 200:
            error = f"HTTP {resp.status_code}"
        else:
            payload = resp.content
            reachable = True
            sig_resp = requests.get(_TCB_SIG_URL, timeout=10)
            if sig_resp.status_code != 200:
                error = f"signature missing: HTTP {sig_resp.status_code}"
            else:
                key = _load_tcb_pubkey()
                if key is None:
                    error = "pinned registry key is unavailable on this deployment"
                else:
                    ok, reason = _verify_minisig(
                        payload, sig_resp.content.decode("utf-8"), *key)
                    if not ok:
                        error = f"list failed to authenticate: {reason}"
                    else:
                        verified = True
                        try:
                            data = json.loads(payload.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            error = "published list is not valid JSON"
                        else:
                            parsed = []
                            for r in data.get("releases") or []:
                                fp = str(r.get("fingerprint") or "").strip().lower()
                                if re.fullmatch(r"[0-9a-f]{64}", fp):
                                    parsed.append({
                                        "tag": str(r.get("tag") or ""),
                                        "date": str(r.get("date") or ""),
                                        "fingerprint": fp,
                                    })
                            if parsed:
                                releases = parsed
                                _tcb_cache.update(at=now, releases=releases)
                            else:
                                error = "published list contains no releases"
    except requests.RequestException as e:
        error = f"unreachable: {e}"[:200]
    return reachable, verified and releases is not None, releases, error


def _detect_git_branch(start=None, max_parents=4):
    try:
        here = os.path.abspath(start or os.path.dirname(__file__))
        for _ in range(max_parents):
            head_file = os.path.join(here, ".git", "HEAD")
            if os.path.isfile(head_file):
                with open(head_file, encoding="utf-8") as f:
                    head = f.read().strip()
                if head.startswith("ref: refs/heads/"):
                    return {"branch": head.rsplit("/", 1)[-1], "revision": None}
                return {"branch": None, "revision": head[:12] or None}
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
    except Exception:
        pass
    return {"branch": None, "revision": None}


@organizations_bp.route('/organizations/<org_id>/tcb-verify', methods=['POST'])
@require_role('admin')
def tcb_verify(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403

    try:
        disk = integrity.get_status(root=integrity._ROOT)
        boot = integrity.get_status()
    except Exception as e:
        current_app.logger.error(f"tcb_verify: local check failed: {e}")
        return jsonify({
            "error": "The local integrity check could not run.",
            "branch": _detect_git_branch()["branch"],
        }), 500

    reachable, verified, releases, error = _fetch_tcb_releases()
    official = None
    if reachable and verified and disk.get("expected_fingerprint"):
        official = next(
            (r for r in releases if r["fingerprint"] == disk["expected_fingerprint"]),
            None,
        )

    if disk["state"] == "unverifiable":
        verdict = "unverifiable"
    elif not disk["intact"]:
        verdict = "modified"
    elif not reachable:
        verdict = "offline"
    elif not verified:
        verdict = "unverifiable"
    elif official:
        verdict = "authentic"
    else:
        verdict = "unreleased"

    pin = os.environ.get("SAFI_EXPECTED_FINGERPRINT", "").strip().lower()
    pin_configured = bool(pin)
    pin_matches = None
    if pin_configured and disk.get("fingerprint"):
        pin_matches = pin == disk["fingerprint"]

    git = _detect_git_branch()

    result = {
        "checked_at": utc_isoformat(datetime.now(timezone.utc)),
        "verdict": verdict,
        "release_url": _TCB_RELEASES_URL,
        "local": {
            "state": disk["state"],
            "intact": disk["intact"],
            "fingerprint": disk.get("fingerprint"),
            "manifest_fingerprint": disk.get("expected_fingerprint"),
            "boot_state": boot["state"],
            "boot_intact": boot["intact"],
            "branch": git["branch"],
            "revision": git["revision"],
            "modified_files": list(disk.get("modified") or [])[:50],
            "missing_files": list(disk.get("missing") or [])[:50],
        },
        "remote": {
            "reachable": reachable,
            "verified": verified,
            "error": error,
            "official_release": official,
        },
        "pin": {
            "configured": pin_configured,
            "matches": pin_matches,
            "configured_prefix": (pin[:16] + "…") if pin_configured else None,
        },
    }

    try:
        db.append_compliance_log(org_id, 'tcb_verify', f"user:{_actor()}", result)
    except Exception as e:
        current_app.logger.error(f"tcb_verify: compliance log write failed: {e}")

    return jsonify(result)


@organizations_bp.route('/organizations/<org_id>/tcb-verify/last', methods=['GET'])
@require_role('admin')
def last_tcb_verify(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        rows = db.list_compliance_log(org_id, limit=100)
        last = next(
            (r for r in rows
             if r.get("event_type") == "tcb_verify"
             and isinstance(r.get("detail"), dict)
             and "verdict" in r["detail"]),
            None,
        )
        if last is None:
            return jsonify({"found": False, "verdict": None, "checked_at": None})
        return jsonify({"found": True, **last["detail"]})
    except Exception as e:
        current_app.logger.error(f"tcb_verify last: {e}")
        return jsonify({"error": "An internal error occurred."}), 500
