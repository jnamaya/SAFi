"""
SCIM 2.0 provisioning endpoints (backlog 68), served at /scim/v2.

An identity provider (Okta, Entra, etc.) authenticates with a per-org bearer
token and pushes Users and Groups. This layer translates those into SAFi
membership by CALLING the existing member/invitation functions, so all the
governance-bearing logic keeps living where it already does:

- Provision an existing SAFi user  -> add to org / set role.
- Provision a not-yet-logged-in user -> a long-lived invitation, which the
  normal SSO login path already accepts by email (no login change needed).
- Deprovision (active=false / DELETE) -> the same off-boarding the manual
  member-remove performs: revoke MCP tool tokens, drop OAuth tokens, remove
  membership, strip sharing, log evidence; plus revoke any pending invite.
- Group membership -> role via the admin-configured group->role map.

Fully userland: no faculty, database.py, or rbac.py edits.

Deferred by design (documented in backlog 68): bulk operations, complex PATCH
filter paths (e.g. members[value eq ...]), and ETag concurrency.
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, request, jsonify, g, current_app

from ..persistence import database as db
from ..persistence import scim_store
from ..persistence import sharing_store
from ..core.services import mcp_oauth

scim_bp = Blueprint("scim", __name__)

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def _scim_error(status, detail, scim_type=None):
    body = {"schemas": [ERROR_SCHEMA], "status": str(status), "detail": detail}
    if scim_type:
        body["scimType"] = scim_type
    resp = jsonify(body)
    resp.status_code = status
    resp.mimetype = "application/scim+json"
    return resp


def _scim_json(body, status=200):
    resp = jsonify(body)
    resp.status_code = status
    resp.mimetype = "application/scim+json"
    return resp


def require_scim_token(f):
    """Enforce HTTPS, then resolve the org from the Bearer token.

    HTTPS is checked FIRST, before the token is even read: the bearer token
    authenticates the IdP, and accepting it over plain HTTP would expose it to
    anyone on the path. On a deployment that declares an https public URL
    (WEB_BASE_URL), a request that did not arrive over TLS is refused. The
    check honors the reverse proxy via ProxyFix (request.is_secure reflects
    X-Forwarded-Proto). A localhost/plain-http deployment (dev, the test
    client, plain-HTTP self-host) declares http and is left alone."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from ..config import Config
        if Config.WEB_BASE_URL.startswith("https") and not request.is_secure:
            return _scim_error(403, "SCIM requires HTTPS.")
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        org_id = scim_store.resolve_org_by_token(token) if token else None
        if not org_id:
            return _scim_error(401, "Invalid or missing bearer token.")
        g.scim_org_id = org_id
        return f(*args, **kwargs)
    return wrapper


# --- SAFi application (reconciliation) ---------------------------------------

def _actor(org_id):
    return f"scim:{org_id}"


def _apply_membership(org_id, email, role):
    """Bring one person to `role` in `org_id`. Existing SAFi user -> membership
    row; otherwise a long-lived invitation the SSO login path will accept."""
    if role not in scim_store.VALID_ROLES:
        role = "member"
    user = db.get_user_by_email(email)
    if user:
        uid = user["id"]
        try:
            if str(user.get("org_id")) != str(org_id):
                db.update_user_org_and_role(uid, org_id, role)
            else:
                db.update_member_role(uid, org_id, role, actor=_actor(org_id))
        except db.LastAdminError:
            # Never strip the final admin via a directory sync; leave as-is.
            current_app.logger.warning("SCIM role change skipped: would remove last admin (%s)", email)
        db.append_compliance_log(org_id, "scim_user_provisioned", _actor(org_id),
                                 {"email": email, "role": role, "linked": True})
    else:
        # expires far out: a SCIM-provisioned invite persists until deprovisioned.
        db.create_org_invitation(org_id, email, role, invited_by=_actor(org_id), expires_days=3650)
        db.append_compliance_log(org_id, "scim_user_provisioned", _actor(org_id),
                                 {"email": email, "role": role, "linked": False})


def _deprovision(org_id, email):
    """Off-board one person: the same sequence the manual member-remove runs,
    plus revoking any pending invitation. Best-effort and idempotent."""
    user = db.get_user_by_email(email)
    if user and str(user.get("org_id")) == str(org_id):
        uid = user["id"]
        try:
            revoked = mcp_oauth.revoke_all_mcp_tokens(uid)
            for key in revoked:
                db.delete_oauth_token(uid, mcp_oauth.provider_key(key), org_id=org_id)
        except Exception as e:
            current_app.logger.warning("SCIM deprovision token revoke failed for %s: %s", email, e)
            revoked = {}
        try:
            db.remove_member_from_org(uid, org_id, actor=_actor(org_id))
            sharing_store.remove_user_from_org_sharing(uid, org_id)
        except db.LastAdminError:
            current_app.logger.warning("SCIM deprovision skipped: would remove last admin (%s)", email)
            return
        db.append_compliance_log(org_id, "scim_user_deprovisioned", _actor(org_id),
                                 {"email": email, "tool_tokens_revoked": revoked})
    # Revoke a still-pending invitation, whether or not a user row existed.
    for inv in db.list_org_invitations(org_id, pending_only=True):
        if (inv.get("email") or "").lower() == email.lower():
            db.revoke_org_invitation(org_id, inv["id"], _actor(org_id))
    db.append_compliance_log(org_id, "scim_user_deprovisioned", _actor(org_id),
                             {"email": email, "invitation_revoked": True})


def _reconcile_resource_role(org_id, res):
    """Recompute a resource's effective role from its groups and apply it,
    unless it is inactive (deprovisioned)."""
    if not res or not res.get("active"):
        return
    role = scim_store.effective_role(org_id, res["scim_id"], res.get("base_role", "member"))
    _apply_membership(org_id, res["email"], role)


# --- SCIM representations -----------------------------------------------------

def _user_to_scim(res):
    return {
        "schemas": [USER_SCHEMA],
        "id": res["scim_id"],
        "externalId": res.get("external_id"),
        "userName": res["email"],
        "name": {"formatted": res.get("display_name") or res["email"]},
        "displayName": res.get("display_name") or res["email"],
        "emails": [{"value": res["email"], "primary": True}],
        "active": bool(res["active"]),
        "meta": {
            "resourceType": "User",
            "created": _iso(res.get("created_at")),
            "lastModified": _iso(res.get("updated_at")),
            "location": f"/scim/v2/Users/{res['scim_id']}",
        },
    }


def _group_to_scim(grp):
    return {
        "schemas": [GROUP_SCHEMA],
        "id": grp["scim_id"],
        "externalId": grp.get("external_id"),
        "displayName": grp["display_name"],
        "members": [{"value": m} for m in (grp.get("members") or [])],
        "meta": {
            "resourceType": "Group",
            "created": _iso(grp.get("created_at")),
            "lastModified": _iso(grp.get("updated_at")),
            "location": f"/scim/v2/Groups/{grp['scim_id']}",
        },
    }


def _iso(dt):
    try:
        return dt.isoformat() if dt else None
    except Exception:
        return None


# --- discovery ---------------------------------------------------------------

@scim_bp.route("/ServiceProviderConfig", methods=["GET"])
@require_scim_token
def service_provider_config():
    return _scim_json({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken",
            "name": "OAuth Bearer Token",
            "description": "Authentication via the per-organization SCIM bearer token.",
        }],
    })


@scim_bp.route("/ResourceTypes", methods=["GET"])
@require_scim_token
def resource_types():
    types = [
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
         "id": "User", "name": "User", "endpoint": "/Users", "schema": USER_SCHEMA},
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
         "id": "Group", "name": "Group", "endpoint": "/Groups", "schema": GROUP_SCHEMA},
    ]
    return _scim_json({"schemas": [LIST_SCHEMA], "totalResults": len(types),
                       "Resources": types, "startIndex": 1, "itemsPerPage": len(types)})


@scim_bp.route("/Schemas", methods=["GET"])
@require_scim_token
def schemas():
    core = [{"id": USER_SCHEMA, "name": "User"}, {"id": GROUP_SCHEMA, "name": "Group"}]
    return _scim_json({"schemas": [LIST_SCHEMA], "totalResults": len(core),
                       "Resources": core, "startIndex": 1, "itemsPerPage": len(core)})


# --- Users -------------------------------------------------------------------

def _extract_email(body):
    email = (body.get("userName") or "").strip().lower()
    if not email:
        for e in body.get("emails") or []:
            if e.get("primary") and e.get("value"):
                email = e["value"].strip().lower()
                break
        if not email and body.get("emails"):
            email = (body["emails"][0].get("value") or "").strip().lower()
    return email


def _display_name(body, email):
    name = body.get("displayName")
    if not name:
        n = body.get("name") or {}
        name = n.get("formatted") or " ".join(
            x for x in [n.get("givenName"), n.get("familyName")] if x) or None
    return name or email


@scim_bp.route("/Users", methods=["GET"])
@require_scim_token
def list_users():
    org_id = g.scim_org_id
    email_filter = None
    flt = request.args.get("filter")
    if flt:
        # Support the one filter IdPs actually send on Users: userName eq "x".
        import re
        m = re.search(r'userName\s+eq\s+"([^"]+)"', flt, re.IGNORECASE)
        if m:
            email_filter = m.group(1)
        else:
            return _scim_error(400, f"Unsupported filter: {flt}", "invalidFilter")

    resources = scim_store.list_resources(org_id, email_filter=email_filter)
    try:
        start = max(1, int(request.args.get("startIndex", 1)))
    except (TypeError, ValueError):
        start = 1
    try:
        count = int(request.args.get("count", 100))
    except (TypeError, ValueError):
        count = 100
    count = max(0, min(count, 200))
    page = resources[start - 1: start - 1 + count] if count else []
    return _scim_json({
        "schemas": [LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": start,
        "itemsPerPage": len(page),
        "Resources": [_user_to_scim(r) for r in page],
    })


@scim_bp.route("/Users/<scim_id>", methods=["GET"])
@require_scim_token
def get_user(scim_id):
    res = scim_store.get_resource(g.scim_org_id, scim_id)
    if not res:
        return _scim_error(404, "User not found.")
    return _scim_json(_user_to_scim(res))


@scim_bp.route("/Users", methods=["POST"])
@require_scim_token
def create_user():
    org_id = g.scim_org_id
    body = request.get_json(silent=True) or {}
    email = _extract_email(body)
    if not email or "@" not in email:
        return _scim_error(400, "userName (email) is required.", "invalidValue")

    existing = scim_store.get_resource_by_email(org_id, email)
    if existing:
        # SCIM convention: duplicate create is a 409.
        return _scim_error(409, "User already exists.", "uniqueness")

    active = body.get("active", True)
    res = scim_store.create_resource(
        org_id, email, body.get("externalId"), _display_name(body, email),
        bool(active), "member")
    if active:
        _reconcile_resource_role(org_id, res)
    return _scim_json(_user_to_scim(res), status=201)


@scim_bp.route("/Users/<scim_id>", methods=["PUT"])
@require_scim_token
def replace_user(scim_id):
    org_id = g.scim_org_id
    res = scim_store.get_resource(org_id, scim_id)
    if not res:
        return _scim_error(404, "User not found.")
    body = request.get_json(silent=True) or {}
    active = bool(body.get("active", True))
    was_active = bool(res["active"])
    res = scim_store.update_resource(
        org_id, scim_id, active=active,
        display_name=_display_name(body, res["email"]),
        external_id=body.get("externalId"))
    if not active and was_active:
        _deprovision(org_id, res["email"])
    elif active:
        _reconcile_resource_role(org_id, res)
    return _scim_json(_user_to_scim(res))


@scim_bp.route("/Users/<scim_id>", methods=["PATCH"])
@require_scim_token
def patch_user(scim_id):
    org_id = g.scim_org_id
    res = scim_store.get_resource(org_id, scim_id)
    if not res:
        return _scim_error(404, "User not found.")
    body = request.get_json(silent=True) or {}
    ops = body.get("Operations") or []
    was_active = bool(res["active"])
    new_active = was_active
    new_name = None
    for op in ops:
        if (op.get("op") or "").lower() not in ("replace", "add"):
            continue
        path = (op.get("path") or "").lower()
        val = op.get("value")
        if path == "active":
            new_active = _as_bool(val)
        elif path in ("displayname", "name.formatted"):
            new_name = val if isinstance(val, str) else new_name
        elif path == "" and isinstance(val, dict):
            # Pathless replace: attributes live inside the value object.
            if "active" in val:
                new_active = _as_bool(val["active"])
            if "displayName" in val:
                new_name = val["displayName"]

    res = scim_store.update_resource(org_id, scim_id, active=new_active, display_name=new_name)
    if was_active and not new_active:
        _deprovision(org_id, res["email"])
    elif new_active:
        _reconcile_resource_role(org_id, res)
    return _scim_json(_user_to_scim(res))


@scim_bp.route("/Users/<scim_id>", methods=["DELETE"])
@require_scim_token
def delete_user(scim_id):
    org_id = g.scim_org_id
    res = scim_store.get_resource(org_id, scim_id)
    if not res:
        return _scim_error(404, "User not found.")
    _deprovision(org_id, res["email"])
    scim_store.delete_resource(org_id, scim_id)
    return ("", 204)


def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


# --- Groups ------------------------------------------------------------------

@scim_bp.route("/Groups", methods=["GET"])
@require_scim_token
def list_groups():
    org_id = g.scim_org_id
    groups = scim_store.list_groups(org_id)
    return _scim_json({
        "schemas": [LIST_SCHEMA],
        "totalResults": len(groups),
        "startIndex": 1,
        "itemsPerPage": len(groups),
        "Resources": [_group_to_scim(gr) for gr in groups],
    })


@scim_bp.route("/Groups/<scim_id>", methods=["GET"])
@require_scim_token
def get_group(scim_id):
    grp = scim_store.get_group(g.scim_org_id, scim_id)
    if not grp:
        return _scim_error(404, "Group not found.")
    return _scim_json(_group_to_scim(grp))


@scim_bp.route("/Groups", methods=["POST"])
@require_scim_token
def create_group():
    org_id = g.scim_org_id
    body = request.get_json(silent=True) or {}
    name = (body.get("displayName") or "").strip()
    if not name:
        return _scim_error(400, "displayName is required.", "invalidValue")
    members = [m.get("value") for m in (body.get("members") or []) if m.get("value")]
    grp = scim_store.create_group(org_id, name, body.get("externalId"), members)
    _recompute_members(org_id, members)
    return _scim_json(_group_to_scim(grp), status=201)


@scim_bp.route("/Groups/<scim_id>", methods=["PATCH"])
@require_scim_token
def patch_group(scim_id):
    org_id = g.scim_org_id
    grp = scim_store.get_group(org_id, scim_id)
    if not grp:
        return _scim_error(404, "Group not found.")
    body = request.get_json(silent=True) or {}
    members = set(grp.get("members") or [])
    touched = set(members)
    new_name = None
    for op in body.get("Operations") or []:
        opname = (op.get("op") or "").lower()
        path = (op.get("path") or "").lower()
        val = op.get("value")
        if path == "members":
            ids = [v.get("value") for v in (val or []) if isinstance(v, dict) and v.get("value")]
            if opname in ("add",):
                members.update(ids); touched.update(ids)
            elif opname == "remove":
                # No filter path support: remove the listed members, or clear all.
                if ids:
                    members.difference_update(ids); touched.update(ids)
                else:
                    touched.update(members); members.clear()
            elif opname == "replace":
                touched.update(members); members = set(ids); touched.update(ids)
        elif path in ("displayname", "") and isinstance(val, (str, dict)):
            if isinstance(val, str):
                new_name = val
            elif isinstance(val, dict) and "displayName" in val:
                new_name = val["displayName"]

    grp = scim_store.set_group_members(org_id, scim_id, list(members), display_name=new_name)
    _recompute_members(org_id, touched)
    return _scim_json(_group_to_scim(grp))


@scim_bp.route("/Groups/<scim_id>", methods=["DELETE"])
@require_scim_token
def delete_group(scim_id):
    org_id = g.scim_org_id
    grp = scim_store.get_group(org_id, scim_id)
    if not grp:
        return _scim_error(404, "Group not found.")
    members = list(grp.get("members") or [])
    scim_store.delete_group(org_id, scim_id)
    _recompute_members(org_id, members)
    return ("", 204)


def _recompute_members(org_id, member_ids):
    """After a group change, re-apply the effective role of each affected
    resource (their group memberships may now map to a different role)."""
    for sid in set(member_ids or []):
        res = scim_store.get_resource(org_id, sid)
        if res:
            _reconcile_resource_role(org_id, res)
