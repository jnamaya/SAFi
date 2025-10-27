from flask import Blueprint, session, jsonify, request, url_for, redirect, current_app
import secrets
from .. import oauth
from ..persistence import database as db
from ..config import Config
from ..core.values import get_profile, list_profiles

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    """
    Redirect to Google's OAuth consent screen.
    """
    redirect_uri = url_for('auth.callback', _external=True)
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)


@auth_bp.route('/callback')
def callback():
    """
    Handle the callback from Google after authentication.
    """
    try:
        token = oauth.google.authorize_access_token()
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
        return redirect('/')
    except Exception as e:
        # In a production environment, this would be logged.
        # For the MVP, we redirect with a generic error.
        return redirect('/?error=auth_failed')


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
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    user_details = db.get_user_details(user_id)
    if not user_details:
        return jsonify({"ok": False, "error": "User not found"}), 404

    active_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
    
    try:
        user_details['active_profile_details'] = get_profile(active_profile_name)
    except KeyError:
        # User had an invalid profile, fall back to default
        try:
            db.update_user_profile(user_id, Config.DEFAULT_PROFILE)
            
            user_details['active_profile'] = Config.DEFAULT_PROFILE
            user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)
            
            user_session = session.get('user', {})
            user_session['active_profile'] = Config.DEFAULT_PROFILE
            session['user'] = user_session

        except Exception as e:
            # This is a critical server misconfiguration
            return jsonify({'ok': False, 'error': 'Server configuration error'}), 500

    # Populate model preferences, using system defaults as a fallback.
    user_details['intellect_model'] = user_details.get('intellect_model') or Config.INTELLECT_MODEL
    user_details['will_model'] = user_details.get('will_model') or Config.WILL_MODEL
    user_details['conscience_model'] = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL

    return jsonify({"ok": True, "user": user_details})


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
        return jsonify({"error": "Failed to update model preferences."}), 500


@auth_bp.route('/me/delete', methods=['POST'])
def delete_me():
    """
    Permanently delete the user's account and all associated data.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})
