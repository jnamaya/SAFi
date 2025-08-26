import asyncio
import json
from flask import Blueprint, session, jsonify, request, Response
from datetime import datetime, timezone

from ..persistence import database as db
from ..core.orchestrator import SAFi
from ..core.values import get_profile, list_profiles
from ..config import Config

# Conversations API blueprint
# Handles: prompt processing, audit polling, profile switching, basic CRUD for conversations
conversations_bp = Blueprint('conversations', __name__)

# Ensure the SQLite schema exists before handling requests
db.init_db(Config.DATABASE_NAME)

# Track the active profile key used to construct SAFi
_current_profile_name = getattr(Config, "DEFAULT_PROFILE", "secular")


def _load_safi(profile_name: str) -> SAFi:
    """
    Build and return a SAFi orchestrator bound to a specific profile.
    Pulls the profile config, then wires it into SAFi with the global app Config.
    """
    prof = get_profile(profile_name)
    return SAFi(config=Config, value_profile_or_list=prof)


# Single SAFi instance used across requests, recreated when profile changes
saf_system = _load_safi(_current_profile_name)


def get_user_id():
    """
    Return the authenticated user id stored in session, or None if not logged in.
    Accepts either OIDC style 'sub' or a custom 'id'.
    """
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')


@conversations_bp.route('/process_prompt', methods=['POST'])
def process_prompt_endpoint():
    """
    Process a user prompt.
    Steps:
      1) Verify authentication and enforce daily rate limit.
      2) Validate input payload for 'message' and 'conversation_id'.
      3) Record usage for quota tracking.
      4) Call SAFi.process_prompt. That returns the immediate AI answer.
         Conscience and Spirit run in background threads started by SAFi.
      5) Return the immediate result to the client.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # Daily rate limit check
    limit = Config.DAILY_PROMPT_LIMIT
    if limit > 0:
        count = db.get_todays_prompt_count(Config.DATABASE_NAME, user_id)
        if count >= limit:
            return jsonify({
                "error": f"You have reached your daily limit of {limit} messages. Please try again tomorrow."
            }), 429

    data = request.json
    if 'message' not in data or 'conversation_id' not in data:
        return jsonify({"error": "'message' and 'conversation_id' are required."}), 400
    
    # Record usage before processing so the quota is consistent with user experience
    if limit > 0:
        db.record_prompt_usage(Config.DATABASE_NAME, user_id)

    # SAFi handles Intellect and Will immediately, then launches audit threads
    result = asyncio.run(saf_system.process_prompt(data['message'], user_id, data['conversation_id']))
    return jsonify(result)


@conversations_bp.route('/audit_result/<message_id>', methods=['GET'])
def get_audit_result_endpoint(message_id):
    """
    Poll audit status and results for a specific message id.
    Returns:
      - status: 'complete' or current state
      - ledger: conscience evaluations when available
      - spirit_score: numeric coherence score when available
      - spirit_note: enriched note which now includes a memory summary snippet
      - profile and values when complete, so the client can render context
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    result = db.get_audit_result(Config.DATABASE_NAME, message_id)

    if result:
        # Attach profile metadata after completion for consistent UI rendering
        if result.get("status") == "complete":
            prof = getattr(saf_system, 'profile', None) or {}
            result["profile"] = prof.get("name", _current_profile_name)
            result["values"] = prof.get("values", [])
        return jsonify(result)
    else:
        return jsonify({"status": "not_found"}), 404


@conversations_bp.route('/health')
def health_check():
    """
    Lightweight readiness probe that also shows the active profile name.
    """
    prof = getattr(saf_system, 'profile', None) or {}
    return jsonify({"status": "ok", "profile": prof.get("name", _current_profile_name)})


@conversations_bp.route('/profiles', methods=['GET'])
def profiles_list():
    """
    Return current profile details and available profile keys.
    Includes worldview, values, and example prompts for the active profile.
    """
    prof = getattr(saf_system, 'profile', None) or {}
    prompts = prof.get("example_prompts", [])
    return jsonify({
        "current": prof.get("name", _current_profile_name),
        "key": _current_profile_name,
        "available": list_profiles(),
        "worldview": prof.get("worldview"),
        "values": prof.get("values", []),
        "example_prompts": prompts
    })


@conversations_bp.route('/profiles', methods=['POST'])
def profiles_set():
    """
    Switch the active profile.
    Body: { "name": "<profile_key>" }
    Effects:
      - Rebuilds the global SAFi instance with the requested profile.
      - Updates the current profile key.
    """
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip().lower()
    if not name:
        return jsonify({"error": "Provide profile 'name'"}), 400
    try:
        global saf_system, _current_profile_name
        saf_system = _load_safi(name)
        _current_profile_name = name
        prof = getattr(saf_system, 'profile', None) or {}
        return jsonify({
            "status": "ok",
            "current": prof.get("name", name),
            "key": name,
            "values": prof.get("values", []),
        })
    except KeyError as e:
        return jsonify({"error": str(e), "available": list_profiles()}), 400


@conversations_bp.route('/conversations', methods=['GET'])
def get_conversations():
    """
    List all conversations for the authenticated user, newest first.
    Returns [{ id, title }, ...]
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    conversations = db.fetch_user_conversations(Config.DATABASE_NAME, user_id)
    return jsonify(conversations)


@conversations_bp.route('/conversations', methods=['POST'])
def handle_create_conversation():
    """
    Create a new conversation with a default title.
    Returns { id, title } and 201 status.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    new_convo = db.create_conversation(Config.DATABASE_NAME, user_id)
    return jsonify(new_convo), 201


@conversations_bp.route('/conversations/<conversation_id>', methods=['PUT'])
def handle_rename_conversation(conversation_id):
    """
    Rename a conversation.
    Body: { "title": "New Title" }
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    data = request.json
    new_title = data.get('title')
    if not new_title:
        return jsonify({"error": "'title' is required."}), 400
    db.rename_conversation(Config.DATABASE_NAME, conversation_id, new_title)
    return jsonify({"status": "success"})


@conversations_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def handle_delete_conversation(conversation_id):
    """
    Delete a conversation and its history for the authenticated user.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    db.delete_conversation(Config.DATABASE_NAME, conversation_id)
    return jsonify({"status": "success"})


@conversations_bp.route('/conversations/<conversation_id>/history', methods=['GET'])
def get_chat_history(conversation_id):
    """
    Retrieve the ordered chat history for a conversation.
    Each item includes role, content, timestamp, message_id,
    conscience_ledger, spirit_score, and spirit_note.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    history = db.fetch_chat_history_for_conversation(Config.DATABASE_NAME, conversation_id)
    return jsonify(history)


@conversations_bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_chat_history(conversation_id):
    """
    Export the full conversation as a downloadable JSON file.
    Filename is built from the conversation title with safe characters.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    history = db.fetch_chat_history_for_conversation(Config.DATABASE_NAME, conversation_id)
    convos = db.fetch_user_conversations(Config.DATABASE_NAME, user_id)
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
