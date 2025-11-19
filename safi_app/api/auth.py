"""
Defines the authentication and user management API endpoints.

This blueprint handles all user-facing authentication logic, including:
- Google OAuth 2.0 flow for web and mobile.
- Session management (login, logout, /me).
- User profile and model preference management.
- Account deletion.
"""
from flask import Blueprint, session, jsonify, request, url_for, redirect, current_app
import secrets
import traceback
import requests
import base64
from .. import oauth
from ..persistence import database as db
from ..config import Config
from ..core.values import get_profile, list_profiles
from authlib.integrations.base_client.errors import OAuthError

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    """
    [GET /api/login]
    Initiates the Google OAuth 2.0 login flow for web clients.
    """
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    return oauth.google.authorize_redirect(Config.WEB_CALLBACK_URL, nonce=nonce)


@auth_bp.route('/callback')
def callback():
    """
    [GET /api/callback]
    Handles the redirect callback from Google.
    """
    try:
        current_app.logger.info("Web callback initiated.")
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

        # FIX: Store minimal data in session to prevent "Cookie too large" errors.
        # Google pictures are URLs, so they are safe, but we strip unnecessary fields anyway.
        session_user = {
            'id': user_details['id'],
            'email': user_details.get('email'),
            'name': user_details.get('name'),
            'active_profile': user_details.get('active_profile')
        }
        session['user'] = session_user
        
        current_app.logger.info(f"Web callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
        
    except Exception as e:
        current_app.logger.error(f"Web callback error: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return redirect('/?error=auth_failed')


@auth_bp.route('/login/microsoft')
def login_microsoft():
    """
    [GET /api/login/microsoft]
    Initiates the Microsoft OAuth 2.0 login flow.
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

        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        # FIX: Critical Session Size Optimization
        # We create a lightweight session object. 
        # We DO NOT include 'picture' here because for Microsoft users, it is a 
        # massive Base64 string that exceeds the 4KB browser cookie limit.
        session_user = {
            'id': user_details['id'],
            'email': user_details.get('email'),
            'name': user_details.get('name'),
            'active_profile': user_details.get('active_profile'),
            # Note: We exclude 'picture' from the cookie. The frontend fetches
            # full user details (including the picture) via /api/me anyway.
        }
        session['user'] = session_user
        
        current_app.logger.info(f"Microsoft callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
        
    except Exception as e:
        current_app.logger.error(f"Microsoft callback error: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return redirect('/?error=auth_failed')


@auth_bp.route('/auth/google/mobile', methods=['POST'])
def mobile_callback():
    """
    [POST /api/auth/google/mobile]
    """
    current_app.logger.info("Mobile auth callback initiated.")
    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({"ok": False, "error": "No 'code' provided."}), 400

    try:
        redirect_uri = Config.WEB_CALLBACK_URL
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'code': code,
            'client_id': oauth.google.client_id,
            'client_secret': oauth.google.client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        token_response = requests.post(token_url, data=token_data)
        
        if not token_response.ok:
            raise OAuthError(error='token_exchange_failed')
        
        token = token_response.json()
        user_info = oauth.google.parse_id_token(token, nonce=None)

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

        # Optimized Session
        session_user = {
            'id': user_details['id'],
            'email': user_details.get('email'),
            'name': user_details.get('name'),
            'active_profile': user_details.get('active_profile')
        }
        session['user'] = session_user
        
        return jsonify({"ok": True, "status": "login_success"})

    except Exception as e:
        current_app.logger.error(f"Exception in mobile login: {str(e)}")
        return jsonify({"ok": False, "error": f"Server error: {str(e)}"}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({"status": "logged_out"})


@auth_bp.route('/me', methods=['GET'])
def get_me():
    """
    [GET /api/me]
    Returns full user details.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        # We fetch the FULL details (including the massive picture blob) from DB here.
        # This is fine because /api/me returns JSON, which has a much higher size limit than cookies.
        user_details = db.get_user_details(user_id)
        if not user_details:
            session.pop('user', None)
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
    
        return jsonify({"ok": True, "user": user_details})
        
    except Exception as e:
        current_app.logger.error(f"/api/me error: {str(e)}")
        return jsonify({'ok': False, 'error': 'Server error'}), 500

# ... (Profile/Model update routes remain unchanged) ...
@auth_bp.route('/me/profile', methods=['PUT'])
def set_user_profile():
    user_id = session.get('user', {}).get('id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json
    profile_name = data.get('profile')
    db.update_user_profile(user_id, profile_name)
    # Update session
    user_session = session.get('user', {})
    user_session['active_profile'] = profile_name
    session['user'] = user_session
    return jsonify({"status": "success", "active_profile": profile_name})

@auth_bp.route('/me/models', methods=['PUT'])
def set_user_models():
    user_id = session.get('user', {}).get('id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    data = request.json
    db.update_user_models(user_id, data.get('intellect_model'), data.get('will_model'), data.get('conscience_model'))
    # Update session (optional since we fetch fresh on /me, but good for consistency)
    # We don't store models in session anymore to save space, so nothing to update here.
    return jsonify({"status": "success"})

@auth_bp.route('/me/delete', methods=['POST'])
def delete_me():
    user_id = session.get('user', {}).get('id')
    if not user_id: return jsonify({"error": "Auth required"}), 401
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})