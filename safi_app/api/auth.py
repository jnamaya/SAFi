"""
Defines the authentication and user management API endpoints.

This blueprint handles all user-facing authentication logic, including:
- Google/Microsoft OAuth 2.0 flow for web Login (OpenID).
- Tool-specific token acquisition (Google Drive, SharePoint).
- Session management (login, logout, /me).
- User profile and model preference management.
- Account deletion.
"""
from flask import Blueprint, session, jsonify, request, url_for, redirect, current_app
import secrets
import traceback
import requests
import base64
import os
import json
import uuid
from datetime import datetime, timedelta
from ..extensions import oauth
from ..persistence import database as db
from ..config import Config
from ..core.faculties.synderesis import get_profile, list_profiles
from authlib.integrations.base_client.errors import OAuthError
from google_auth_oauthlib.flow import Flow # For Tool Auth
import jwt

from ..core import totp as totp_lib

auth_bp = Blueprint('auth', __name__)

# =================================================================
# TOTP MFA HELPERS (enterprise identity Phase 2)
# =================================================================

_MFA_TOKEN_TTL_SECONDS = 300

# In-process attempt throttle: user_id -> [timestamps]. Good enough for a
# single-box deploy; the auth_events journal is the durable record.
_mfa_attempts: dict = {}
_MFA_MAX_ATTEMPTS = 5
_MFA_ATTEMPT_WINDOW = 300


def _mfa_rate_limited(user_id):
    import time as _time
    now = _time.time()
    attempts = [t for t in _mfa_attempts.get(user_id, []) if now - t < _MFA_ATTEMPT_WINDOW]
    _mfa_attempts[user_id] = attempts
    return len(attempts) >= _MFA_MAX_ATTEMPTS


def _mfa_record_attempt(user_id):
    import time as _time
    _mfa_attempts.setdefault(user_id, []).append(_time.time())


def _issue_mfa_token(user_id):
    """Short-lived proof that the password step succeeded; the second factor
    must be presented before any session exists."""
    payload = {
        "sub": user_id,
        "type": "mfa_pending",
        "exp": datetime.utcnow() + timedelta(seconds=_MFA_TOKEN_TTL_SECONDS),
    }
    token = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
    return token.decode("utf-8") if isinstance(token, bytes) else token


def _verify_mfa_token(token):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "mfa_pending":
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None

# =================================================================
# ENTERPRISE IDENTITY PHASE 1 HELPERS (server-side sessions)
# =================================================================

def _establish_session(user_details, idp, extra_context=None, lifetime_hours=None):
    """Create the server-side session row, journal the login, and set the slim
    {'sid'} cookie. Replaces the old fat session['user'] writes — everything
    but the sid is re-resolved per request by core/identity.resolve_session."""
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
        ip=request.remote_addr,  # ProxyFix already resolves the client IP
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


def _resolve_membership(user_details, idp):
    """Membership at login: a live invitation wins; otherwise domain auto-join
    under the org's join policy (invite_only orgs journal the denial and the
    user lands org-less — they still authenticate). Mutates user_details."""
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

    if '@' not in email:
        return
    domain = email.split('@')[-1]
    try:
        org = db.get_organization_by_domain(domain)
    except Exception as e:
        current_app.logger.error(f"Domain lookup failed during login: {e}")
        return
    if not org:
        return
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

# =================================================================
# PUBLIC APP CONFIG (non-sensitive feature flags for the frontend)
# =================================================================

@auth_bp.route('/app-config', methods=['GET'])
def app_config():
    """
    [GET /api/app-config]
    Returns non-sensitive feature flags so the frontend can adapt its UI
    without requiring the user to be logged in.
    """
    return jsonify({
        "demo_enabled":        Config.ENABLE_DEMO_LOGIN,
        "local_login_enabled": Config.ENABLE_LOCAL_LOGIN,
    })

# =================================================================
# DASHBOARD AUTHENTICATION (Token Issuance)
# =================================================================

@auth_bp.route('/auth/dashboard-token', methods=['POST'])
def get_dashboard_token():
    """
    Generates a short-lived JWT for accessing the Streamlit Dashboard.
    RBAC: Only 'admin', 'editor', 'auditor' roles allowed.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    user = db.get_user_details(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    role = user.get('role', 'member')
    if role not in ['admin', 'editor', 'auditor']:
        return jsonify({"error": "Access denied: Insufficient permissions."}), 403

    try:
        payload = {
            "sub": user_id,
            "role": role,
            "org_id": user.get('org_id'),
            "email": user.get('email'),
            "type": "dashboard_access",
        }
        
        token = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode('utf-8')
            
        return jsonify({
            "token": token,
            "url": Config.DASHBOARD_URL
        })
    except Exception as e:
        current_app.logger.error(f"Token generation failed: {e}")
        return jsonify({"error": "Internal error generating token"}), 500

# =================================================================
# MAIN APP AUTHENTICATION (OpenID Connect for Login)
# =================================================================

@auth_bp.route('/login')
def login():
    """
    [GET /api/login]
    Initiates the Google OAuth 2.0 login flow for web clients (User Identity).
    """
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    # Force HTTPS scheme
    redirect_uri = url_for('auth.callback', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)


@auth_bp.route('/callback')
def callback():
    """
    [GET /api/callback]
    Handles the redirect callback from Google Login.
    """
    try:
        current_app.logger.info("Web callback initiated.")
        # Authlib handles redirect_uri from session automatically, 
        # provided the login route set it correctly (with https).
        token = oauth.google.authorize_access_token() 
        nonce = session.pop('nonce', None)
        oauth.google.parse_id_token(token, nonce=nonce)
        user_info = oauth.google.get('userinfo').json()
        
        # --- Account Linking ---
        email = user_info.get('email')
        if email:
            existing_user = db.get_user_by_email(email)
            if existing_user:
                user_info['sub'] = existing_user['id']
                user_info['id'] = existing_user['id']
        # -----------------------

        db.upsert_user(user_info)
        user_id = user_info.get('sub') or user_info.get('id')
        user_details = db.get_user_details(user_id)

        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        if not user_details.get('org_id'):
            # Membership: invitation first, then domain auto-join under the
            # org's join policy (enterprise identity Phase 1).
            try:
                _resolve_membership(user_details, idp='google')
            except Exception as e:
                current_app.logger.error(f"Error resolving membership: {e}")

        if not user_details.get('org_id'):
            # NEW: "Founder Flow" - Auto-create Personal Organization
            org_name = f"{user_details.get('name', 'My')} Organization"
            try:
                new_org = db.create_organization_atomic(org_name, user_id)
                user_details['org_id'] = new_org['org_id']
                user_details['role'] = 'admin'
                
                # CRITICAL FIX: Persist the role promotion to DB!
                db.update_user_org_and_role(user_id, new_org['org_id'], 'admin')
                
                current_app.logger.info(f"Created Personal Org '{org_name}' for new user {user_id}")
            except Exception as e:
                current_app.logger.error(f"Failed to auto-create org: {e}")

        _establish_session(user_details, idp='google')

        current_app.logger.info(f"Web callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
    except Exception as e:
        current_app.logger.error(f"Web callback error: {str(e)}", exc_info=True)
        return redirect('/?error=auth_failed')

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

@auth_bp.route('/auth/google/mobile', methods=['POST'])
def login_mobile():
    """
    [POST /api/auth/google/mobile]
    Handles Google Sign-In from the native Capacitor app.
    """
    data = request.json
    token = data.get('code')
    
    if not token:
        return jsonify({"error": "Missing auth token"}), 400

    try:
        # SECURITY: Verify the Google ID token's signature, issuer and expiry
        # against Google's public certs. Never trust an unverified JWT — decoding
        # with verify_signature=False let any client forge a login as any user.
        #
        # The native (Capacitor) app authenticates with its OWN Google OAuth
        # client, so its token's audience differs from the web GOOGLE_CLIENT_ID.
        # We therefore verify the signature without a fixed audience, then
        # explicitly enforce that the audience is one of OUR registered client
        # ids (web + mobile). This keeps audience validation strict while
        # supporting both clients.
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
                audience=None,  # audience enforced manually against allow-list below
            )
        except ValueError as verify_error:
            current_app.logger.warning(f"Mobile login: rejected invalid Google token: {verify_error}")
            return jsonify({"error": "Invalid authentication token"}), 401

        # verify_oauth2_token already enforces iss ∈ {accounts.google.com,
        # https://accounts.google.com}; double-check defensively.
        if user_info.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
            return jsonify({"error": "Invalid token issuer"}), 401

        # Enforce audience against our own registered client ids.
        if user_info.get('aud') not in allowed_audiences:
            current_app.logger.warning(
                f"Mobile login: rejected token with unrecognized audience {user_info.get('aud')}"
            )
            return jsonify({"error": "Invalid authentication token"}), 401

        if 'email' not in user_info:
            return jsonify({"error": "Invalid token payload"}), 401
            
        # 1. Map the user info
        mapped_user = {
            'sub': user_info.get('sub'),
            'id': user_info.get('sub'),
            'email': user_info.get('email'),
            'name': user_info.get('name', 'Mobile User'),
            'picture': user_info.get('picture', '')
        }
        
        # 2. Check for existing users to link accounts
        existing_user = db.get_user_by_email(mapped_user['email'])
        if existing_user:
            mapped_user['id'] = existing_user['id']
            mapped_user['sub'] = existing_user['id']
            
        # 3. Save to database
        db.upsert_user(mapped_user)
        user_id = mapped_user['id']
        user_details = db.get_user_details(user_id)
        
        # 4. Set Default Profile
        if not user_details.get('active_profile'):
            default_profile = getattr(Config, 'DEFAULT_PROFILE', 'fiduciary')
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        # 5. Membership + server-side session (enterprise identity Phase 1)
        if not user_details.get('org_id'):
            try:
                _resolve_membership(user_details, idp='google_mobile')
            except Exception as e:
                current_app.logger.error(f"Error resolving membership (mobile): {e}")
        _establish_session(user_details, idp='google_mobile')

        # Return a status token so the frontend knows it succeeded
        return jsonify({"ok": True, "token": "mobile_session_active"})

    except Exception as e:
        current_app.logger.error(f"Mobile login failed: {e}", exc_info=True)
        return jsonify({"error": "Authentication failed"}), 500

# =================================================================
# LOCAL LOGIN (Persistent Admin, No OAuth Required)
# =================================================================

@auth_bp.route('/login/local', methods=['POST'])
def login_local():
    """
    [POST /api/login/local]
    Authenticates against the persistent local admin account configured
    via SAFI_LOCAL_ADMIN_EMAIL / SAFI_LOCAL_ADMIN_PASSWORD.
    Only available when SAFI_ENABLE_LOCAL_LOGIN is true (both vars set).
    """
    from werkzeug.security import check_password_hash

    if not Config.ENABLE_LOCAL_LOGIN:
        return jsonify({"error": "Local login is not enabled on this instance."}), 404

    data     = request.get_json(silent=True) or {}
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = db.get_user_by_email(email)
    if not user or not user.get('password_hash'):
        return jsonify({"error": "Invalid credentials."}), 401

    if not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid credentials."}), 401

    # --- TOTP MFA (enterprise identity Phase 2) ---
    totp_state = db.get_user_totp(user['id'])
    if totp_state['enabled']:
        # Password verified but no session yet: hand back a short-lived
        # mfa_pending token; the session is only created by /login/local/mfa.
        return jsonify({"ok": False, "mfa_required": True,
                        "mfa_token": _issue_mfa_token(user['id'])})

    cfg = db.get_org_identity_config(user.get('org_id'))
    if cfg.get('require_mfa'):
        # Org mandates MFA and this account has none: grant a session that
        # can ONLY reach /me + MFA enrollment + logout (enforced centrally in
        # core/identity.resolve_session), so enrollment is possible but
        # nothing else is.
        _establish_session(user, idp='local', extra_context={
            "amr": ["pwd"], "mfa": False, "mfa_pending_enrollment": True})
        current_app.logger.info(f"Local login (MFA enrollment required): {email}")
        return jsonify({"ok": True, "mfa_setup_required": True})

    _establish_session(user, idp='local', extra_context={"amr": ["pwd"], "mfa": False})

    current_app.logger.info(f"Local admin login: {email}")
    return jsonify({"ok": True})


@auth_bp.route('/login/local/mfa', methods=['POST'])
def login_local_mfa():
    """
    [POST /api/login/local/mfa]
    Second step of local login for TOTP-enrolled accounts: exchanges the
    mfa_pending token + a live code for a real session.
    """
    if not Config.ENABLE_LOCAL_LOGIN:
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

    _mfa_attempts.pop(user_id, None)
    _establish_session(user, idp='local', extra_context={"amr": ["pwd", "otp"], "mfa": True})
    current_app.logger.info(f"Local MFA login: {user.get('email')}")
    return jsonify({"ok": True})

# =================================================================
# DEMO LOGIN (Auditor Role, Disposable)
# =================================================================

@auth_bp.route('/login/demo')
def login_demo():
    """
    [GET /api/login/demo]
    Creates 'Auditor' account for demo purposes.
    - RESUMABLE: Checks for 'safi_demo_id' cookie to reuse existing session.
    - CLEANUP: Triggers cleanup of old accounts.
    - DISABLED: Returns 404 if SAFI_ENABLE_DEMO is false.
    """
    if not Config.ENABLE_DEMO_LOGIN:
        return jsonify({"error": "Demo login is not available on this instance."}), 404

    try:
        # 1. Lazy Cleanup (Probabilistic: 5% chance)
        # Prevents "thundering herd" where every login triggers a DB-heavy cleanup
        import random
        if random.random() < 0.05:
            db.cleanup_old_demo_users()
        
        # 2. Check for Existing Demo Session (Resumable)
        existing_demo_id = request.cookies.get('safi_demo_id')
        user_to_login = None
        
        if existing_demo_id:
            # Verify if this user still exists in DB
            existing_user = db.get_user_details(existing_demo_id)
            if existing_user:
                current_app.logger.info(f"Resuming demo session for {existing_demo_id}")
                user_to_login = existing_user
                
        # 3. Create New User if needed
        if not user_to_login:
            demo_id = f"demo_{uuid.uuid4()}"
            
            # Create Private Sandbox Organization
            # We use the last 4 chars of ID to make it readable but unique
            org_name = f"Contoso ({demo_id[-4:]})"
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
            
            # Initialize Profile
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(demo_id, default_profile)
            
            # Prepare for session
            user_to_login = user_info
            user_to_login['active_profile'] = default_profile
            
            current_app.logger.info(f"Created new demo user {demo_id}")

        # 4. Create Session — fixed 24h absolute, matching the sandbox purge.
        _establish_session(user_to_login, idp='demo', lifetime_hours=24,
                           extra_context={"is_demo": True})
        
        # 5. Return Response with Cookie
        resp = redirect('/')
        # Set cookie for 24 hours (86400 seconds)
        resp.set_cookie('safi_demo_id', user_to_login['id'], max_age=86400, httponly=True, samesite='Lax')
        return resp
        
    except Exception as e:
        current_app.logger.error(f"Demo login failed: {str(e)}", exc_info=True)
        return redirect('/?error=demo_failed')


# =================================================================
# MICROSOFT LOGIN (App Login / Linking via "Sign in with Microsoft")
# =================================================================

@auth_bp.route('/login/microsoft')
def login_microsoft():
    """
    [GET /api/login/microsoft]
    Initiates the Microsoft OAuth 2.0 login flow using Authlib.
    This supports the "Sign in with Microsoft" button.
    Currently used primarily for linking accounts or identifying user.
    """
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    # FIX: Explicitly force scheme='https' to prevent AADSTS50011
    redirect_uri = url_for('auth.callback_microsoft', _external=True, _scheme='https')
    return oauth.microsoft.authorize_redirect(redirect_uri, nonce=nonce)


@auth_bp.route('/callback/microsoft')
def callback_microsoft():
    """
    [GET /api/callback/microsoft]
    Handles the redirect callback from Microsoft.
    """
    try:
        current_app.logger.info("Microsoft callback initiated.")
        
        # Authlib uses the saved redirect_uri from session automatically.
        token = oauth.microsoft.authorize_access_token()
        
        resp = oauth.microsoft.get('https://graph.microsoft.com/v1.0/me')
        user_info = resp.json()
        
        email = user_info.get('mail') or user_info.get('userPrincipalName')
        
        # --- Fetch Profile Picture ---
        picture_data = None
        try:
            photo_resp = oauth.microsoft.get('https://graph.microsoft.com/v1.0/me/photo/$value')
            if photo_resp.ok:
                b64_img = base64.b64encode(photo_resp.content).decode('utf-8')
                content_type = photo_resp.headers.get('Content-Type', 'image/jpeg')
                # This Base64 string is huge (kb/mb). We save it to DB but NOT session.
                picture_data = f"data:{content_type};base64,{b64_img}"
        except Exception as e:
             current_app.logger.warning(f"Error fetching Microsoft photo: {e}")
        # -----------------------------
        
        mapped_user_info = {
            'sub': user_info.get('id'),
            'id': user_info.get('id'),
            'email': email,
            'name': user_info.get('displayName'),
            'picture': picture_data
        }

        existing_user = db.get_user_by_email(email)
        if existing_user:
            mapped_user_info['id'] = existing_user['id']
            mapped_user_info['sub'] = existing_user['id']
            if not picture_data and existing_user.get('picture'):
                 mapped_user_info['picture'] = existing_user['picture']
        
        db.upsert_user(mapped_user_info)
        
        user_id = mapped_user_info.get('id')
        user_details = db.get_user_details(user_id)
        
        # Membership + server-side session (enterprise identity Phase 1)
        if not user_details.get('org_id'):
            try:
                _resolve_membership(user_details, idp='microsoft')
            except Exception as e:
                current_app.logger.warning(f"Membership resolution failed for Microsoft user {user_id}: {e}")

        _establish_session(user_details, idp='microsoft')
        
        # --- Microsoft Token Storage for Tools (Bonus) ---
        # Since we have the token here, we can piggyback and save it for OneDrive use!
        # Scope might be limited to 'User.Read' depending on Init config, 
        # but if we add 'Files.ReadWrite.All' to init, this works double-duty.
        # For now, we just log in. The 'Connect' flow below adds specific scopes.
        
        current_app.logger.info(f"Microsoft callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
        
    except Exception as e:
        current_app.logger.error(f"Microsoft callback error: {str(e)}", exc_info=True)
        return redirect('/?error=auth_failed')


# =================================================================
# TOOL AUTHENTICATION (Google Drive & SharePoint via Manual Flow)
# =================================================================

@auth_bp.route('/auth/status')
def auth_status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"connected": []})
    
    connected = db.get_connected_providers(user_id)
    return jsonify({"connected": connected})

@auth_bp.route('/auth/<provider>/disconnect', methods=['POST'])
def disconnect_provider(provider):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
        
    db.delete_oauth_token(user_id, provider)
    return jsonify({"status": "disconnected", "provider": provider})

# --- GOOGLE DRIVE TOOL ---
@auth_bp.route('/auth/google/login')
def google_tool_login():
    try:
        user_id = session.get('user_id')
        # Allow linking even if not logged in? No, must be logged in.
        if not user_id:
            return jsonify({"error": "Not logged in"}), 401

        # Define scopes for Drive
        scopes = [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ]

        client_config = {
            "web": {
                "client_id": current_app.config['GOOGLE_CLIENT_ID'],
                "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=scopes
        )
        # Unique callback for Drive tool
        flow.redirect_uri = url_for('auth.google_tool_callback', _external=True, _scheme='https')
        current_app.logger.info(f"Google Drive Redirect URI: {flow.redirect_uri}")
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Force consent to get refresh token
        )
        
        session['google_tool_state'] = state
        return redirect(authorization_url)
    except Exception as e:
        current_app.logger.error(f"Google Drive Login Start Logic Failed: {e}")
        return jsonify({"error": "Authentication failed. Please try again."}), 500

@auth_bp.route('/auth/google/callback')
def google_tool_callback():
    current_app.logger.info("Entering Google Drive Callback")
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/chat?error=auth_session_expired')

    state = session.get('google_tool_state')
    
    # Bypass library's strict HTTPS check if behind a proxy terminating SSL
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    # Allow the provider to return different scopes than requested (e.g. adding openid/profile)
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

    client_config = {
        "web": {
            "client_id": current_app.config['GOOGLE_CLIENT_ID'],
            "client_secret": current_app.config['GOOGLE_CLIENT_SECRET'],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=[],
        state=state
    )
    # Must match init
    flow.redirect_uri = url_for('auth.google_tool_callback', _external=True, _scheme='https')

    try:
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        
        db.upsert_oauth_token(
            user_id, 
            'google', 
            creds.token, 
            creds.refresh_token, 
            creds.expiry, # datetime object
            " ".join(creds.scopes) if creds.scopes else ""
        )
        
        return redirect('/?status=google_connected')
    except Exception as e:
        current_app.logger.error(f"Google Tool Auth Error: {e}", exc_info=True)
        # Redirect to root to avoid 404s on /chat if SPA routing is flaky
        return redirect(f'/?error=google_auth_failed&details={str(e)}')

# --- MICROSOFT SHAREPOINT TOOL ---
@auth_bp.route('/auth/microsoft/login')
def microsoft_tool_login():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Not logged in"}), 401
        
        # Minimal scopes for SharePoint/OneDrive
        scopes = "Files.ReadWrite.All Sites.Read.All offline_access"
        
        client_id = current_app.config['MICROSOFT_CLIENT_ID']
        if not client_id:
            current_app.logger.error("Microsoft Client ID not set")
            return jsonify({"error": "MS Config Missing"}), 500

        redirect_uri = url_for('auth.microsoft_tool_callback', _external=True, _scheme='https')
        current_app.logger.info(f"MS Tool Login Redirect URI: {redirect_uri}")
        
        state = os.urandom(16).hex()
        session['ms_tool_state'] = state
        
        # Generic OAuth2 Code Flow
        base_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": scopes,
            "state": state
        }
        
        import urllib.parse
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        return redirect(url)
    except Exception as e:
        current_app.logger.error(f"MS Tool Login Start Failed: {e}")
        return jsonify({"error": "Authentication failed. Please try again."}), 500

@auth_bp.route('/auth/microsoft/callback')
def microsoft_tool_callback():
    current_app.logger.info("Entering MS Tool Callback")
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/chat?error=auth_session_expired')
        
    code = request.args.get('code')
    state = request.args.get('state')
    
    if state != session.get('ms_tool_state'):
         current_app.logger.error("MS State mismatch")
         return redirect('/chat?error=state_mismatch')
         
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    redirect_uri = url_for('auth.microsoft_tool_callback', _external=True, _scheme='https')
    
    data = {
        "client_id": current_app.config['MICROSOFT_CLIENT_ID'],
        "client_secret": current_app.config['MICROSOFT_CLIENT_SECRET'],
        "scope": "Files.ReadWrite.All Sites.Read.All offline_access",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    try:
        current_app.logger.info(f"Exchanging code for MS tool token. URI: {redirect_uri}")
        r = requests.post(token_url, data=data)
        r.raise_for_status()
        tokens = r.json()
        
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 3600)
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        scope = tokens.get('scope', "")
        
        db.upsert_oauth_token(
            user_id,
            'microsoft',
            access_token,
            refresh_token,
            expires_at,
            scope
        )
        return redirect('/?status=microsoft_connected')
    except Exception as e:
        current_app.logger.error(f"Microsoft Tool Auth Error: {e}", exc_info=True)
        return redirect(f'/?error=microsoft_auth_failed&details={str(e)}')


# --- GITHUB TOOL ---
@auth_bp.route('/auth/github/login')
def github_tool_login():
    try:
        user_id = session.get('user_id')
        if not user_id: return jsonify({"error": "Not logged in"}), 401

        # DEBUG: Log what we see
        gh_id = current_app.config.get('GITHUB_CLIENT_ID')
        current_app.logger.info(f"Attempting GitHub Login. Client ID present? {bool(gh_id)}")

        client_id = gh_id
        if not client_id:
            return jsonify({"error": "GitHub Client ID not configured"}), 500

        # Scopes: repo (full control) or read:user (just identity). 
        # For our MCP, we need 'repo' to read private code/issues.
        scope = "repo read:user"
        state = secrets.token_urlsafe(16)
        session['github_state'] = state
        
        base_url = "https://github.com/login/oauth/authorize"
        redirect_uri = url_for('auth.github_tool_callback', _external=True, _scheme='https')
        
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state
        }
        
        import urllib.parse
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        return redirect(url)
    except Exception as e:
        current_app.logger.error(f"GitHub Auth Start Failed: {e}")
        return jsonify({"error": "Authentication failed. Please try again."}), 500

@auth_bp.route('/auth/github/callback')
def github_tool_callback():
    user_id = session.get('user_id')
    if not user_id: return redirect('/?error=session_expired')
    
    code = request.args.get('code')
    state = request.args.get('state')
    
    if state != session.get('github_state'):
        return redirect('/?error=state_mismatch')
        
    client_id = current_app.config.get('GITHUB_CLIENT_ID')
    client_secret = current_app.config.get('GITHUB_CLIENT_SECRET')
    
    token_url = "https://github.com/login/oauth/access_token"
    
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code
    }
    
    try:
        # GitHub returns form-encoded by default unless Accept header set
        headers = {"Accept": "application/json"}
        r = requests.post(token_url, json=data, headers=headers)
        r.raise_for_status()
        token_data = r.json()
        
        access_token = token_data.get('access_token')
        if not access_token:
            return redirect(f"/?error=github_token_missing&details={token_data}")
            
        # GitHub tokens don't always expire (unless configured), but we set a far future date if missing
        expires_in = token_data.get('expires_in', 31536000) # Default 1 year
        expires_at = datetime.now() + timedelta(seconds=int(expires_in))
        
        db.upsert_oauth_token(
            user_id,
            'github',
            access_token,
            None, # GitHub (classic) doesn't use refresh tokens usually
            expires_at,
            token_data.get('scope', '')
        )
        return redirect('/?status=github_connected')
        
    except Exception as e:
         current_app.logger.error(f"GitHub Callback Error: {e}")
         return redirect(f"/?error=github_callback_failed&details={str(e)}")


# =================================================================
# USER & SESSION MANAGEMENT
# =================================================================

@auth_bp.route('/me', methods=['GET'])
def get_me():
    """
    [GET /api/me]
    Returns full user details.
    """
    user_id = session.get('user_id') # Use session['user_id'] for consistency
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        # We fetch the FULL details from DB here.
        user_details = db.get_user_details(user_id)
        if not user_details:
            return jsonify({"ok": False, "error": "User details not found"}), 404
    
        active_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
        try:
            user_details['active_profile_details'] = get_profile(active_profile_name)
        except (KeyError, ValueError):
            # KeyError: persona no longer exists. ValueError: it failed
            # compile-time governance validation (e.g. rubric-less hard gate).
            # Either way, fall back to the default so login still works.
            db.update_user_profile(user_id, Config.DEFAULT_PROFILE)
            user_details['active_profile'] = Config.DEFAULT_PROFILE
            user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)
    
        user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
        
        # Ensure role/org are present
        if 'role' not in user_details: user_details['role'] = 'member'
        if 'org_id' not in user_details: user_details['org_id'] = None

        # Org-mandated MFA, not yet enrolled (restricted session): tell the
        # frontend to show the enrollment gate instead of the app.
        from flask import g as _g
        if getattr(_g, 'mfa_pending_enrollment', False):
            user_details['mfa_setup_required'] = True

        # Credential material never leaves the server, even hashed/encrypted.
        for _sensitive in ('password_hash', 'totp_secret', 'totp_enabled_at'):
            user_details.pop(_sensitive, None)

        # --- Self-Correction for Org Owners ---
        if user_details.get('org_id') and user_details.get('role') != 'admin':
            org = db.get_organization(user_details['org_id'])
            if org and org.get('owner_id') == user_id:
                current_app.logger.warning(f"User {user_id} is Org Owner but has role '{user_details['role']}'. Auto-promoting to ADMIN.")
                db.update_user_org_and_role(user_id, user_details['org_id'], 'admin')
                user_details['role'] = 'admin' # Update local dict
        # -------------------------------------------

        return jsonify({"ok": True, "user": user_details})
        
    except Exception as e:
        current_app.logger.error(f"/api/me error: {str(e)}", exc_info=True)
        return jsonify({'ok': False, 'error': 'Server error'}), 500

@auth_bp.route('/me/profile', methods=['PUT'])
def set_user_profile():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json
    profile_name = data.get('profile')
    db.update_user_profile(user_id, profile_name)
    return jsonify({"status": "success", "active_profile": profile_name})

@auth_bp.route('/me/models', methods=['PUT'])
def set_user_models():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json
    db.update_user_models(user_id, data.get('intellect_model'), data.get('will_model'), data.get('conscience_model'))
    return jsonify({"status": "success"})

@auth_bp.route('/me/delete', methods=['POST', 'DELETE'])
def delete_me():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    db.revoke_user_sessions(user_id, f"user:{user_id}")
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})

# =================================================================
# SESSION MANAGEMENT (self-service; enterprise identity Phase 1)
# =================================================================

@auth_bp.route('/me/sessions', methods=['GET'])
def list_my_sessions():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    from flask import g
    rows = db.list_user_sessions(user_id)
    current = getattr(g, 'sid', None)
    out = [{
        "id": r["id"],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "last_seen_at": r["last_seen_at"].isoformat() if r.get("last_seen_at") else None,
        "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
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
    """Log out everywhere else — revokes every session except the current."""
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    from flask import g
    count = db.revoke_user_sessions(user_id, f"user:{user_id}", keep_sid=getattr(g, 'sid', None))
    return jsonify({"ok": True, "revoked": count})

# =================================================================
# TOTP MFA SELF-SERVICE (enterprise identity Phase 2)
# =================================================================

@auth_bp.route('/me/mfa', methods=['GET'])
def get_my_mfa():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    state = db.get_user_totp(user_id)
    user = db.get_user_details(user_id) or {}
    cfg = db.get_org_identity_config(user.get('org_id'))
    return jsonify({"ok": True, "totp_enabled": state['enabled'],
                    "org_requires_mfa": bool(cfg.get('require_mfa')),
                    # OAuth accounts satisfy MFA at the IdP, not here.
                    "local_account": bool(user.get('password_hash'))})


@auth_bp.route('/me/mfa/totp/setup', methods=['POST'])
def setup_my_totp():
    """Generate a pending secret and return it (Base32 + otpauth URI). Not
    enforced at login until confirmed with a live code via /verify."""
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
    """Confirm enrollment with a live code. If the current session was a
    restricted mfa_pending_enrollment session (org-mandated MFA), upgrade it
    in place so the user proceeds without re-login."""
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

    _mfa_attempts.pop(user_id, None)
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
    """Self-service disable — requires a live code so a hijacked session
    cannot strip the second factor."""
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    if _mfa_rate_limited(user_id):
        return jsonify({"error": "Too many attempts. Wait a few minutes."}), 429
    state = db.get_user_totp(user_id)
    if not state['enabled']:
        # Pending (unconfirmed) enrollments can be dropped without a code.
        db.disable_user_totp(user_id, f"user:{user_id}")
        return jsonify({"ok": True, "totp_enabled": False})
    code = (request.get_json(silent=True) or {}).get('code') or ''
    if not totp_lib.verify_code(state['secret'], code):
        _mfa_record_attempt(user_id)
        db.log_auth_event('mfa_failed', f"user:{user_id}", user_id=user_id,
                          detail={"method": "totp", "phase": "disable"})
        return jsonify({"error": "Invalid code."}), 401
    user = db.get_user_details(user_id) or {}
    db.disable_user_totp(user_id, f"user:{user_id}", org_id=user.get('org_id'))
    return jsonify({"ok": True, "totp_enabled": False})


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """
    [POST /api/logout]
    Revokes the server-side session and clears the cookie.
    """
    sid = session.get('sid')
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if sid:
        db.revoke_session(sid, f"user:{user_id or 'unknown'}", reason='logout')
        db.log_auth_event('logout', f"user:{user_id or 'unknown'}",
                          user_id=user_id, session_id=sid)
    session.clear()
    return jsonify({"ok": True})
    return redirect('/') if request.method == 'GET' else jsonify({"status": "success"})