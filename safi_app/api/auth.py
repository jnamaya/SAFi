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

        # --- FIXED: Removed DATABASE_NAME argument ---
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
        current_app.logger.error(f"Authentication failed: {e}")
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
    Return the current user's details, including their full active profile.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    # --- FIXED: Removed DATABASE_NAME argument ---
    user_details = db.get_user_details(user_id)
    if not user_details:
        return jsonify({"ok": False, "error": "User not found"}), 404

    active_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
    
    try:
        user_details['active_profile_details'] = get_profile(active_profile_name)
    except KeyError:
        user_details['active_profile_details'] = get_profile(Config.DEFAULT_PROFILE)

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
    
    if not profile_name or profile_name not in list_profiles():
        return jsonify({"error": "Invalid profile name provided."}), 400

    # --- FIXED: Removed DATABASE_NAME argument ---
    db.update_user_profile(user_id, profile_name)
    
    user_session = session.get('user', {})
    user_session['active_profile'] = profile_name
    session['user'] = user_session
    
    return jsonify({"status": "success", "active_profile": profile_name})


@auth_bp.route('/me/delete', methods=['POST'])
def delete_me():
    """
    Permanently delete the user's account and all associated data.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    # --- FIXED: Removed DATABASE_NAME argument ---
    db.delete_user(user_id)
    session.clear()
    return jsonify({"status": "success"})
