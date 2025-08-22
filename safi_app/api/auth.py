from flask import Blueprint, session, url_for, redirect, jsonify
from .. import oauth  # This now safely imports the initialized oauth object
from ..persistence import database as db
from ..config import Config

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    redirect_uri = url_for('auth.callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/callback')
def callback():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get('userinfo').json()
    session['user'] = user_info
    db.upsert_user(Config.DATABASE_NAME, user_info)
    return redirect("/")

@auth_bp.route('/logout')
def logout():
    session.pop('user', None)
    return jsonify({"status": "logged_out"})

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    user = session.get('user')
    if user:
        return jsonify(user)
    return jsonify({"error": "Not authenticated"}), 401

@auth_bp.route('/me', methods=['DELETE'])
def delete_me():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Authentication required."}), 401
    
    user_id = user.get('sub') or user.get('id')
    db.delete_user_data(Config.DATABASE_NAME, user_id)
    session.pop('user', None)
    return jsonify({"status": "success"})
