from flask import Blueprint, jsonify, request, current_app, session
import uuid
import json
import re
import smtplib
from email.message import EmailMessage
import requests
import dns.resolver
import dns.exception
from ..persistence import database as db
from ..timeutil import utc_isoformat
from ..config import Config
from ..core.rbac import require_role, check_permission, get_current_org_id
# Same check the governance compiler uses, applied at save time: what would
# raise at chat time is rejected while the admin is still looking at the form.
from ..core.faculties.synderesis import _has_usable_rubric

organizations_bp = Blueprint('organizations', __name__)


def _domain_uses_google_workspace(domain):
    """Best-effort signal that a domain's mail is hosted on Google Workspace:
    its MX records point at Google's mail servers. Google has no per-domain
    discovery endpoint the way Microsoft does, so this is the closest
    equivalent — a real DNS fact about where the domain is hosted, not an
    assumption. Returns False (never raises) on any lookup failure, which
    the caller treats as "not on Google Workspace"."""
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
    """Best-effort Microsoft tenant discovery for a just-verified domain.
    The OIDC discovery document's issuer embeds the tenant's real GUID
    (https://login.microsoftonline.com/<tenant-guid>/v2.0) — a standard,
    publicly documented, unauthenticated lookup; no credentials sent, no
    secret exposed. Returns None (never raises) on any failure, which the
    caller treats as "this domain isn't on Microsoft", not an error."""
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

    # A domain can be verified by ONE organization (backlog 78). Nothing used to
    # stop two orgs verifying the same one, and because get_organization_by_domain
    # takes the first row with no ordering, which org then "owned" the domain was
    # arbitrary. That matters: a verified domain outranks invitations and drives
    # auto-join, so an ambiguous owner sends new people to an arbitrary tenant.
    #
    # Refused here rather than resolved, because the alternative (moving people
    # or the domain between orgs) would let a later verifier take over an
    # existing organization. Reconciliation is a support conversation, not
    # something an endpoint should decide.
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

        # Re-checked at the moment of commit, not only at start (backlog 78).
        # The start check can be minutes or days old, and another org can verify
        # the same domain in between, so this is the one that actually decides.
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

            # Proving the domain claims its identities (backlog 78): existing
            # accounts on it join this org as members, and this admin decides who
            # is promoted. Never fatal to the verification itself, which already
            # succeeded and is committed; a failure here is reported and left for
            # a retry rather than rolling back a proven domain.
            absorbed = {"moved": [], "skipped": [], "emptied_orgs": [],
                        "orgs_without_admin": []}
            try:
                absorbed = db.absorb_domain_users(org_id, domain, f"user:{_actor()}")
                if absorbed["moved"]:
                    current_app.logger.info(
                        f"Domain {domain} verified: absorbed {len(absorbed['moved'])} "
                        f"account(s) into org {org_id} as members")
            except Exception as e:
                current_app.logger.error(f"Domain absorption failed for {domain}: {e}")

            # A DNS-verified domain is the strongest ownership signal this
            # system has — turn it into the thing that actually restricts
            # logins (backlog 52 follow-up). domain_verified itself gates
            # nothing on its own in single-tenant deployments; google_hd /
            # ms_tenant_id are what _org_claim_gate actually checks,
            # regardless of tenancy mode. Each is only set when there is an
            # actual signal the domain is hosted there — a domain on
            # neither (a third-party mail host) gets neither set, which is
            # correct: nothing to restrict against on a provider nobody at
            # this org will ever log in through. Never fatal to the
            # verification, which already committed.
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
                # The admin needs to see this: people they did not invite are now
                # members of their org, and any org left without an admin or
                # without members needs an operator to reconcile it.
                "absorbed": absorbed["moved"],
                "orgs_without_admin": absorbed["orgs_without_admin"],
                "emptied_orgs": absorbed["emptied_orgs"],
            })
        else:
            return jsonify({
                "status": "failed", 
                "error": "Token not found in DNS TXT records."
            }), 200 # Return 200 so frontend handles it gracefully
            
    except dns.resolver.NXDOMAIN:
        return jsonify({"status": "failed", "error": "Domain does not exist."}), 200
    except dns.resolver.NoAnswer:
        # The domain resolves but has no TXT records at all yet. This is the
        # normal state right after starting verification, not a server error.
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

@organizations_bp.route('/organizations/<org_id>/usage', methods=['GET'])
@require_role('admin')
def get_org_usage(org_id):
    """
    [GET /api/organizations/<org_id>/usage?days=30]
    Aggregated LLM token usage for the Usage & Cost tab (backlog 61).
    Raw counts plus the display-time price map; dollars are computed in the
    browser so a price change never rewrites stored history.
    """
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
    """
    [GET /api/organizations/usage/deployment?days=30]
    Whole-deployment usage grouped by org (backlog 65) — the operator's view
    of who spends the shared .env provider keys. Gated on SAFI_SUPER_ADMINS
    (deployment config), never on any org role: an org admin who is not a
    named super admin gets 403 and the Usage & Cost tab skips the section
    silently. Blank SAFI_SUPER_ADMINS = nobody, the documented safe default.
    """
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
    """Shared guard for the provider-key endpoints: admin of THIS org only."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return None


@organizations_bp.route('/organizations/<org_id>/provider-keys', methods=['GET'])
@require_role('admin')
def list_provider_keys(org_id):
    """
    [GET /api/organizations/<org_id>/provider-keys]
    Which providers this org holds its own key for — display shape only
    (provider, last 4, updated). The key itself is write-only and never
    returned by any endpoint. Also carries the provider options and whether
    the deployment has its own .env key for each.
    """
    forbidden = _provider_keys_forbidden(org_id)
    if forbidden:
        return forbidden
    from ..core.services.model_routing import PROVIDER_METADATA, configured_providers
    from ..config import Config
    deployment = configured_providers(Config)
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
    """
    [PUT /api/organizations/<org_id>/provider-keys]  {provider, key}
    Stores the org's own key for one provider, encrypted. It overlays the
    deployment .env key for this org's calls within a minute (per-worker
    cache TTL). The key is never echoed back and never logged.
    """
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
        # Evidence: the change, never the key.
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
    """
    [DELETE /api/organizations/<org_id>/provider-keys?provider=x]
    Removes the org's key; calls fall back to the deployment .env default.
    """
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
    """SCIM directory-sync status for the admin UI (backlog 68): enabled,
    whether a token exists (never the token itself), the base URL the IdP
    points at, the group->role map, and how many resources the IdP has pushed.
    """
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    from ..persistence import scim_store
    from ..config import Config
    try:
        cfg = scim_store.get_config(org_id)
        # The deployment's declared public URL, not request.url_root: it is the
        # real external base an IdP must call, with the correct scheme. SCIM
        # requires HTTPS, so surface whether this deployment provides it.
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
    """Generate a new SCIM bearer token and return it ONCE. Any previous token
    stops working immediately. Only the hash is stored."""
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
        # Read the prior role first: update_member_role journals it to
        # auth_events, but that table has no reader — no endpoint, no UI — so
        # the record exists where nobody can see it. The compliance log is what
        # records_api surfaces, and a role change is an access-control event an
        # auditor expects to find beside the config changes it enables.
        prior = (db.get_user_details(user_id) or {}).get('role')
        db.update_member_role(user_id, org_id, new_role, actor=_actor())
        db.append_compliance_log(org_id, 'member_role_changed', f"user:{_actor()}", {
            "member": user_id,
            "prior_role": prior,
            "new_role": new_role,
            # Called out on its own because it is the change that matters most:
            # admin is the role that can rewrite the Charter, the AI Standards
            # and every policy.
            "admin_granted": new_role == 'admin' and prior != 'admin',
            "admin_revoked": prior == 'admin' and new_role != 'admin',
        })
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
        prior = (db.get_user_details(user_id) or {}).get('role')
        # Off-boarding reaches the member's connected tool servers too: their
        # agents are about to be out of reach, so a token nothing can consume
        # would be pure blast radius, at SAFi and inside the gateways alike.
        # Best effort BEFORE the rows die (the token is the proof of
        # possession revocation requires); removal proceeds regardless.
        from ..core.services import mcp_oauth
        revoked = mcp_oauth.revoke_all_mcp_tokens(user_id)
        for key in revoked:
            db.delete_oauth_token(user_id, mcp_oauth.provider_key(key), org_id=org_id)
        db.remove_member_from_org(user_id, org_id, actor=_actor())
        # Sharing rows must not outlive the membership: direct grants and
        # group memberships in this org go with the member (backlog 55),
        # and so do direct conversation/folder shares (backlog 56).
        from ..persistence import sharing_store, conversation_sharing_store
        sharing_store.remove_user_from_org_sharing(user_id, org_id)
        conversation_sharing_store.remove_user_from_org_sharing(user_id, org_id)
        db.append_compliance_log(org_id, 'member_removed', f"user:{_actor()}",
                                 {"member": user_id, "prior_role": prior,
                                  "tool_tokens_revoked": revoked})
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


_INVITE_CLAIM_EXPIRES_DAYS = 14  # matches create_org_invitation's own default


def _send_invite_claim_email(inv, org):
    """Backlog 51: emails the SMTP-delivered claim link for a freshly
    created invitation. The email IS the verification — only whoever can
    read this exact inbox ever sees the token — which is why there is no
    "copy invite link" affordance anywhere in the admin UI. A copied link
    could be pasted anywhere (a Slack channel, a group chat) and would then
    prove nothing about who is actually claiming it.

    Raises on any SMTP failure; the caller treats that as
    claim_email_sent=False without failing the invite-creation request —
    the invitation itself was already created and still works if the
    invitee already has a matching Google or Microsoft account."""
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
        "id": r["id"][:8] + "…",  # opaque preview — admins revoke in bulk, never need the full sid
        "created_at": utc_isoformat(r.get("created_at")),
        "last_seen_at": utc_isoformat(r.get("last_seen_at")),
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
                                       data.get('role', 'member'), _actor())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating invitation: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

    # Claim-link email (backlog 51): only when SMTP is configured. No
    # fallback link is ever surfaced in the admin UI when it isn't — an
    # unsent link would be indistinguishable from a verified one to whoever
    # the admin might otherwise be tempted to hand it to directly.
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
        # Non-negotiable standards get named individually: each one can stop
        # every response from every agent, so "which ones were non-negotiable on
        # the day traffic stopped" has to be answerable from the log alone.
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
