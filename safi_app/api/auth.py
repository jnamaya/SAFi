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
    Redirects the user to Google's consent screen.
    """
    # Create a unique, unguessable nonce to prevent CSRF attacks
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    
    # Redirect to Google, specifying the callback URL from our config
    return oauth.google.authorize_redirect(Config.WEB_CALLBACK_URL, nonce=nonce)


@auth_bp.route('/callback')
def callback():
    """
    [GET /api/callback]
    Handles the redirect callback from Google after successful authentication.
    Exchanges the authorization code for an access token and user info.
    """
    try:
        current_app.logger.info("Web callback initiated.")
        
        # Complete the OAuth flow by exchanging the code for a token
        # This implicitly uses the redirect_uri from the config
        token = oauth.google.authorize_access_token() 
        
        # Validate the nonce to ensure the request originated from our site
        nonce = session.pop('nonce', None)
        oauth.google.parse_id_token(token, nonce=nonce)
        
        # Fetch user info from Google
        user_info = oauth.google.get('userinfo').json()

        # Create or update the user in the database
        db.upsert_user(user_info)
        
        user_id = user_info.get('sub') or user_info.get('id')
        user_details = db.get_user_details(user_id)

        # Assign a default profile if this is a new user
        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        # Store user details in the server-side session
        session['user'] = user_details
        current_app.logger.info(f"Web callback successful for User {user_id}. Redirecting to /")
        return redirect('/')
        
    except Exception as e:
        current_app.logger.error(f"Web callback error: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return redirect('/?error=auth_failed')


@auth_bp.route('/auth/google/mobile', methods=['POST'])
def mobile_callback():
    """
    [POST /api/auth/google/mobile]
    Handles authentication for mobile clients.
    
    The mobile app performs the initial Google Sign-In and sends a
    one-time 'serverAuthCode' here. This endpoint exchanges that code
    for tokens on the server, creates a session, and returns a
    success status to the mobile app.
    """
    current_app.logger.info("Mobile auth callback initiated.")
    data = request.json
    code = data.get('code')
    if not code:
        current_app.logger.error("Mobile auth: No 'code' provided in POST body.")
        return jsonify({"ok": False, "error": "No 'code' provided."}), 400

    try:
        # The redirect_uri must match *exactly* what is in the Google Cloud console
        redirect_uri = Config.WEB_CALLBACK_URL
        
        current_app.logger.info(f"Attempting mobile token exchange for code: {code[:20]}...")
        
        # Manually exchange the authorization code for an access token
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
            # Handle failure from Google's token endpoint
            error_data = token_response.json()
            current_app.logger.error(f"Token exchange failed: {error_data}")
            raise OAuthError(
                error=error_data.get('error', 'token_exchange_failed'),
                description=error_data.get('error_description', 'Failed to exchange authorization code')
            )
        
        token = token_response.json()
        current_app.logger.info("Mobile token exchange successful.")
        
        # Parse the ID token to get user info securely
        # Nonce is not used for this server-initiated flow
        user_info = oauth.google.parse_id_token(token, nonce=None)
        current_app.logger.info(f"User info retrieved for: {user_info.get('email')}")

        # Log the user in (same logic as /callback)
        db.upsert_user(user_info)
        user_id = user_info.get('sub') or user_info.get('id')
        user_details = db.get_user_details(user_id)

        # Set default profile if one isn't set
        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        # Store user details in the session
        session['user'] = user_details
        
        current_app.logger.info(f"Mobile login successful for user: {user_id}.")
        
        # Return success JSON to the mobile app
        return jsonify({"ok": True, "status": "login_success"})

    except OAuthError as e:
        current_app.logger.error(f"OAuthError in mobile login: {e.description or e.error}")
        return jsonify({
            "ok": False, 
            "error": f"OAuth error: {e.description or e.error}"
        }), 401
        
    except Exception as e:
        current_app.logger.error(f"Exception in mobile login: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            "ok": False, 
            "error": f"Server error: {str(e)}"
        }), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    [POST /api/logout]
    Clears the user's session from the server.
    """
    session.pop('user', None)
    return jsonify({"status": "logged_out"})


@auth_bp.route('/me', methods=['GET'])
def get_me():
    """
    [GET /api/me]
    Returns the full details for the currently authenticated user.
    
    This is the primary endpoint for the frontend to verify a session
    and get all necessary user data (profile, model preferences, etc.).
    """
    current_app.logger.info("/api/me endpoint hit.")
    user_id = session.get('user', {}).get('id')
    if not user_id:
        current_app.logger.warning("/api/me failed: User not authenticated.")
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        current_app.logger.info(f"/api/me: Fetching details for {user_id}.")
        user_details = db.get_user_details(user_id)
        if not user_details:
            # Session exists but user was deleted from DB
            session.pop('user', None)
            current_app.logger.error(f"/api/me failed: User DB record not found for {user_id}.")
            return jsonify({"ok": False, "error": "User details not found"}), 404
    
        active_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
        
        try:
            # Load the full profile details (values, rules, etc.)
            user_details['active_profile_details'] = get_profile(active_profile_name)
        except KeyError:
            # User's active_profile is invalid (e.g., removed from config)
            current_app.logger.warning(f"/api/me: Invalid profile '{active_profile_name}'. Falling back to default.")
            try:
                # Reset user to the default profile
                db.update_user_profile(user_id, Config.DEFAULT_PROFILE)
                user_details['active_profile'] = Config.DEFAULT_PROFILE
                user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)
                
                # Update the session as well
                user_session = session.get('user', {})
                user_session['active_profile'] = Config.DEFAULT_PROFILE
                session['user'] = user_session
    
            except Exception as e:
                # This is a critical server misconfiguration (e.g., default profile is invalid)
                current_app.logger.error(f"Profile configuration error: {str(e)}")
                return jsonify({'ok': False, 'error': 'Server configuration error'}), 500
    
        # Populate model preferences, using system defaults as a fallback
        user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        user_details['will_model'] = user_details.get('will_model') or Config.WILL_MODEL
        user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
    
        current_app.logger.info(f"/api/me SUCCESS. Returning JSON user data for {user_id}.")
        return jsonify({"ok": True, "user": user_details})
        
    except Exception as e:
        # Catch-all for any other unexpected errors
        current_app.logger.error(f"/api/me UNEXPECTED EXCEPTION: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'ok': False, 'error': 'Internal server error during user retrieval'}), 500


@auth_bp.route('/me/profile', methods=['PUT'])
def set_user_profile():
    """
    [PUT /api/me/profile]
    Updates the user's active profile preference.
    Expects JSON: {"profile": "profile_name"}
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    data = request.json
    profile_name = data.get('profile')
    
    # Validate that the selected profile is one that the server knows about
    available_keys = [p['key'] for p in list_profiles()]
    if not profile_name or profile_name not in available_keys:
        return jsonify({"error": "Invalid profile name provided."}), 400

    # Update the database
    db.update_user_profile(user_id, profile_name)
    
    # Update the session immediately
    user_session = session.get('user', {})
    user_session['active_profile'] = profile_name
    session['user'] = user_session
    
    return jsonify({"status": "success", "active_profile": profile_name})


@auth_bp.route('/me/models', methods=['PUT'])
def set_user_models():
    """
    [PUT /api/me/models]
    Updates the user's model preferences for each faculty.
    Expects JSON: {
        "intellect_model": "model_name",
        "will_model": "model_name",
        "conscience_model": "model_name"
    }
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    data = request.json
    intellect_model = data.get('intellect_model')
    will_model = data.get('will_model')
    conscience_model = data.get('conscience_model')

    if not all([intellect_model, will_model, conscience_model]):
        return jsonify({"error": "All three models (intellect, will, conscience) are required."}), 400

    # Validate that all selected models are in the server's allow-list
    available = Config.AVAILABLE_MODELS
    if any(m not in available for m in [intellect_model, will_model, conscience_model]):
        return jsonify({"error": "One or more provided models are not in the available list."}), 400

    try:
        # Update the database
        db.update_user_models(user_id, intellect_model, will_model, conscience_model)
        
        # Update the session immediately
        user_session = session.get('user', {})
        user_session['intellect_model'] = intellect_model
        user_session['will_model'] = will_model
        user_session['conscience_model'] = conscience_model
        session['user'] = user_session
        
        return jsonify({
            "status": "success",
            "models": {
                "intellect_model": intellect_model,
                "will_model": will_model,
                "conscience_model": conscience_model
            }
        })
    except Exception as e:
        current_app.logger.error(f"Failed to update models: {str(e)}")
        return jsonify({"error": "Failed to update model preferences."}), 500


@auth_bp.route('/me/delete', methods=['POST'])
def delete_me():
    """
    [POST /api/me/delete]
    Permanently delete the user's account and all associated data
    (profile, conversations, etc.).
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        # This will cascade and delete all related data
        db.delete_user(user_id)
        # Clear the session to log them out
        session.clear()
        return jsonify({"status": "success"})
    except Exception as e:
        current_app.logger.error(f"Failed to delete user {user_id}: {str(e)}")
        return jsonify({"error": "Failed to delete account"}), 500