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

# --- CRITICAL FIX: Hardcoded Authorized Redirect URI ---
# UPDATED: Using the correct 'safi.selfalignmentframework.com' subdomain and HTTPS.
# ENSURE THIS EXACT STRING IS REGISTERED IN GOOGLE CLOUD CONSOLE.
WEB_REDIRECT_URI = "https://safi.selfalignmentframework.com/api/callback"
WEB_REDIRECT_URI = "https://chat.selfalignmentframework.com/api/callback"
# -------------------------------------------------------


@auth_bp.route('/login')
def login():
    """
    Redirect to Google's OAuth consent screen.
    Uses the hardcoded WEB_REDIRECT_URI.
    """
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce

    
    # Pass the hardcoded constant as the redirect_uri argument
    return oauth.google.authorize_redirect(WEB_REDIRECT_URI, nonce=nonce)


@auth_bp.route('/callback')
def callback():
    """
    Handle the callback from Google after authentication.
    """
    try:
        current_app.logger.info("LOG: Web callback initiated.") # NEW LOGGING
        # --- FIX APPLIED HERE: Removed redundant redirect_uri argument ---
        # authlib will automatically infer the redirect_uri from the request,
        # which is now forced to HTTPS by the previous authorize_redirect call.
        token = oauth.google.authorize_access_token() 
        # -----------------------------------------------------------------
        nonce = session.pop('nonce', None)
        oauth.google.parse_id_token(token, nonce=nonce)
        
        user_info = oauth.google.get('userinfo').json()

        db.upsert_user(user_info)
        
        user_id = user_info.get('sub') or user_info.get('id')
        user_details = db.get_user_details(user_id)

        if not user_details.get('active_profile'):
            default_profile = Config.DEFAULT_PROFILE
            db.update_user_profile(user_id, default_profile)
            user_details['active_profile'] = default_profile

        session['user'] = user_details
        current_app.logger.info(f"LOG: Web callback successful for User {user_id}. Redirecting.") # NEW LOGGING
        return redirect('/')
    except Exception as e:
        # In a production environment, this would be logged.
        # For the MVP, we redirect with a generic error.
        current_app.logger.error(f"Web callback error: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return redirect('/?error=auth_failed')


@auth_bp.route('/auth/google/mobile', methods=['POST'])
def mobile_callback():
    """
    Handle the mobile app's login request.
    The mobile app sends a one-time 'serverAuthCode' from the GoogleAuth plugin.
    """
    current_app.logger.info("LOG: Mobile callback attempt received.") # NEW LOGGING
    data = request.json
    code = data.get('code')
    if not code:
        current_app.logger.error("Mobile login: No code provided")
        return jsonify({"ok": False, "error": "No 'code' provided."}), 400

    try:
        # Use the same authorized redirect_uri for mobile/backend exchange
        redirect_uri = WEB_REDIRECT_URI
        
        current_app.logger.info("=" * 50)
        current_app.logger.info("Mobile login attempt")
        current_app.logger.info(f"Redirect URI: {redirect_uri}")
        current_app.logger.info(f"Code (first 20 chars): {code[:20]}...")
        current_app.logger.info(f"OAuth client configured: {oauth.google.client_id}")
        
        # Exchange the authorization code for an access token
        # This is where we MUST use the correct hardcoded HTTPS URI
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'code': code,
            'client_id': oauth.google.client_id,
            'client_secret': oauth.google.client_secret,
            'redirect_uri': redirect_uri, # CRITICAL: Ensure this is the HTTPS URI
            'grant_type': 'authorization_code'
        }
        
        current_app.logger.info(f"Making token exchange request to: {token_url}")
        token_response = requests.post(token_url, data=token_data)
        
        if not token_response.ok:
            error_data = token_response.json()
            current_app.logger.error(f"Token exchange failed: {error_data}")
            raise OAuthError(
                error=error_data.get('error', 'token_exchange_failed'),
                description=error_data.get('error_description', 'Failed to exchange authorization code')
            )
        
        token = token_response.json()
        
        current_app.logger.info("Token exchange successful! Persisting user session.") # NEW LOGGING
        
        # Parse the ID token to get user info securely
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
        
        current_app.logger.info(f"Mobile login successful for user: {user_id}. Returning JSON.") # NEW LOGGING
        current_app.logger.info("=" * 50)
        
        # Return success JSON to the mobile app
        return jsonify({"ok": True, "status": "login_success"})

    except OAuthError as e:
        current_app.logger.error("=" * 50)
        current_app.logger.error("OAuthError in mobile login:")
        current_app.logger.error(f"  Error type: {e.error}")
        current_app.logger.error(f"  Description: {e.description}")
        current_app.logger.error(f"  URI: {getattr(e, 'uri', 'N/A')}")
        current_app.logger.error(f"  Full error: {str(e)}")
        current_app.logger.error("=" * 50)
        return jsonify({
            "ok": False, 
            "error": f"OAuth error: {e.description or e.error}"
        }), 401
        
    except Exception as e:
        current_app.logger.error("=" * 50)
        current_app.logger.error("Exception in mobile login:")
        current_app.logger.error(f"  Exception type: {type(e).__name__}")
        current_app.logger.error(f"  Exception message: {str(e)}")
        current_app.logger.error("  Full traceback:")
        current_app.logger.error(traceback.format_exc())
        current_app.logger.error("=" * 50)
        return jsonify({
            "ok": False, 
            "error": f"Server error: {str(e)}"
        }), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Clear the user session.
    """
    session.pop('user', None)
    return jsonify({"status": "logged_out"})


@auth_bp.route('/me', methods=['GET'])
def get_me():
    """
    Return the current user's details, including their full active profile
    and model preferences.
    """
    current_app.logger.info("LOG: /api/me endpoint hit.") # NEW LOGGING
    user_id = session.get('user', {}).get('id')
    if not user_id:
        current_app.logger.warning("LOG: /api/me failed: User not authenticated (missing session user_id).") # NEW LOGGING
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    # --- CRITICAL FIX START: Wrap potentially failing code in try/except ---
    try:
        current_app.logger.info(f"LOG: /api/me authenticated successfully. Fetching details for {user_id}.") # NEW LOGGING
        user_details = db.get_user_details(user_id)
        if not user_details:
            # Although the session exists, the DB record might not (if deleted externally)
            session.pop('user', None)
            current_app.logger.error(f"LOG: /api/me failed: User DB record not found for {user_id}.") # NEW LOGGING
            return jsonify({"ok": False, "error": "User details not found"}), 404
    
        active_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
        
        try:
            user_details['active_profile_details'] = get_profile(active_profile_name)
        except KeyError:
            # User had an invalid profile, fall back to default
            current_app.logger.warning(f"LOG: /api/me: Invalid profile '{active_profile_name}'. Falling back to default.") # NEW LOGGING
            try:
                db.update_user_profile(user_id, Config.DEFAULT_PROFILE)
                
                user_details['active_profile'] = Config.DEFAULT_PROFILE
                user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)
                
                user_session = session.get('user', {})
                user_session['active_profile'] = Config.DEFAULT_PROFILE
                session['user'] = user_session
    
            except Exception as e:
                # This is a critical server misconfiguration
                current_app.logger.error(f"Profile configuration error: {str(e)}")
                return jsonify({'ok': False, 'error': 'Server configuration error'}), 500
    
        # Populate model preferences, using system defaults as a fallback.
        user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        user_details['will_model'] = user_details.get('will_model') or Config.WILL_MODEL
        user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
    
        # Final success return
        current_app.logger.info(f"LOG: /api/me SUCCESS. Returning JSON user data.") # NEW LOGGING
        return jsonify({"ok": True, "user": user_details})
        
    except Exception as e:
        # Catch all unexpected errors during processing and return JSON
        current_app.logger.error(f"LOG: /api/me UNEXPECTED EXCEPTION: {str(e)}") # NEW LOGGING
        current_app.logger.error(traceback.format_exc())
        return jsonify({'ok': False, 'error': 'Internal server error during user retrieval'}), 500

    # --- CRITICAL FIX END ---


@auth_bp.route('/me/profile', methods=['PUT'])
def set_user_profile():
    """
    Update the user's active profile preference in the database and session.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    data = request.json
    profile_name = data.get('profile')
    
    available_keys = [p['key'] for p in list_profiles()]
    if not profile_name or profile_name not in available_keys:
        return jsonify({"error": "Invalid profile name provided."}), 400

    db.update_user_profile(user_id, profile_name)
    
    user_session = session.get('user', {})
    user_session['active_profile'] = profile_name
    session['user'] = user_session
    
    return jsonify({"status": "success", "active_profile": profile_name})


@auth_bp.route('/me/models', methods=['PUT'])
def set_user_models():
    """
    Update the user's active model preferences in the database.
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

    # Validate against the available models list from Config
    available = Config.AVAILABLE_MODELS
    if any(m not in available for m in [intellect_model, will_model, conscience_model]):
        return jsonify({"error": "One or more provided models are not in the available list."}), 400

    try:
        db.update_user_models(user_id, intellect_model, will_model, conscience_model)
        
        # Update session data as well
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
    Permanently delete the user's account and all associated data.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        db.delete_user(user_id)
        session.clear()
        return jsonify({"status": "success"})
    except Exception as e:
        current_app.logger.error(f"Failed to delete user: {str(e)}")
        return jsonify({"error": "Failed to delete account"}), 500