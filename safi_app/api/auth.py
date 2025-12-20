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
from ..core.values import get_profile, list_profiles
from authlib.integrations.base_client.errors import OAuthError
from google_auth_oauthlib.flow import Flow # For Tool Auth
import jwt

auth_bp = Blueprint('auth', __name__)

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
        # Generate Token (5 minute expiry)
        payload = {
            "sub": user_id,
            "role": role,
            "org_id": user.get('org_id'),
            "email": user.get('email'),
            "type": "dashboard_access",
            "exp": datetime.utcnow() + timedelta(minutes=30)
        }
        
        token = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode('utf-8')
            
        return jsonify({"token": token})
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
            # NEW: Domain-based Auto-Join
            # If the user has a domain that matches a verified organization, join them as MEMBER.
            try:
                user_email = user_details.get('email', '')
                if '@' in user_email:
                    domain = user_email.split('@')[-1]
                    existing_org = db.get_organization_by_domain(domain)
                    if existing_org:
                        user_details['org_id'] = existing_org['id']
                        user_details['role'] = 'member'
                        db.update_user_org_and_role(user_id, existing_org['id'], 'member')
                        current_app.logger.info(f"User {user_id} auto-joined org {existing_org['name']} (Domain: {domain})")
            except Exception as e:
                current_app.logger.error(f"Error in domain auto-join: {e}")

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

        # FIX: Store minimal data in session to prevent "Cookie too large" errors.
        session_user = {
            'id': user_details['id'],
            'email': user_details.get('email'),
            'name': user_details.get('name'),
            'active_profile': user_details.get('active_profile'),
            'role': user_details.get('role', 'member'),
            'org_id': user_details.get('org_id')
        }
        session['user'] = session_user
        
        # Compatibility with Tool Auth (which uses simple keys)
        session['user_id'] = user_details['id']
        session['user_email'] = user_details.get('email')
        
        current_app.logger.info(f"Web callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
    except Exception as e:
        current_app.logger.error(f"Web callback error: {str(e)}", exc_info=True)
        return redirect('/?error=auth_failed')


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
    """
    try:
        # 1. Lazy Cleanup
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
                'name': "Demo Admin",
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

        # 4. Create Session
        session_user = {
            'id': user_to_login['id'],
            'email': user_to_login.get('email'),
            'name': user_to_login.get('name'),
            'active_profile': user_to_login.get('active_profile', Config.DEFAULT_PROFILE),
            'role': user_to_login.get('role', 'admin'),
            'org_id': user_to_login.get('org_id'),
            'is_demo': True 
        }
        session['user'] = session_user
        session['user_id'] = user_to_login['id']
        
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
        
        # Reuse user setup logic (Org/Profile)
        if not user_details.get('org_id'):
            try:
                user_email = user_details.get('email', '')
                if '@' in user_email:
                    domain = user_email.split('@')[-1]
                    existing_org = db.get_organization_by_domain(domain)
                    if existing_org:
                        user_details['org_id'] = existing_org['id']
                        user_details['role'] = 'member'
                        db.update_user_org_and_role(user_id, existing_org['id'], 'member')
            except Exception: pass # logging handled elsewhere

        # Create session
        session_user = {
            'id': user_details['id'],
            'email': user_details.get('email'),
            'name': user_details.get('name'),
            'active_profile': user_details.get('active_profile'),
            'role': user_details.get('role', 'member'),
            'org_id': user_details.get('org_id')
        }
        session['user'] = session_user
        session['user_id'] = user_details['id']
        
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
        return jsonify({"error": str(e)}), 500

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
        return jsonify({"error": str(e)}), 500

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
        current_app.logger.info(f"DEBUG: Attempting GitHub Login. Client ID present? {bool(gh_id)} (Value: {gh_id if gh_id else 'None'})")

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
        return jsonify({"error": str(e)}), 500

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
        except KeyError:
            # Fallback logic...
            db.update_user_profile(user_id, Config.DEFAULT_PROFILE)
            user_details['active_profile'] = Config.DEFAULT_PROFILE
            user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)
    
        user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        user_details['will_model'] = user_details.get('will_model') or Config.WILL_MODEL
        user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
        
        # Ensure role/org are present
        if 'role' not in user_details: user_details['role'] = 'member'
        if 'org_id' not in user_details: user_details['org_id'] = None

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

@auth_bp.route('/me/delete', methods=['POST'])
def delete_me():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """
    [POST /api/logout]
    Clears the server-side session.
    """
    session.clear()
    return redirect('/') if request.method == 'GET' else jsonify({"status": "success"})