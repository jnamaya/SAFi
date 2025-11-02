import asyncio
import json
from flask import Blueprint, session, jsonify, request, Response
from datetime import datetime, timezone

from ..persistence import database as db
from ..core.orchestrator import SAFi
from ..core.values import get_profile, list_profiles
from ..config import Config

conversations_bp = Blueprint('conversations', __name__)

safi_instances = {}

def _load_safi(profile_name: str) -> SAFi:
    """
    Loads or creates a cached SAFi instance for a given profile.
    NOTE: This is now only used for non-user-specific instances,
    like the public anonymous endpoint.
    """
    if profile_name in safi_instances:
        return safi_instances[profile_name]

    prof = get_profile(profile_name)
    # When creating a cached instance, it always uses the default models from Config.
    instance = SAFi(
        config=Config, 
        value_profile_or_list=prof,
        intellect_model=Config.INTELLECT_MODEL,
        will_model=Config.WILL_MODEL,
        conscience_model=Config.CONSCIENCE_MODEL
    )
    
    safi_instances[profile_name] = instance
    return instance

def get_user_id():
    """
    Retrieves the authenticated user's ID from the session.
    """
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')

def get_user_profile_name():
    """
    Retrieves the user's currently active profile name from the session.
    Falls back to the system default profile.
    """
    user = session.get('user', {})
    return user.get('active_profile') or Config.DEFAULT_PROFILE

@conversations_bp.route('/public/process_prompt', methods=['POST'])
def public_process_prompt_endpoint():
    """
    Process a user prompt from the public WordPress chatbot.
    This endpoint is anonymous and does not require authentication.
    It uses the cached _load_safi() function.
    """
    data = request.json
    if 'message' not in data or 'conversation_id' not in data:
        return jsonify({"error": "'message' and 'conversation_id' are required."}), 400

    anonymous_user_id = data['conversation_id']
    
    # Ensure a user record exists for the anonymous session
    if not db.get_user_details(anonymous_user_id):
        placeholder_user_info = {
            "sub": anonymous_user_id,
            "name": "Public User",
            "email": f"{anonymous_user_id}@public.chat",
            "picture": "" 
        }
        db.upsert_user(placeholder_user_info)
    
    # Create a new conversation for each public prompt
    # The orchestrator must have a valid conversation ID to save message history.
    new_convo = db.create_conversation(anonymous_user_id)

    # Set the public persona to "safi"
    public_profile_name = "safi"
    saf_system = _load_safi(public_profile_name) # Uses the cached instance
    
    # Use the ID from the newly created conversation record.
    result = asyncio.run(saf_system.process_prompt(data['message'], anonymous_user_id, new_convo['id']))
    return jsonify(result)


@conversations_bp.route('/process_prompt', methods=['POST'])
def process_prompt_endpoint():
    """
    Process a user prompt using their selected profile AND selected models.
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
    
    # Create a user-specific SAFi instance instead of using the cache.
    # 1. Get user's full details
    user_details = db.get_user_details(user_id)
    if not user_details:
         return jsonify({"error": "User not found."}), 404

    # 2. Get their profile
    user_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
    prof = get_profile(user_profile_name)

    # 3. Get their model preferences, falling back to Config defaults
    intellect_model = user_details.get('intellect_model') or Config.INTELLECT_MODEL
    will_model = user_details.get('will_model') or Config.WILL_MODEL
    conscience_model = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
    
    # 4. Create a new SAFi instance with these specific settings
    saf_system = SAFi(
        config=Config,
        value_profile_or_list=prof,
        intellect_model=intellect_model,
        will_model=will_model,
        conscience_model=conscience_model
    )
    
    result = asyncio.run(saf_system.process_prompt(data['message'], user_id, data['conversation_id']))
    return jsonify(result)


@conversations_bp.route('/audit_result/<message_id>', methods=['GET'])
def get_audit_result_endpoint(message_id):
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
    return jsonify({"status": "ok"})

@conversations_bp.route('/models', methods=['GET'])
def get_available_models():
    """
    Returns the list of available AI models from the config.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    return jsonify({"models": Config.AVAILABLE_MODELS})

@conversations_bp.route('/profiles', methods=['GET'])
def profiles_list():
    """
    Returns a list of all available profile configurations and the key
    of the user's currently active profile.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    user_profile_name = get_user_profile_name()
    
    all_profiles = []
    for p in list_profiles():
        try:
            # We add the 'key' to the profile dict for the frontend
            profile_details = get_profile(p['key'])
            profile_details['key'] = p['key'] 
            all_profiles.append(profile_details)
        except KeyError:
            continue # Skip any broken profiles
            
    sorted_profiles = sorted(all_profiles, key=lambda x: x['name'])
    
    return jsonify({
        "available": sorted_profiles, 
        "active_profile_key": user_profile_name
    })


@conversations_bp.route('/conversations', methods=['GET'])
def get_conversations():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    conversations = db.fetch_user_conversations(user_id)
    
    # --- MODIFICATION: Add 'last_updated' timestamp to each conversation ---
    # This loops through each conversation and finds the timestamp of the
    # most recent message. This is what the frontend needs for sorting.
    conversations_with_timestamps = []
    for convo in conversations:
        # Fetch all history for the conversation
        # Note: This is an N+1 query and can be slow if a user has
        # many conversations. A better long-term fix is to modify
        # `db.fetch_user_conversations` to do this in one SQL query.
        history = db.fetch_chat_history_for_conversation(convo['id'], limit=9999, offset=0)
        
        if history:
            # Assuming history is sorted oldest-to-newest, get the last message
            last_message = history[-1]
            convo['last_updated'] = last_message.get('timestamp')
        else:
            # If no messages, fall back to the conversation's creation time
            # (Assuming the convo object has 'created_at' from the DB)
            convo['last_updated'] = convo.get('created_at')

        conversations_with_timestamps.append(convo)
    
    return jsonify(conversations_with_timestamps)
    # --- END MODIFICATION ---

@conversations_bp.route('/conversations', methods=['POST'])
def handle_create_conversation():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    new_convo = db.create_conversation(user_id)
    
    # --- MODIFICATION: Ensure new convo has 'last_updated' field ---
    # When a new convo is created, it has no messages.
    # We'll set 'last_updated' to its 'created_at' time.
    # This assumes `db.create_conversation` returns an object
    # that includes a 'created_at' timestamp.
    if 'created_at' in new_convo:
        new_convo['last_updated'] = new_convo['created_at']
    else:
        # As a fallback, set it to the current time.
        new_convo['last_updated'] = datetime.now(timezone.utc).isoformat()
    # --- END MODIFICATION ---

    return jsonify(new_convo), 201

@conversations_bp.route('/conversations/<conversation_id>', methods=['PUT'])
def handle_rename_conversation(conversation_id):
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
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    db.delete_conversation(conversation_id)
    return jsonify({"status": "success"})

@conversations_bp.route('/conversations/<conversation_id>/history', methods=['GET'])
def get_chat_history(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    history = db.fetch_chat_history_for_conversation(conversation_id, limit=limit, offset=offset)
    return jsonify(history)

@conversations_bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_chat_history(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
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
