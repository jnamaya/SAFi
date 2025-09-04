import asyncio
import json
from flask import Blueprint, session, jsonify, request, Response
from datetime import datetime, timezone

from ..persistence import database as db
from ..core.orchestrator import SAFi
from ..core.values import get_profile, list_profiles
from ..config import Config

conversations_bp = Blueprint('conversations', __name__)

# --- CHANGE: Added a cache for SAFi instances ---
# This dictionary will store initialized SAFi orchestrators, keyed by their
# profile name. This is a major optimization that prevents re-creating the
# SAFi object and its faculties on every single request.
safi_instances = {}

def _load_safi(profile_name: str) -> SAFi:
    """
    Build and return a SAFi orchestrator, using a cache to avoid re-creation.
    """
    # --- CHANGE: Check the cache first ---
    # If an instance for this profile already exists, return it immediately.
    if profile_name in safi_instances:
        return safi_instances[profile_name]

    # If not in the cache, create a new instance
    prof = get_profile(profile_name)
    instance = SAFi(config=Config, value_profile_or_list=prof)
    
    # --- CHANGE: Store the new instance in the cache ---
    safi_instances[profile_name] = instance
    return instance

def get_user_id():
    """
    Return the authenticated user id stored in session.
    """
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')

def get_user_profile_name():
    """
    Get the user's active profile from session, falling back to the default.
    """
    user = session.get('user', {})
    return user.get('active_profile') or Config.DEFAULT_PROFILE


@conversations_bp.route('/process_prompt', methods=['POST'])
def process_prompt_endpoint():
    """
    Process a user prompt using their selected profile.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    limit = Config.DAILY_PROMPT_LIMIT
    if limit > 0:
        count = db.get_todays_prompt_count(user_id)
        if count >= limit:
            return jsonify({"error": f"Daily limit of {limit} messages reached."}), 429

    data = request.json
    if 'message' not in data or 'conversation_id' not in data:
        return jsonify({"error": "'message' and 'conversation_id' are required."}), 400
    
    if limit > 0:
        db.record_prompt_usage(user_id)
    
    user_profile = get_user_profile_name()
    saf_system = _load_safi(user_profile)
    
    result = asyncio.run(saf_system.process_prompt(data['message'], user_id, data['conversation_id']))
    return jsonify(result)


@conversations_bp.route('/audit_result/<message_id>', methods=['GET'])
def get_audit_result_endpoint(message_id):
    """
    Poll audit status and results for a specific message id.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    result = db.get_audit_result(message_id)

    if result:
        return jsonify(result)
    else:
        return jsonify({"status": "not_found"}), 404


@conversations_bp.route('/health')
def health_check():
    """
    Lightweight readiness probe.
    """
    return jsonify({"status": "ok"})


@conversations_bp.route('/profiles', methods=['GET'])
def profiles_list():
    """
    Return available profiles and the active one for the current user.
    """
    user_profile_name = get_user_profile_name()
    active_profile_details = {}
    try:
        active_profile_details = get_profile(user_profile_name)
    except KeyError:
        active_profile_details = get_profile(Config.DEFAULT_PROFILE)

    return jsonify({
        "available": list_profiles(),
        "active_details": active_profile_details
    })


@conversations_bp.route('/conversations', methods=['GET'])
def get_conversations():
    """
    List all conversations for the authenticated user.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    conversations = db.fetch_user_conversations(user_id)
    return jsonify(conversations)


@conversations_bp.route('/conversations', methods=['POST'])
def handle_create_conversation():
    """
    Create a new conversation.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    new_convo = db.create_conversation(user_id)
    return jsonify(new_convo), 201


@conversations_bp.route('/conversations/<conversation_id>', methods=['PUT'])
def handle_rename_conversation(conversation_id):
    """
    Rename a conversation.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    data = request.json
    new_title = data.get('title')
    if not new_title:
        return jsonify({"error": "'title' is required."}), 400
    db.rename_conversation(conversation_id, new_title)
    return jsonify({"status": "success"})


@conversations_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def handle_delete_conversation(conversation_id):
    """
    Delete a conversation.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    db.delete_conversation(conversation_id)
    return jsonify({"status": "success"})


@conversations_bp.route('/conversations/<conversation_id>/history', methods=['GET'])
def get_chat_history(conversation_id):
    """
    Retrieve the chat history for a conversation.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # --- CHANGE: Support for pagination ---
    # The endpoint now checks for 'limit' and 'offset' query parameters
    # to pass to the updated database function.
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    history = db.fetch_chat_history_for_conversation(conversation_id, limit=limit, offset=offset)
    return jsonify(history)


@conversations_bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_chat_history(conversation_id):
    """
    Export a conversation as a JSON file.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # Note: Export still fetches the full history, ignoring pagination.
    history = db.fetch_chat_history_for_conversation(conversation_id, limit=9999, offset=0)
    
    convos = db.fetch_user_conversations(user_id)
    convo_title = next((c['title'] for c in convos if c['id'] == conversation_id), "Untitled")
    filename_title = "".join(x for x in convo_title if x.isalnum() or x in " _-").rstrip()
    export_data = {
        "title": convo_title,
        "conversation_id": conversation_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "history": history
    }
    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment;filename=SAFi-Export-{filename_title}.json'}
    )
