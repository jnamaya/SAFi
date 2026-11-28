from flask import Blueprint, session, jsonify, request, url_for, redirect, current_app, abort, g
from functools import wraps
import hashlib
import secrets
import traceback
import requests
import base64
import os
import json
import uuid
from datetime import datetime, timedelta
from ..extensions import oauth
from ..timeutil import utc_isoformat
from ..persistence import database as db
from ..config import Config
from ..bootstrap import create_organization
from ..role_config import ROLE_CONFIG
from ..profile_resolver import get_profile
from authlib.integrations.base_client.errors import OAuthError
import jwt

from ..core import totp as totp_lib

auth_bp = Blueprint('auth', __name__)

_DUMMY_PASSWORD_HASH = (
    "pbkdf2:sha256:600000$hoc9W551n0cb6hOE$"
    "cd991ab88e42a094d8ca5c1e41f3d828a6aa8c986ff265746f9fa4b5d95f8861"
)


_MFA_TOKEN_TTL_SECONDS = 300

_mfa_attempts: dict = {}
_MFA_MAX_ATTEMPTS = 5
_MFA_ATTEMPT_WINDOW = 300


def _mfa_rate_limited(user_id):
    from ..persistence import rate_limit_store
    bucket = f"mfa:{user_id}"
    db_result = rate_limit_store.is_rate_limited(bucket, _MFA_MAX_ATTEMPTS, _MFA_ATTEMPT_WINDOW)
    if db_result is not None:
        return db_result
    import time as _time
    now = _time.time()
    attempts = [t for t in _mfa_attempts.get(user_id, []) if now - t < _MFA_ATTEMPT_WINDOW]
    _mfa_attempts[user_id] = attempts
    return len(attempts) >= _MFA_MAX_ATTEMPTS


def _mfa_record_attempt(user_id):
    from ..persistence import rate_limit_store
    bucket = f"mfa:{user_id}"
    if rate_limit_store.record_attempt(bucket, _MFA_ATTEMPT_WINDOW):
        return
    import time as _time
    _mfa_attempts.setdefault(user_id, []).append(_time.time())


def _mfa_clear_attempts(user_id):
    from ..persistence import rate_limit_store
    rate_limit_store.clear_attempts(f"mfa:{user_id}")
    _mfa_attempts.pop(user_id, None)


_MAX_INVITE_EXPIRES_DAYS = 30


def _signing_key(purpose: str) -> str:
    import hmac
    return hmac.new(
        str(Config.SECRET_KEY).encode("utf-8"),
        f"safi:jwt:{purpose}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _issue_mfa_token(user_id):
    payload = {
        "sub": user_id,
        "type": "mfa_pending",
        "exp": datetime.utcnow() + timedelta(seconds=_MFA_TOKEN_TTL_SECONDS),
    }
    token = jwt.encode(payload, _signing_key("mfa_pending"), algorithm="HS256")
    return token.decode("utf-8") if isinstance(token, bytes) else token


def _verify_mfa_token(token):
    try:
        payload = jwt.decode(token, _signing_key("mfa_pending"), algorithms=["HS256"])
        if payload.get("type") != "mfa_pending":
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def issue_invite_claim_token(invite_id, email, expires_days):
    capped_days = min(max(1, int(expires_days)), _MAX_INVITE_EXPIRES_DAYS)
    payload = {
        "sub": invite_id,
        "email": email,
        "type": "invite_claim",
        "exp": datetime.utcnow() + timedelta(days=capped_days),
    }
    token = jwt.encode(payload, _signing_key("invite_claim"), algorithm="HS256")
    return token.decode("utf-8") if isinstance(token, bytes) else token


def verify_invite_claim_token(token):
    try:
        payload = jwt.decode(token, _signing_key("invite_claim"), algorithms=["HS256"])
        if payload.get("type") != "invite_claim":
            return None
        invite_id, email = payload.get("sub"), payload.get("email")
        if not invite_id or not email:
            return None
        return {"invite_id": invite_id, "email": email}
    except jwt.PyJWTError:
        return None


def _establish_session(user_details, idp, extra_context=None, lifetime_hours=None):
    from ..core import identity as _identity
    user_id = user_details['id']
    org_id = user_details.get('org_id')
    cfg = db.get_org_identity_config(org_id)
    hours = lifetime_hours or cfg['session_lifetime_hours']
    ctx = {"idp": idp}
    if extra_context:
        ctx.update(extra_context)
    sid = db.create_session(
        user_id, org_id, hours,
        ip=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else None,
        auth_context=ctx,
    )
    db.log_auth_event('login', f"user:{user_id}", org_id=org_id, user_id=user_id,
                      session_id=sid, detail=ctx)
    _identity.invalidate_user_cache(user_id)
    session.clear()
    session['sid'] = sid
    session.permanent = True
    return sid


_MFA_AMR_METHODS = {"mfa", "ngcmfa", "hwk", "otp", "fido", "sms", "swk"}


def _sso_evidence(idp, claims):
    ev = {"idp": idp}
    for k in ("iss", "tid", "hd", "auth_time"):
        if claims.get(k) is not None:
            ev[k] = claims[k]
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if amr:
        ev["amr"] = amr
        ev["mfa"] = any(m in _MFA_AMR_METHODS for m in amr)
    else:
        ev["mfa"] = None
    return ev


def _org_claim_gate(user_details, idp, claims):
    org_id = user_details.get('org_id')
    if not org_id:
        return None
    cfg = db.get_org_identity_config(org_id)
    reason = None
    if idp.startswith('google'):
        want_hd = cfg.get('google_hd')
        if want_hd and (claims.get('hd') or '').lower() != want_hd:
            reason = 'hd_mismatch'
    elif idp == 'ldap':
        if not cfg.get('ldap_enabled'):
            reason = 'ldap_not_enabled'
    elif idp == 'microsoft':
        want_tid = cfg.get('ms_tenant_id')
        if want_tid and (claims.get('tid') or '').lower() != want_tid:
            reason = 'tid_mismatch'
        elif cfg.get('require_mfa'):
            amr = claims.get('amr') or []
            if isinstance(amr, str):
                amr = [amr]
            if not any(m in _MFA_AMR_METHODS for m in amr):
                reason = 'mfa_evidence_missing'
    if reason:
        db.log_auth_event('login_denied', f"user:{user_details['id']}", org_id=org_id,
                          user_id=user_details['id'],
                          detail={"reason": reason, "idp": idp,
                                  "tid": claims.get('tid'), "hd": claims.get('hd'),
                                  "amr": claims.get('amr')})
        current_app.logger.warning(
            f"Login denied for {user_details.get('email')}: {reason} (idp={idp})")
    return reason


def _ms_link_allowed(user, tid):
    org_id = (user or {}).get('org_id')
    if not org_id or not tid:
        return False
    want = ((db.get_org_identity_config(org_id) or {}).get('ms_tenant_id') or '').lower()
    return bool(want) and want == tid.lower()


def _enforce_domain_ownership(user_details, idp):
    user_id = user_details['id']
    email = (user_details.get('email') or '').strip().lower()
    if '@' not in email:
        return
    domain = email.split('@')[-1]
    current_org = user_details.get('org_id')

    try:
        owner = db.get_organization_by_domain(domain)
    except Exception as e:
        current_app.logger.error(f"Domain ownership check failed during login: {e}")
        return
    if not owner or str(owner['id']) == str(current_org):
        return

    previous_role = user_details.get('role')
    db.update_user_org_and_role(user_id, owner['id'], 'member')
    user_details['org_id'] = owner['id']
    user_details['role'] = 'member'
    db.log_auth_event('member_absorbed_by_domain', f"user:{user_id}",
                      org_id=owner['id'], user_id=user_id,
                      detail={"email": email, "domain": domain,
                              "previous_org_id": current_org,
                              "previous_role": previous_role,
                              "new_role": "member", "idp": idp,
                              "trigger": "login"})
    current_app.logger.info(
        f"User {user_id} moved into org {owner['id']} as member: {domain} is verified there")


def _resolve_single_tenant_membership(user_details, idp):
    user_id = user_details['id']
    email = (user_details.get('email') or '').strip().lower()

    inv = db.match_pending_invitation(email)
    if inv:
        res = db.accept_invitation(inv['id'], user_id, f"user:{user_id}")
        if res:
            user_details['org_id'] = res['org_id']
            user_details['role'] = res['role']
            db.log_auth_event('member_joined', f"user:{user_id}", org_id=res['org_id'],
                              user_id=user_id, detail={"join_method": "invite", "idp": idp})
            return

    org_id = Config.SINGLE_TENANT_ORG_ID
    if not org_id:
        existing = db.get_oldest_organization()
        org_id = existing['id'] if existing else None

    if org_id:
        db.update_user_org_and_role(user_id, org_id, 'member')
        user_details['org_id'] = org_id
        user_details['role'] = 'member'
        db.log_auth_event('member_joined', f"user:{user_id}", org_id=org_id,
                          user_id=user_id,
                          detail={"join_method": "single_tenant", "idp": idp})
        current_app.logger.info(f"User {user_id} joined single-tenant org {org_id}")
        return

    org_name = f"{user_details.get('name', 'My')} Organization"
    new_org = create_organization(org_name, user_id)
    user_details['org_id'] = new_org['org_id']
    user_details['role'] = 'admin'
    db.update_user_org_and_role(user_id, new_org['org_id'], 'admin')
    db.log_auth_event('org_founded', f"user:{user_id}", org_id=new_org['org_id'],
                      user_id=user_id,
                      detail={"join_method": "single_tenant_founder", "idp": idp})
    current_app.logger.info(f"User {user_id} founded single-tenant org {new_org['org_id']}")


def _resolve_membership(user_details, idp):
    if Config.TENANCY_MODE != 'multi':
        _resolve_single_tenant_membership(user_details, idp)
        return

    user_id = user_details['id']
    email = (user_details.get('email') or '').strip().lower()
    domain = email.split('@')[-1] if '@' in email else None

    org = None
    if domain:
        try:
            org = db.get_organization_by_domain(domain)
        except Exception as e:
            current_app.logger.error(f"Domain lookup failed during login: {e}")

    inv = db.match_pending_invitation(email)

    if inv and org and str(inv['org_id']) != str(org['id']):
        db.log_auth_event('invite_declined_domain_owned', f"user:{user_id}",
                          org_id=inv['org_id'], user_id=user_id,
                          detail={"reason": "domain_verified_by_another_org",
                                  "domain": domain, "domain_org_id": org['id'],
                                  "idp": idp})
        current_app.logger.warning(
            f"Ignoring invitation from org {inv['org_id']} for {email}: "
            f"{domain} is verified by org {org['id']}")
        inv = None

    if inv:
        res = db.accept_invitation(inv['id'], user_id, f"user:{user_id}")
        if res:
            user_details['org_id'] = res['org_id']
            user_details['role'] = res['role']
            db.log_auth_event('member_joined', f"user:{user_id}", org_id=res['org_id'],
                              user_id=user_id, detail={"join_method": "invite", "idp": idp})
            return

    if not org:
        return
    user_details['_domain_owned_by'] = org['id']
    policy = db.get_org_identity_config(org['id'])['join_policy']
    if policy in ('domain_auto_join', 'both'):
        user_details['org_id'] = org['id']
        user_details['role'] = 'member'
        db.update_user_org_and_role(user_id, org['id'], 'member')
        db.log_auth_event('member_joined', f"user:{user_id}", org_id=org['id'],
                          user_id=user_id,
                          detail={"join_method": "auto_join", "idp": idp, "domain": domain})
        current_app.logger.info(f"User {user_id} auto-joined org {org['name']} (Domain: {domain})")
    else:
        db.log_auth_event('login_denied', f"user:{user_id}", org_id=org['id'],
                          user_id=user_id,
                          detail={"reason": "join_policy", "idp": idp, "domain": domain})
        current_app.logger.info(f"User {user_id} not auto-joined to {org['name']}: join_policy={policy}")

def _found_org_if_unaffiliated(user_details, idp):
    if user_details.get('org_id') or user_details.get('_domain_owned_by'):
        return False

    user_id = user_details['id']
    org_name = f"{user_details.get('name', 'My')} Organization"
    try:
        new_org = create_organization(org_name, user_id)
        db.update_user_org_and_role(user_id, new_org['org_id'], 'admin')
        user_details['org_id'] = new_org['org_id']
        user_details['role'] = 'admin'
        db.log_auth_event('org_founded', f"user:{user_id}",
                          org_id=new_org['org_id'], user_id=user_id,
                          detail={"join_method": "founder", "idp": idp,
                                  "org_name": org_name})
        current_app.logger.info(
            f"Created Personal Org '{org_name}' for new user {user_id} (idp={idp})")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to auto-create org for {user_id}: {e}")
        return False


def sso_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not Config.SSO_LOGIN_ENABLED:
            abort(404)
        return fn(*args, **kwargs)
    return wrapper


@auth_bp.route('/app-config', methods=['GET'])
def app_config():
    google_configured = bool(Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET)
    microsoft_configured = bool(Config.MICROSOFT_CLIENT_ID and Config.MICROSOFT_CLIENT_SECRET)
    try:
        from safi_cli import __version__ as _cli_version
    except Exception:
        _cli_version = None
    return jsonify({
        "cloud_edition":       Config.CLOUD_EDITION,
        "demo_enabled":        Config.ENABLE_DEMO_LOGIN,
        "local_login_enabled": Config.password_login_available(),
        "voice_input_enabled": Config.VOICE_INPUT_ENABLED,
        "tts_enabled":         Config.tts_enabled(),
        "sso_login_enabled":   Config.SSO_LOGIN_ENABLED and (google_configured or microsoft_configured),
        "google_login_enabled": Config.SSO_LOGIN_ENABLED and google_configured,
        "microsoft_login_enabled": Config.SSO_LOGIN_ENABLED and microsoft_configured,
        "ldap_login_enabled":    Config.ldap_configured() and db.any_org_ldap_enabled(),
        "latest_cli_version":    _cli_version,
    })


@auth_bp.route('/login')
@sso_required
def login():
    cli_code = (request.args.get('cli_code') or '').strip()
    if cli_code:
        session['cli_sso_code'] = cli_code
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    redirect_uri = url_for('auth.callback', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)


@auth_bp.route('/callback')
@sso_required
def callback():
    try:
        current_app.logger.info("Web callback initiated.")
        token = oauth.google.authorize_access_token()
        nonce = session.pop('nonce', None)
        id_claims = oauth.google.parse_id_token(token, nonce=nonce) or {}
        user_info = oauth.google.get('userinfo').json()
        
        email = user_info.get('email')
        if email:
            existing_user = db.get_user_by_email(email)
            if existing_user:
                user_info['sub'] = existing_user['id']
                user_info['id'] = existing_user['id']

        db.upsert_user(user_info)
        user_id = user_info.get('sub') or user_info.get('id')
        user_details = db.get_user_details(user_id)

        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        if not user_details.get('org_id'):
            try:
                _resolve_membership(user_details, idp='google')
            except Exception as e:
                current_app.logger.error(f"Error resolving membership: {e}")
        else:
            try:
                _enforce_domain_ownership(user_details, idp='google')
            except Exception as e:
                current_app.logger.error(f"Error enforcing domain ownership: {e}")

        _found_org_if_unaffiliated(user_details, idp='google')

        denied = _org_claim_gate(user_details, 'google', id_claims)
        if denied:
            return redirect(f'/?error=login_denied&reason={denied}')
        cli_code = session.pop('cli_sso_code', None)
        _establish_session(user_details, idp='google',
                           extra_context=_sso_evidence('google', id_claims))

        if cli_code:
            return redirect(url_for('auth.cli_sso_authorize', code=cli_code))
        current_app.logger.info(f"Web callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
    except Exception as e:
        current_app.logger.error(f"Web callback error: {str(e)}", exc_info=True)
        return redirect('/?error=auth_failed')

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

@auth_bp.route('/auth/google/mobile', methods=['POST'])
@sso_required
def login_mobile():
    data = request.json
    token = data.get('code')
    
    if not token:
        return jsonify({"error": "Missing auth token"}), 400

    try:
        allowed_audiences = {
            aud for aud in (
                current_app.config.get('GOOGLE_CLIENT_ID'),
                *current_app.config.get('GOOGLE_MOBILE_CLIENT_IDS', ()),
            ) if aud
        }
        try:
            user_info = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                audience=None,
            )
        except ValueError as verify_error:
            current_app.logger.warning(f"Mobile login: rejected invalid Google token: {verify_error}")
            return jsonify({"error": "Invalid authentication token"}), 401

        if user_info.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
            return jsonify({"error": "Invalid token issuer"}), 401

        if user_info.get('aud') not in allowed_audiences:
            current_app.logger.warning(
                f"Mobile login: rejected token with unrecognized audience {user_info.get('aud')}"
            )
            return jsonify({"error": "Invalid authentication token"}), 401

        if 'email' not in user_info:
            return jsonify({"error": "Invalid token payload"}), 401
            
        mapped_user = {
            'sub': user_info.get('sub'),
            'id': user_info.get('sub'),
            'email': user_info.get('email'),
            'name': user_info.get('name', 'Mobile User'),
            'picture': user_info.get('picture', '')
        }
        
        existing_user = db.get_user_by_email(mapped_user['email'])
        if existing_user:
            mapped_user['id'] = existing_user['id']
            mapped_user['sub'] = existing_user['id']
            
        db.upsert_user(mapped_user)
        user_id = mapped_user['id']
        user_details = db.get_user_details(user_id)
        
        if not user_details.get('active_profile'):
            default_profile = getattr(Config, 'DEFAULT_PROFILE', 'software_engineer')
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        if not user_details.get('org_id'):
            try:
                _resolve_membership(user_details, idp='google_mobile')
            except Exception as e:
                current_app.logger.error(f"Error resolving membership (mobile): {e}")
        else:
            try:
                _enforce_domain_ownership(user_details, idp='google_mobile')
            except Exception as e:
                current_app.logger.error(f"Error enforcing domain ownership (mobile): {e}")

        _found_org_if_unaffiliated(user_details, idp='google_mobile')

        denied = _org_claim_gate(user_details, 'google_mobile', user_info)
        if denied:
            return jsonify({"error": "Login denied by your organization's policy",
                            "reason": denied}), 403
        _establish_session(user_details, idp='google_mobile',
                           extra_context=_sso_evidence('google_mobile', user_info))

        return jsonify({"ok": True, "token": "mobile_session_active"})

    except Exception as e:
        current_app.logger.error(f"Mobile login failed: {e}", exc_info=True)
        return jsonify({"error": "Authentication failed"}), 500


@auth_bp.route('/login/local', methods=['POST'])
def login_local():
    from werkzeug.security import check_password_hash

    if not Config.password_login_available():
        return jsonify({"error": "Local login is not enabled on this instance."}), 404

    data       = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or data.get('email') or '').strip()
    password   = data.get('password') or ''

    from .keys import per_minute_allowed as _pm_allowed
    if not _pm_allowed("login:ip:{}".format(request.remote_addr or "-")) or (
            identifier and not _pm_allowed("login:id:{}".format(identifier.lower()))):
        current_app.logger.warning(
            "login_throttled ip=%s", request.remote_addr)
        return jsonify({"error": "Too many attempts. Try again shortly."}), 429

    user = db.get_user_by_identifier(identifier) if (identifier and password) else None
    stored_hash = (user or {}).get('password_hash') or _DUMMY_PASSWORD_HASH
    pw_ok = check_password_hash(stored_hash, password) if (identifier and password) else False
    valid = bool(user and user.get('password_hash') and pw_ok)
    if not valid:
        current_app.logger.warning(
            "login_failed ip=%s identifier_hash=%s",
            request.remote_addr,
            hashlib.sha256(identifier.encode()).hexdigest()[:16] if identifier else "-")
        return jsonify({"error": "Invalid credentials."}), 401

    totp_state = db.get_user_totp(user['id'])
    if totp_state['enabled']:
        return jsonify({"ok": False, "mfa_required": True,
                        "mfa_token": _issue_mfa_token(user['id'])})

    cfg = db.get_org_identity_config(user.get('org_id'))
    if cfg.get('require_mfa'):
        _establish_session(user, idp='local', extra_context={
            "amr": ["pwd"], "mfa": False, "mfa_pending_enrollment": True})
        current_app.logger.info(f"Local login (MFA enrollment required): {identifier}")
        return jsonify({"ok": True, "mfa_setup_required": True})

    _establish_session(user, idp='local', extra_context={"amr": ["pwd"], "mfa": False})

    current_app.logger.info(f"Local admin login: {identifier}")
    return jsonify({"ok": True})


@auth_bp.route('/cli/login', methods=['POST'])
def cli_login():
    from werkzeug.security import check_password_hash
    from .keys import per_minute_allowed as _pm_allowed

    if not _pm_allowed("cli-login:ip:{}".format(request.remote_addr or "-")):
        return jsonify({"error": "Too many attempts. Try again shortly."}), 429

    data       = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    password   = data.get('password') or ''
    totp_code  = (data.get('totp_code') or '').strip()
    use_ldap   = bool(data.get('ldap') or '\\' in identifier or data.get('idp') == 'ldap')

    user = None
    if use_ldap and Config.ldap_configured():
        from ..core import ldap_client
        username, _dh = ldap_client.split_domain_identifier(identifier)
        result = ldap_client.authenticate(username, password)
        if not result.get('ok'):
            db.log_auth_event('login_denied', f"ldap:{username}",
                              detail={"idp": "ldap", "reason": result.get('code'), "via": "cli"})
            return jsonify({"error": result.get('message') or "Invalid credentials.",
                            "code": result.get('code')}), 401
        user = db.get_user_by_email(result.get('email'))
        if not user:
            return jsonify({"error": "No SAFi account exists for this directory identity."}), 403
    else:
        if not Config.password_login_available():
            return jsonify({"error": "Password login is not enabled on this instance."}), 404
        user = db.get_user_by_identifier(identifier) if (identifier and password) else None
        stored_hash = (user or {}).get('password_hash') or _DUMMY_PASSWORD_HASH
        pw_ok = check_password_hash(stored_hash, password) if (identifier and password) else False
        valid = bool(user and user.get('password_hash') and pw_ok)
        if not valid:
            current_app.logger.warning("cli_login_failed ip=%s", request.remote_addr)
            return jsonify({"error": "Invalid credentials."}), 401

    totp_state = db.get_user_totp(user['id'])
    if totp_state['enabled']:
        if not totp_code:
            return jsonify({"ok": False, "mfa_required": True}), 401
        if not totp_lib.verify_code(totp_state['secret'], totp_code):
            return jsonify({"error": "Invalid verification code."}), 401

    provisioned = db.get_or_create_policy_key_for_user(user, label="safi-cli")
    if not provisioned:
        return jsonify({"error": "No governance policy is available for your account; "
                                 "ask an administrator to assign one."}), 403

    db.log_auth_event('login_success', f"user:{user['id']}", org_id=user.get('org_id'),
                      user_id=user['id'], detail={"idp": "ldap" if use_ldap else "local",
                                                  "via": "cli"})
    return jsonify({"ok": True,
                    "api_key": provisioned["api_key"],
                    "policy_id": provisioned["policy_id"],
                    "user": {"id": user["id"], "name": user.get("name") or user.get("email"),
                             "org_id": user.get("org_id")}})


_CLI_SSO_TTL_SECONDS = 300


def _cli_sso_dir():
    import stat
    import tempfile
    uid = os.getuid() if hasattr(os, "getuid") else 0
    sso_dir = os.path.join(tempfile.gettempdir(), f"safi_cli_sso_{uid}")
    os.makedirs(sso_dir, mode=0o700, exist_ok=True)
    st = os.lstat(sso_dir)
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise OSError("Invalid CLI SSO directory")
    if hasattr(os, "getuid") and st.st_uid != uid:
        raise PermissionError("CLI SSO directory is not owned by the current user")
    os.chmod(sso_dir, 0o700)
    return sso_dir


def _cli_sso_file(device_code: str):
    import re
    if not device_code or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", device_code):
        return None
    return os.path.join(_cli_sso_dir(), f"{device_code}.json")


def _cli_sso_load(device_code: str):
    import time
    path = _cli_sso_file(device_code)
    if not path or not os.path.exists(path):
        return None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
        if time.time() - float(rec.get("created_at", 0)) > _CLI_SSO_TTL_SECONDS:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        return rec
    except Exception:
        return None


def _cli_sso_save(device_code: str, rec: dict) -> None:
    path = _cli_sso_file(device_code)
    if not path:
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)


@auth_bp.route('/cli/sso/start', methods=['POST'])
@sso_required
def cli_sso_start():
    import hashlib
    import time
    from .keys import per_minute_allowed as _pm_allowed

    if not _pm_allowed("cli-sso:ip:{}".format(request.remote_addr or "-")):
        return jsonify({"error": "Too many attempts. Try again shortly."}), 429

    device_code = secrets.token_urlsafe(24)
    poll_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(poll_token.encode("utf-8")).hexdigest()
    _cli_sso_save(device_code, {
        "device_code": device_code,
        "poll_token_hash": token_hash,
        "created_at": time.time(),
        "status": "pending",
    })
    return jsonify({
        "ok": True,
        "device_code": device_code,
        "poll_token": poll_token,
        "authorize_path": f"/api/cli/sso/authorize?code={device_code}",
        "expires_in": _CLI_SSO_TTL_SECONDS,
    })


@auth_bp.route('/cli/sso/authorize', methods=['GET', 'POST'])
@sso_required
def cli_sso_authorize():
    import html as _html

    code = (request.args.get("code") or request.form.get("code") or "").strip()
    rec = _cli_sso_load(code)
    if not rec:
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>SAFi CLI Login</title></head>"
            "<body style='font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e7eb;display:flex;"
            "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
            "<div style='max-width:420px;padding:28px;border:1px solid #262626;border-radius:12px;background:#141414'>"
            "<h2 style='margin-top:0;color:#f87171'>Invalid or Expired Code</h2>"
            "<p style='color:#a3a3a3'>This SAFi CLI sign-in request has expired or was already used. "
            "Please start a new login from your terminal.</p></div></body></html>",
            400,
        )

    sess_user = session.get("user")
    user_id = (sess_user.get("id") or sess_user.get("sub")) if isinstance(sess_user, dict) else None
    is_demo_user = not user_id or str(user_id).startswith("demo_")

    if is_demo_user:
        session["cli_sso_code"] = code
        esc_code = _html.escape(code, quote=True)
        google_ok = bool(Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET)
        ms_ok = bool(Config.MICROSOFT_CLIENT_ID and Config.MICROSOFT_CLIENT_SECRET)
        buttons = []
        if google_ok:
            buttons.append(
                f"<a href='/api/login?cli_code={esc_code}' style='display:block;text-align:center;"
                "padding:12px 16px;margin-top:12px;background:#16a34a;color:#fff;text-decoration:none;"
                "border-radius:8px;font-weight:600'>Continue with Google</a>"
            )
        if ms_ok:
            buttons.append(
                f"<a href='/api/login/microsoft?cli_code={esc_code}' style='display:block;text-align:center;"
                "padding:12px 16px;margin-top:12px;background:#2563eb;color:#fff;text-decoration:none;"
                "border-radius:8px;font-weight:600'>Continue with Microsoft</a>"
            )
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>SAFi CLI SSO</title></head>"
            "<body style='font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e7eb;display:flex;"
            "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
            "<div style='max-width:420px;width:100%;padding:28px;border:1px solid #262626;border-radius:12px;background:#141414'>"
            "<h2 style='margin-top:0'>Sign in to SAFi CLI</h2>"
            "<p style='color:#a3a3a3;font-size:14px'>Choose your identity provider to authorize your terminal session and provision a governed Policy API key.</p>"
            + "".join(buttons)
            + "</div></body></html>"
        )

    user = db.get_user_details(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    if request.method == "GET":
        esc_code = _html.escape(code, quote=True)
        esc_name = _html.escape(user.get("name") or user.get("email") or str(user_id))
        esc_email = _html.escape(user.get("email") or "")
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Authorize SAFi CLI</title></head>"
            "<body style='font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e7eb;display:flex;"
            "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
            "<div style='max-width:420px;width:100%;padding:28px;border:1px solid #262626;border-radius:12px;background:#141414'>"
            "<h2 style='margin-top:0'>Authorize SAFi CLI</h2>"
            f"<p style='color:#a3a3a3;font-size:14px'>Signed in as <strong style='color:#fff'>{esc_name}</strong>"
            + (f" ({esc_email})" if esc_email else "")
            + ".</p>"
            "<p style='color:#a3a3a3;font-size:14px'>Click below to provision a governed Policy API key for your terminal.</p>"
            "<form method='POST' action='/api/cli/sso/authorize'>"
            f"<input type='hidden' name='code' value='{esc_code}'>"
            "<button type='submit' style='width:100%;padding:12px 16px;margin-top:8px;background:#16a34a;"
            "color:#fff;border:none;border-radius:8px;font-weight:600;font-size:15px;cursor:pointer'>"
            "Authorize SAFi CLI</button></form></div></body></html>"
        )

    provisioned = db.get_or_create_policy_key_for_user(user, label="safi-cli")
    if not provisioned:
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>SAFi CLI Error</title></head>"
            "<body style='font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e7eb;display:flex;"
            "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
            "<div style='max-width:420px;padding:28px;border:1px solid #262626;border-radius:12px;background:#141414'>"
            "<h2 style='margin-top:0;color:#f87171'>No Policy Available</h2>"
            "<p style='color:#a3a3a3'>No governance policy is available for your account; ask an administrator to assign one.</p>"
            "</div></body></html>",
            403,
        )

    db.log_auth_event("login_success", f"user:{user['id']}", org_id=user.get("org_id"),
                      user_id=user["id"], detail={"idp": "sso", "via": "cli"})
    rec["status"] = "complete"
    rec["payload"] = {
        "ok": True,
        "api_key": provisioned["api_key"],
        "policy_id": provisioned["policy_id"],
        "user": {
            "id": user["id"],
            "name": user.get("name") or user.get("email"),
            "org_id": user.get("org_id"),
        },
    }
    _cli_sso_save(code, rec)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>SAFi CLI Authorized</title></head>"
        "<body style='font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e7eb;display:flex;"
        "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
        "<div style='max-width:420px;padding:28px;border:1px solid #16a34a;border-radius:12px;background:#141414'>"
        "<h2 style='margin-top:0;color:#4ade80'>✓ SAFi CLI Authorized</h2>"
        "<p style='color:#a3a3a3'>Your Policy API key has been sent to your terminal. You can close this browser tab.</p>"
        "</div></body></html>"
    )


@auth_bp.route('/cli/sso/poll', methods=['POST'])
@sso_required
def cli_sso_poll():
    import hashlib
    import hmac

    data = request.get_json(silent=True) or {}
    code = (data.get("device_code") or "").strip()
    poll_token = (data.get("poll_token") or "").strip()
    rec = _cli_sso_load(code)
    if not rec or not poll_token:
        return jsonify({"error": "Invalid or expired device code."}), 404

    expected_hash = rec.get("poll_token_hash") or ""
    given_hash = hashlib.sha256(poll_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected_hash, given_hash):
        return jsonify({"error": "Invalid poll token."}), 403

    if rec.get("status") != "complete":
        return jsonify({"ok": True, "status": "pending"})

    path = _cli_sso_file(code)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    payload = dict(rec.get("payload") or {})
    payload["status"] = "complete"
    return jsonify(payload)


@auth_bp.route('/login/local/mfa', methods=['POST'])
def login_local_mfa():
    if not Config.password_login_available():
        return jsonify({"error": "Local login is not enabled on this instance."}), 404

    data = request.get_json(silent=True) or {}
    user_id = _verify_mfa_token(data.get('mfa_token') or '')
    if not user_id:
        return jsonify({"error": "MFA challenge expired. Sign in again."}), 401

    if _mfa_rate_limited(user_id):
        db.log_auth_event('mfa_rate_limited', f"user:{user_id}", user_id=user_id)
        return jsonify({"error": "Too many attempts. Wait a few minutes."}), 429

    user = db.get_user_details(user_id)
    totp_state = db.get_user_totp(user_id)
    if not user or not totp_state['enabled'] or not totp_state['secret']:
        return jsonify({"error": "Invalid credentials."}), 401

    if not totp_lib.verify_code(totp_state['secret'], data.get('code') or ''):
        _mfa_record_attempt(user_id)
        db.log_auth_event('mfa_failed', f"user:{user_id}", org_id=user.get('org_id'),
                          user_id=user_id, detail={"method": "totp", "phase": "login"})
        return jsonify({"error": "Invalid code."}), 401

    _mfa_clear_attempts(user_id)
    _establish_session(user, idp='local', extra_context={"amr": ["pwd", "otp"], "mfa": True})
    current_app.logger.info(f"Local MFA login: {user.get('email')}")
    return jsonify({"ok": True})


def _ldap_jit_target_org(email):
    inv = db.match_pending_invitation(email)
    if inv:
        if db.get_org_identity_config(inv['org_id']).get('ldap_enabled'):
            return {"id": inv['org_id'], "role": inv['role'] or 'member'}
        return None
    domain = (email.split('@')[-1] or '').lower()
    if domain and '@' in email:
        org = db.get_organization_by_domain(domain)
        if org:
            cfg = db.get_org_identity_config(org['id'])
            if cfg.get('ldap_enabled') and cfg.get('ldap_auto_provision'):
                return {"id": org['id'], "role": 'member'}
    return None


def _ldap_provision_user(email, bind_result, jit_org, username):
    user_id = f"ldap_{uuid.uuid4()}"
    db.upsert_user({
        "id": user_id, "email": email,
        "name": bind_result.get('name') or username,
        "org_id": jit_org['id'], "role": jit_org['role'],
    })
    return db.get_user_by_email(email)


def _apply_ldap_role_mapping(user, user_dn):
    if not user or not user.get('org_id'):
        return
    from ..core import ldap_client
    group_dns = ldap_client.get_groups(user_dn)
    if group_dns is None:
        return
    new_role = db.resolve_ldap_role(user['org_id'], group_dns)
    if new_role != (user.get('role') or 'member'):
        db.update_user_org_and_role(user['id'], user['org_id'], new_role)
        db.log_auth_event('role_changed', f"user:{user['id']}", org_id=user['org_id'],
                          user_id=user['id'],
                          detail={"source": "ldap_group_mapping", "old": user.get('role'),
                                  "new": new_role, "groups": group_dns})
        current_app.logger.info(
            f"LDAP role mapping: {user.get('email')} {user.get('role')} -> {new_role}")


@auth_bp.route('/login/ldap', methods=['POST'])
def login_ldap():
    from ..core import ldap_client

    if not Config.ldap_configured():
        return jsonify({"error": "LDAP sign-in is not configured on this instance."}), 404

    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    password = data.get('password') or ''
    if not identifier or not password:
        return jsonify({"error": "Directory username and password are required."}), 400

    username, _domain_hint = ldap_client.split_domain_identifier(identifier)
    result = ldap_client.authenticate(username, password)
    if not result.get('ok'):
        status = 503 if result.get('code') in ('directory_unreachable', 'directory_timeout') else 401
        db.log_auth_event('login_denied', f"ldap:{username}",
                          detail={"idp": "ldap", "reason": result.get('code')})
        return jsonify({"error": result.get('message') or "Invalid credentials.",
                        "code": result.get('code')}), status

    email = result.get('email')
    if not email:
        db.log_auth_event('login_denied', f"ldap:{username}",
                          detail={"idp": "ldap", "reason": "no_email_attribute"})
        return jsonify({"error": "Your directory account has no email attribute; "
                                 "it cannot be matched to a SAFi account."}), 401

    user = db.get_user_by_email(email)
    if not user:
        jit_org = _ldap_jit_target_org(email)
        if not jit_org:
            db.log_auth_event('login_denied', f"ldap:{username}", org_id=None,
                              user_id=None, detail={"idp": "ldap", "reason": "no_safi_account",
                                                    "email": email})
            return jsonify({"error": "Directory sign-in succeeded, but no SAFi account "
                                     "exists for this email. Ask your administrator for an invite."}), 403
        user = _ldap_provision_user(email, result, jit_org, username)
        db.log_auth_event('member_joined', f"user:{user['id']}", org_id=jit_org['id'],
                          user_id=user['id'],
                          detail={"join_method": "ldap_jit", "idp": "ldap", "email": email})

    denied = _org_claim_gate(user, 'ldap', {'dn': result.get('dn')})
    if denied:
        return jsonify({"error": "Your organization has not enabled LDAP sign-in."}), 403

    _apply_ldap_role_mapping(user, result.get('dn'))

    totp_state = db.get_user_totp(user['id'])
    if totp_state['enabled']:
        current_app.logger.info(f"LDAP login (MFA pending): {email}")
        return jsonify({"ok": False, "mfa_required": True,
                        "mfa_token": _issue_mfa_token(user['id'])})

    cfg = db.get_org_identity_config(user.get('org_id'))
    if cfg.get('require_mfa'):
        _establish_session(user, idp='ldap', extra_context={
            "amr": ["pwd"], "mfa": False, "mfa_pending_enrollment": True,
            "ldap_dn": result.get('dn')})
        current_app.logger.info(f"LDAP login (MFA enrollment required): {email}")
        return jsonify({"ok": True, "mfa_setup_required": True})

    _establish_session(user, idp='ldap', extra_context={
        "amr": ["pwd"], "mfa": False, "ldap_dn": result.get('dn')})
    current_app.logger.info(f"LDAP login: {email}")
    return jsonify({"ok": True})


@auth_bp.route('/login/ldap/mfa', methods=['POST'])
def login_ldap_mfa():
    if not Config.ldap_configured():
        return jsonify({"error": "LDAP sign-in is not configured on this instance."}), 404

    data = request.get_json(silent=True) or {}
    user_id = _verify_mfa_token(data.get('mfa_token') or '')
    if not user_id:
        return jsonify({"error": "MFA challenge expired. Sign in again."}), 401

    if _mfa_rate_limited(user_id):
        db.log_auth_event('mfa_rate_limited', f"user:{user_id}", user_id=user_id)
        return jsonify({"error": "Too many attempts. Wait a few minutes."}), 429

    user = db.get_user_details(user_id)
    totp_state = db.get_user_totp(user_id)
    if not user or not totp_state['enabled'] or not totp_state['secret']:
        return jsonify({"error": "Invalid credentials."}), 401

    if not totp_lib.verify_code(totp_state['secret'], data.get('code') or ''):
        _mfa_record_attempt(user_id)
        db.log_auth_event('mfa_failed', f"user:{user_id}", org_id=user.get('org_id'),
                          user_id=user_id, detail={"method": "totp", "phase": "login",
                                                   "idp": "ldap"})
        return jsonify({"error": "Invalid code."}), 401

    _mfa_clear_attempts(user_id)
    _establish_session(user, idp='ldap', extra_context={"amr": ["pwd", "otp"], "mfa": True})
    current_app.logger.info(f"LDAP MFA login: {user.get('email')}")
    return jsonify({"ok": True})


@auth_bp.route('/invite/claim', methods=['POST'])
def claim_invitation():
    data = request.get_json(silent=True) or {}
    token = data.get('token') or ''
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    if not token or not name or len(password) < 8:
        return jsonify({"error": "A valid invite link, a name, and a password of at "
                                  "least 8 characters are required."}), 400

    claim = verify_invite_claim_token(token)
    if not claim:
        return jsonify({"error": "This invite link is invalid or has expired."}), 400

    try:
        result = db.claim_invitation_with_password(claim['invite_id'], claim['email'],
                                                    password, name=name)
    except Exception as e:
        current_app.logger.error(f"Error claiming invitation: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

    if not result:
        return jsonify({"error": "This invitation is no longer valid — it may have "
                                  "expired, been revoked, or already been claimed."}), 400

    accepted = db.accept_invitation(claim['invite_id'], result['user_id'],
                                    f"user:{result['user_id']}")
    if not accepted:
        return jsonify({"error": "This invitation is no longer valid — it may have "
                                  "expired, been revoked, or already been claimed."}), 400

    user_details = db.get_user_details(result['user_id'])
    if not user_details.get('active_profile'):
        db.update_user_profile(result['user_id'], Config.DEFAULT_PROFILE)
        user_details['active_profile'] = Config.DEFAULT_PROFILE

    _establish_session(user_details, idp='invite_claim',
                       extra_context={"amr": ["pwd"], "mfa": False})
    current_app.logger.info(f"Invite claimed: {claim['email']} joined org {accepted['org_id']}")
    return jsonify({"ok": True})


@auth_bp.route('/login/demo')
def login_demo():
    if not Config.ENABLE_DEMO_LOGIN:
        return jsonify({"error": "Demo login is not available on this instance."}), 404

    try:
        import random
        if random.random() < 0.05:
            from ..persistence import demo_store
            demo_store.cleanup_old_demo_users()
        
        existing_demo_id = request.cookies.get('safi_demo_id')
        user_to_login = None
        
        if existing_demo_id:
            existing_user = db.get_user_details(existing_demo_id)
            if existing_user:
                current_app.logger.info(f"Resuming demo session for {existing_demo_id}")
                user_to_login = existing_user
                
        if not user_to_login:
            demo_id = f"demo_{uuid.uuid4()}"
            
            org_name = f"SAFi Demo ({demo_id[-4:]})"
            org_id = db.create_organization(org_name)
            
            user_info = {
                'sub': demo_id,
                'id': demo_id,
                'email': f"{demo_id}@demo.local",
                'name': "Guest",
                'picture': "", 
                'role': 'admin',
                'org_id': org_id
            }
            db.upsert_user(user_info)

            from ..persistence import demo_store
            demo_store.record_demo_signup()

            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(demo_id, default_profile)

            if Config.DEMO_INTELLECT_MODEL:
                from ..core.services.model_routing import model_provider_configured
                if model_provider_configured(Config.DEMO_INTELLECT_MODEL, Config):
                    db.update_user_models(demo_id, Config.DEMO_INTELLECT_MODEL, None, None)
                else:
                    current_app.logger.warning(
                        f"SAFI_DEMO_INTELLECT_MODEL '{Config.DEMO_INTELLECT_MODEL}' ignored: "
                        "its provider has no API key on this install.")
            
            user_to_login = user_info
            user_to_login['active_profile'] = default_profile
            
            current_app.logger.info(f"Created new demo user {demo_id}")

        _establish_session(user_to_login, idp='demo', lifetime_hours=24,
                           extra_context={"is_demo": True})
        
        if request.args.get('client') == 'native':
            resp = jsonify({"ok": True})
        else:
            resp = redirect('/')
        resp.set_cookie('safi_demo_id', user_to_login['id'], max_age=86400, httponly=True, samesite='Lax')
        return resp
        
    except Exception as e:
        current_app.logger.error(f"Demo login failed: {str(e)}", exc_info=True)
        return redirect('/?error=demo_failed')


@auth_bp.route('/login/microsoft')
@sso_required
def login_microsoft():
    cli_code = (request.args.get('cli_code') or '').strip()
    if cli_code:
        session['cli_sso_code'] = cli_code
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    redirect_uri = url_for('auth.callback_microsoft', _external=True, _scheme='https')
    return oauth.microsoft.authorize_redirect(redirect_uri, nonce=nonce)


@auth_bp.route('/callback/microsoft')
@sso_required
def callback_microsoft():
    try:
        current_app.logger.info("Microsoft callback initiated.")
        
        token = oauth.microsoft.authorize_access_token()
        nonce = session.pop('nonce', None)
        id_claims = oauth.microsoft.parse_id_token(token, nonce=nonce) or {}
        tid = (id_claims.get('tid') or '').lower()
        oid = id_claims.get('oid')
        if not tid or not oid:
            current_app.logger.warning("Microsoft callback rejected: id_token lacks tid/oid.")
            return redirect('/?error=auth_failed')
        
        resp = oauth.microsoft.get('https://graph.microsoft.com/v1.0/me')
        user_info = resp.json()
        if user_info.get('id') != oid:
            current_app.logger.warning("Microsoft callback rejected: Graph identity does not match id_token.")
            return redirect('/?error=auth_failed')
        
        email = (user_info.get('mail') or user_info.get('userPrincipalName') or '').strip().lower()
        
        picture_data = None
        try:
            photo_resp = oauth.microsoft.get('https://graph.microsoft.com/v1.0/me/photo/$value')
            if photo_resp.ok:
                b64_img = base64.b64encode(photo_resp.content).decode('utf-8')
                content_type = photo_resp.headers.get('Content-Type', 'image/jpeg')
                picture_data = f"data:{content_type};base64,{b64_img}"
        except Exception as e:
             current_app.logger.warning(f"Error fetching Microsoft photo: {e}")
        
        mapped_user_info = {
            'sub': user_info.get('id'),
            'id': user_info.get('id'),
            'email': email,
            'name': user_info.get('displayName'),
            'picture': picture_data
        }

        existing_by_id = db.get_user_details(oid)
        existing_by_email = db.get_user_by_email(email) if email else None
        existing_user = existing_by_id
        if existing_by_email and existing_by_email['id'] != oid:
            if existing_by_id or not _ms_link_allowed(existing_by_email, tid):
                db.log_auth_event('login_denied', f"user:{existing_by_email['id']}",
                                  org_id=existing_by_email.get('org_id'),
                                  user_id=existing_by_email['id'],
                                  detail={"reason": "email_link_unverified", "idp": "microsoft", "tid": tid})
                current_app.logger.warning(
                    f"Microsoft login refused: {email} belongs to another account and tenant {tid} is not pinned to it.")
                return redirect('/?error=login_denied&reason=email_link_unverified')
            existing_user = existing_by_email

        if existing_user:
            early_denied = _org_claim_gate(existing_user, 'microsoft', id_claims)
            if early_denied:
                return redirect(f'/?error=login_denied&reason={early_denied}')
            mapped_user_info['id'] = existing_user['id']
            mapped_user_info['sub'] = existing_user['id']
            if not picture_data and existing_user.get('picture'):
                 mapped_user_info['picture'] = existing_user['picture']
        
        db.upsert_user(mapped_user_info)
        
        user_id = mapped_user_info.get('id')
        user_details = db.get_user_details(user_id)
        
        if not user_details.get('org_id'):
            try:
                _resolve_membership(user_details, idp='microsoft')
            except Exception as e:
                current_app.logger.warning(f"Membership resolution failed for Microsoft user {user_id}: {e}")
        else:
            try:
                _enforce_domain_ownership(user_details, idp='microsoft')
            except Exception as e:
                current_app.logger.warning(f"Domain ownership enforcement failed for {user_id}: {e}")

        _found_org_if_unaffiliated(user_details, idp='microsoft')

        denied = _org_claim_gate(user_details, 'microsoft', id_claims)
        if denied:
            return redirect(f'/?error=login_denied&reason={denied}')
        cli_code = session.pop('cli_sso_code', None)
        _establish_session(user_details, idp='microsoft',
                           extra_context=_sso_evidence('microsoft', id_claims))
        
        if cli_code:
            return redirect(url_for('auth.cli_sso_authorize', code=cli_code))
        current_app.logger.info(f"Microsoft callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
        
    except Exception as e:
        current_app.logger.error(f"Microsoft callback error: {str(e)}", exc_info=True)
        return redirect('/?error=auth_failed')


@auth_bp.route('/auth/status')
def auth_status():
    from ..core.rbac import get_current_org_id, get_current_role
    from ..core.services.connector_governance import connectors_for_member

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"connected": [], "connectors": []})

    org_id = get_current_org_id()

    from ..core.services.mcp_manager import is_guest, member_oauth_servers
    from ..core.services import mcp_oauth
    mcp_servers = []
    user = session.get('user') or {}
    if not is_guest(user_id or '', user.get('email') or ''):
        for server in member_oauth_servers(user_id, org_id, get_current_role()):
            row = db.get_oauth_token(user_id, mcp_oauth.provider_key(server["key"]))
            server["connected"] = bool(row and row.get("access_token"))
            mcp_servers.append(server)

    return jsonify({
        "connected": db.get_connected_providers(user_id),
        "connectors": connectors_for_member(user_id, org_id, get_current_role()),
        "mcp_servers": mcp_servers,
    })

@auth_bp.route('/auth/<provider>/disconnect', methods=['POST'])
def disconnect_provider(provider):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
        
    from ..core.services import mcp_oauth
    if provider.startswith(mcp_oauth.PROVIDER_PREFIX):
        from ..core.services.mcp_manager import file_servers
        key = provider[len(mcp_oauth.PROVIDER_PREFIX):]
        mcp_oauth.revoke_at_server(user_id, key, file_servers().get(key) or {})
    db.delete_oauth_token(user_id, provider, org_id=_connector_org())
    return jsonify({"status": "disconnected", "provider": provider})


def _connector_org():
    from ..core.rbac import get_current_org_id
    return get_current_org_id()


def _safe_profile(preferred: str, fallback: str):
    from ..profile_resolver import get_profile, AGENTS
    for candidate in (preferred, fallback, Config.DEFAULT_PROFILE):
        if not candidate:
            continue
        try:
            return get_profile(candidate), candidate
        except Exception:
            continue
    if AGENTS:
        first = sorted(AGENTS)[0]
        return get_profile(first), first
    raise KeyError("No profiles available in the active catalog.")


@auth_bp.route('/me', methods=['GET'])
def get_me():
    user = getattr(g, 'user', None)
    user_id = (user or {}).get('id') or session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        user_details = db.get_user_details(user_id)
        if not user_details:
            return jsonify({"ok": False, "error": "User details not found"}), 404
    
        user_role = user_details.get('role') or 'member'
        user_org = user_details.get('org_id')
        active_profile_name = user_details.get('active_profile')

        from ..persistence import sharing_store
        from ..role_config import ROLE_CONFIG

        if not active_profile_name or not sharing_store.can_use_built_in_or_custom_agent(
                user_id, user_role, user_org, active_profile_name, ROLE_CONFIG):
            usable = sharing_store.get_first_usable_agent(user_id, user_role, user_org, ROLE_CONFIG)
            if usable:
                active_profile_name = usable
                try:
                    db.update_user_profile(user_id, usable)
                except Exception:
                    pass
                user_details['active_profile'] = usable
            else:
                active_profile_name = None
                user_details['active_profile'] = None

        if active_profile_name:
            try:
                user_details['active_profile_details'] = get_profile(active_profile_name, org_id=user_org)
            except (KeyError, ValueError):
                usable = sharing_store.get_first_usable_agent(user_id, user_role, user_org, ROLE_CONFIG)
                if usable:
                    try:
                        db.update_user_profile(user_id, usable)
                        user_details['active_profile'] = usable
                        user_details['active_profile_details'] = get_profile(usable, org_id=user_org)
                    except Exception:
                        user_details['active_profile_details'] = None
                else:
                    user_details['active_profile'] = None
                    user_details['active_profile_details'] = None
            except Exception:
                current_app.logger.exception(
                    "Could not load active profile details for '%s'.", active_profile_name
                )
                user_details['active_profile_details'] = None
        else:
            user_details['active_profile_details'] = None
    
        user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
        
        if 'role' not in user_details: user_details['role'] = 'member'
        if 'org_id' not in user_details: user_details['org_id'] = None

        user_details['offline_enabled'] = True
        if user_details.get('org_id'):
            try:
                user_details['offline_enabled'] = db.get_org_offline_config(
                    user_details['org_id'])["offline_enabled"]
            except Exception:
                user_details['offline_enabled'] = False

        from flask import g as _g
        if getattr(_g, 'mfa_pending_enrollment', False):
            user_details['mfa_setup_required'] = True

        for _sensitive in ('password_hash', 'totp_secret', 'totp_enabled_at'):
            user_details.pop(_sensitive, None)

        user_details['org_name'] = None
        user_details['is_org_owner'] = False
        if user_details.get('org_id'):
            org = db.get_organization(user_details['org_id'])
            if org:
                user_details['org_name'] = org.get('name')
                user_details['is_org_owner'] = (org.get('owner_id') == user_id)
                if user_details['is_org_owner'] and user_details.get('role') != 'admin':
                    current_app.logger.warning(f"User {user_id} is Org Owner but has role '{user_details['role']}'. Auto-promoting to ADMIN.")
                    db.update_user_org_and_role(user_id, user_details['org_id'], 'admin')
                    user_details['role'] = 'admin'

        _ME_FIELDS = (
            'id', 'username', 'name', 'email', 'picture', 'avatar',
            'role', 'org_id', 'org_name', 'is_org_owner',
            'active_profile', 'intellect_model', 'conscience_model',
            'offline_enabled', 'mfa_setup_required',
        )
        slim = {k: user_details[k] for k in _ME_FIELDS if k in user_details}

        return jsonify({"ok": True, "user": slim})

    except Exception as e:
        current_app.logger.error(f"/api/me error: {str(e)}", exc_info=True)
        return jsonify({'ok': False, 'error': 'Server error'}), 500

@auth_bp.route('/me/profile', methods=['GET'])
def get_user_profile():
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    try:
        profile_data = json.loads(db.fetch_user_profile_memory(user_id))
        return jsonify(profile_data), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching profile for {user_id}: {e}")
        return jsonify({"error": "Could not fetch profile"}), 500

@auth_bp.route('/me/profile', methods=['POST'])
def update_user_profile():
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    try:
        new_profile_data = request.json
        if not isinstance(new_profile_data, dict):
            return jsonify({"error": "Invalid JSON payload"}), 400
        db.upsert_user_profile_memory(user_id, json.dumps(new_profile_data))
        return jsonify({"status": "success", "profile": new_profile_data}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating profile for {user_id}: {e}")
        return jsonify({"error": "Could not update profile"}), 500

@auth_bp.route('/me/profile', methods=['PUT'])
def set_user_profile():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json
    profile_name = (data.get('profile') or '').strip()
    if not profile_name:
        return jsonify({"error": "'profile' is required."}), 400
    from ..profile_resolver import AGENTS
    if profile_name not in AGENTS:
        from ..persistence import sharing_store
        agent = db.get_agent(profile_name)
        if not agent:
            return jsonify({"error": "Unknown agent."}), 404
        user = session.get('user') or {}
        if not sharing_store.can_use_agent(user_id, user.get('role'),
                                           user.get('org_id'), agent, ROLE_CONFIG):
            return jsonify({"error": "You do not have access to that agent."}), 403
    db.update_user_profile(user_id, profile_name)
    return jsonify({"status": "success", "active_profile": profile_name})

@auth_bp.route('/me/models', methods=['PUT'])
def set_user_models():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json or {}
    current = db.get_user_details(user_id) or {}
    intellect = data["intellect_model"] if "intellect_model" in data else current.get("intellect_model")
    will = data["will_model"] if "will_model" in data else current.get("will_model")
    conscience = data["conscience_model"] if "conscience_model" in data else current.get("conscience_model")
    db.update_user_models(user_id, intellect, will, conscience)
    return jsonify({"status": "success"})

@auth_bp.route('/me/delete', methods=['POST', 'DELETE'])
def delete_me():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    from ..core.services.mcp_oauth import revoke_all_mcp_tokens
    revoke_all_mcp_tokens(user_id)
    db.revoke_user_sessions(user_id, f"user:{user_id}")
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})


@auth_bp.route('/me/sessions', methods=['GET'])
def list_my_sessions():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    from flask import g
    rows = db.list_user_sessions(user_id)
    current = getattr(g, 'sid', None)
    out = [{
        "id": r["id"],
        "created_at": utc_isoformat(r.get("created_at")),
        "last_seen_at": utc_isoformat(r.get("last_seen_at")),
        "expires_at": utc_isoformat(r.get("expires_at")),
        "ip": r.get("ip"),
        "user_agent": r.get("user_agent"),
        "current": r["id"] == current,
    } for r in rows]
    return jsonify({"ok": True, "sessions": out})

@auth_bp.route('/me/sessions/<sid>', methods=['DELETE'])
def revoke_my_session(sid):
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    row = db.get_session(sid)
    if not row or row["user_id"] != user_id:
        return jsonify({"error": "Not found"}), 404
    db.revoke_session(sid, f"user:{user_id}")
    return jsonify({"ok": True})

@auth_bp.route('/me/sessions', methods=['DELETE'])
def revoke_my_other_sessions():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    from flask import g
    count = db.revoke_user_sessions(user_id, f"user:{user_id}", keep_sid=getattr(g, 'sid', None))
    return jsonify({"ok": True, "revoked": count})


def _sync_appliance_os_password(new_password: str) -> bool:
    import subprocess
    from pathlib import Path
    helper = Path("/usr/local/sbin/safi-admin-passwd")
    if not helper.exists():
        return False
    try:
        res = subprocess.run(
            ["sudo", str(helper)],
            input=new_password.encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=5
        )
        if res.returncode == 0:
            current_app.logger.info("Synchronized Linux OS password for admin")
            return True
        current_app.logger.warning(
            "Could not sync OS admin password (exit %d): %s",
            res.returncode, res.stderr.decode("utf-8", "replace").strip()
        )
        return False
    except Exception:
        current_app.logger.exception("Error calling safi-admin-passwd helper")
        return False


@auth_bp.route('/me/password', methods=['POST'])
def change_my_password():
    from werkzeug.security import check_password_hash
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Auth required"}), 401
    data = request.json or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''

    user = db.get_user_details(user_id) or {}
    if not user.get('password_hash'):
        return jsonify({"error": "This account signs in with an identity "
                                 "provider and has no password to change."}), 400
    if not check_password_hash(user['password_hash'], current_password):
        return jsonify({"error": "Current password is incorrect."}), 403
    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    if new_password == current_password:
        return jsonify({"error": "New password must differ from the current one."}), 400

    db.set_local_password(user_id, new_password)
    current_app.logger.info("Self-service password change for user %s", user_id)

    if user_id == "local_admin" or user.get("username") == "admin":
        _sync_appliance_os_password(new_password)

    return jsonify({"ok": True, "status": "password_changed"})


@auth_bp.route('/me/mfa', methods=['GET'])
def get_my_mfa():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    state = db.get_user_totp(user_id)
    user = db.get_user_details(user_id) or {}
    cfg = db.get_org_identity_config(user.get('org_id'))
    return jsonify({"ok": True, "totp_enabled": state['enabled'],
                    "org_requires_mfa": bool(cfg.get('require_mfa')),
                    "local_account": bool(user.get('password_hash'))})


@auth_bp.route('/me/mfa/totp/setup', methods=['POST'])
def setup_my_totp():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    user = db.get_user_details(user_id) or {}
    if not user.get('password_hash'):
        return jsonify({"error": "TOTP applies to local (password) accounts. "
                                 "SSO accounts get MFA from their identity provider."}), 400
    secret = totp_lib.generate_secret()
    try:
        db.set_user_totp_pending(user_id, secret)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"ok": True, "secret": secret,
                    "otpauth_uri": totp_lib.provisioning_uri(secret, user.get('email') or user_id)})


@auth_bp.route('/me/mfa/totp/verify', methods=['POST'])
def verify_my_totp():
    from flask import g
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    if _mfa_rate_limited(user_id):
        return jsonify({"error": "Too many attempts. Wait a few minutes."}), 429

    state = db.get_user_totp(user_id)
    if not state['secret']:
        return jsonify({"error": "No enrollment in progress."}), 400
    code = (request.get_json(silent=True) or {}).get('code') or ''
    if not totp_lib.verify_code(state['secret'], code):
        _mfa_record_attempt(user_id)
        db.log_auth_event('mfa_failed', f"user:{user_id}", user_id=user_id,
                          detail={"method": "totp", "phase": "enrollment"})
        return jsonify({"error": "Invalid code."}), 401

    _mfa_clear_attempts(user_id)
    user = db.get_user_details(user_id) or {}
    if not state['enabled']:
        db.enable_user_totp(user_id, f"user:{user_id}", org_id=user.get('org_id'))

    sid = getattr(g, 'sid', None) or session.get('sid')
    if sid:
        row = db.get_session(sid)
        ctx = row.get('auth_context') if row else None
        if isinstance(ctx, str):
            try: ctx = json.loads(ctx)
            except ValueError: ctx = None
        if isinstance(ctx, dict) and ctx.get('mfa_pending_enrollment'):
            ctx.pop('mfa_pending_enrollment', None)
            ctx['mfa'] = True
            ctx['amr'] = sorted(set(ctx.get('amr') or ['pwd']) | {'otp'})
            db.update_session_auth_context(sid, ctx)
    return jsonify({"ok": True, "totp_enabled": True})


@auth_bp.route('/me/mfa/totp', methods=['DELETE'])
def disable_my_totp():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    if _mfa_rate_limited(user_id):
        return jsonify({"error": "Too many attempts. Wait a few minutes."}), 429
    state = db.get_user_totp(user_id)
    if not state['enabled']:
        db.disable_user_totp(user_id, f"user:{user_id}")
        return jsonify({"ok": True, "totp_enabled": False})
    code = (request.get_json(silent=True) or {}).get('code') or ''
    if not totp_lib.verify_code(state['secret'], code):
        _mfa_record_attempt(user_id)
        db.log_auth_event('mfa_failed', f"user:{user_id}", user_id=user_id,
                          detail={"method": "totp", "phase": "disable"})
        return jsonify({"error": "Invalid code."}), 401
    _mfa_clear_attempts(user_id)
    user = db.get_user_details(user_id) or {}
    db.disable_user_totp(user_id, f"user:{user_id}", org_id=user.get('org_id'))
    return jsonify({"ok": True, "totp_enabled": False})


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    sid = session.get('sid')
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if sid:
        db.revoke_session(sid, f"user:{user_id or 'unknown'}", reason='logout')
        db.log_auth_event('logout', f"user:{user_id or 'unknown'}",
                          user_id=user_id, session_id=sid)
    session.clear()
    return jsonify({"ok": True})
    return redirect('/') if request.method == 'GET' else jsonify({"status": "success"})
