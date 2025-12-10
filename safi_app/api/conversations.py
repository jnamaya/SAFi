import asyncio
import json
import time
import threading
import hashlib
from flask import Blueprint, session, jsonify, request, Response, current_app
from datetime import datetime, timezone

from ..persistence import database as db
from ..core.orchestrator import SAFi
from ..core.values import get_profile, list_profiles
from ..config import Config

conversations_bp = Blueprint('conversations', __name__)

# --- CACHING INFRASTRUCTURE ---

class SafiInstanceCache:
    """
    Thread-safe cache for SAFi instances to prevent reloading 
    heavy resources (Vector DB, Embeddings) on every request.
    """
    def __init__(self, ttl_seconds=600): # Default 10 minute TTL
        self._cache = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def _generate_key(self, profile_name, intellect, will, conscience):
        """
        Creates a unique hash for a specific configuration.
        If two users use the exact same profile and models, they share an instance.
        """
        raw_key = f"{profile_name}|{intellect}|{will}|{conscience}"
        return hashlib.md5(raw_key.encode()).hexdigest()

    def get_or_create(self, profile_name, intellect_model, will_model, conscience_model):
        key = self._generate_key(profile_name, intellect_model, will_model, conscience_model)
        now = time.time()

        with self._lock:
            # 1. Cleanup expired items first (simple lazy expiration)
            keys_to_delete = [k for k, v in self._cache.items() if now - v['last_used'] > self._ttl]
            for k in keys_to_delete:
                del self._cache[k]

            # 2. Return existing if found
            if key in self._cache:
                entry = self._cache[key]
                entry['last_used'] = now
                return entry['instance']

            # 3. Create new if missing
            try:
                prof = get_profile(profile_name)
                instance = SAFi(
                    config=Config,
                    value_profile_or_list=prof,
                    intellect_model=intellect_model,
                    will_model=will_model,
                    conscience_model=conscience_model
                )
                
                self._cache[key] = {
                    'instance': instance,
                    'created_at': now,
                    'last_used': now
                }
                return instance
            except Exception as e:
                # Don't cache failed initializations
                raise e

# Initialize the global cache
global_safi_cache = SafiInstanceCache(ttl_seconds=600)



def get_user_id():
    """Retrieves the authenticated user's ID from the session."""
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')

def get_user_profile_name():
    """Retrieves the user's currently active profile name from the session."""
    user = session.get('user', {})
    return user.get('active_profile') or Config.DEFAULT_PROFILE


# --- NEW: Dedicated Endpoint for Teams Bot ---
@conversations_bp.route('/bot/process_prompt', methods=['POST'])
async def bot_process_prompt_endpoint():
    """
    Dedicated endpoint for the Microsoft Teams Bot.
    Uses API Key authentication.
    """
    # 1. Security: Check API Secret Header (Fixed hardcoding)
    api_key = request.headers.get("X-API-KEY")
    if api_key != Config.BOT_API_SECRET: 
        return jsonify({"error": "Unauthorized Bot Access"}), 401

    data = request.json
    user_id = data.get('user_id')
    user_prompt = data.get('message') 
    conversation_id = data.get('conversation_id')
    persona_key = data.get('persona', 'safi') 

    if not all([user_id, user_prompt, conversation_id]):
        return jsonify({"error": "Missing required fields"}), 400

    # 2. Ensure User Exists in DB (Just-in-Time Registration)
    try:
        user_details = db.get_user_details(user_id)
        if not user_details:
            db.upsert_user({
                "sub": user_id,
                "id": user_id,
                "name": f"Teams User {user_id[-4:]}",
                "email": f"{user_id}@safinstitute.org",
                "picture": ""
            })
            db.update_user_profile(user_id, persona_key)
        
        # 3. Ensure Conversation Exists
        if hasattr(db, 'upsert_external_conversation'):
            db.upsert_external_conversation(conversation_id, user_id, title="Teams Chat")
        else:
            current_app.logger.warning("db.upsert_external_conversation missing. Bot memory might fail if conversation is new.")

        # --- MODEL SELECTION LOGIC ---
        selected_intellect = Config.INTELLECT_MODEL
        selected_will = Config.WILL_MODEL
        selected_conscience = Config.CONSCIENCE_MODEL

        if persona_key == "accion_admin":
            selected_intellect = "claude-haiku-4-5-20251001" 
        
        # 4. Get Safi Instance (Cached)
        saf_system = global_safi_cache.get_or_create(
            persona_key, 
            selected_intellect, 
            selected_will, 
            selected_conscience
        )

        # 5. Process Prompt
        result = await saf_system.process_prompt(
            user_prompt, 
            user_id, 
            conversation_id,
            user_name="Colleague"
        )
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Bot Processing Error: {str(e)}")
        return jsonify({"error": str(e), "finalOutput": "I encountered an internal error processing your request."}), 500


@conversations_bp.route('/tts_audio', methods=['POST'])
def tts_audio_endpoint():
    """
    Handles POST request to generate TTS audio.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    try:
        data = request.get_json()
        text_to_speak = data.get('text')
        
        if not text_to_speak:
            return jsonify({"error": "Missing 'text' in request body."}), 400
        
        user_details = db.get_user_details(user_id)
        if not user_details:
             return jsonify({"error": "User not found."}), 404

        user_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
        intellect_model = user_details.get('intellect_model') or Config.INTELLECT_MODEL
        will_model = user_details.get('will_model') or Config.WILL_MODEL
        conscience_model = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
        
        saf_system = global_safi_cache.get_or_create(
            user_profile_name, 
            intellect_model, 
            will_model, 
            conscience_model
        )

        audio_content = saf_system.generate_speech_audio(text_to_speak)
        
        if audio_content is None:
            return jsonify({"error": "TTS generation failed on the backend."}), 500

        response = Response(audio_content, mimetype='audio/mpeg')
        response.headers['Content-Disposition'] = 'attachment; filename=speech.mp3'
        return response

    except Exception as e:
        current_app.logger.error(f"Error processing TTS request: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500


@conversations_bp.route('/public/process_prompt', methods=['POST'])
async def public_process_prompt_endpoint():
    """
    Process a user prompt from the public WordPress chatbot.
    """
    data = request.json
    if 'message' not in data or 'conversation_id' not in data:
        return jsonify({"error": "'message' and 'conversation_id' are required."}), 400

    anonymous_user_id = data['conversation_id']
    
    if not db.get_user_details(anonymous_user_id):
        db.upsert_user({
            "sub": anonymous_user_id,
            "name": "Public User",
            "email": f"{anonymous_user_id}@public.chat",
            "picture": "" 
        })
    
    # NOTE: Public chats are less secure by design, but we still ensure consistency
    new_convo = db.create_conversation(anonymous_user_id)

    saf_system = global_safi_cache.get_or_create(
        "safi", 
        Config.INTELLECT_MODEL, 
        Config.WILL_MODEL, 
        Config.CONSCIENCE_MODEL
    )
    
    result = await saf_system.process_prompt(data['message'], anonymous_user_id, new_convo['id'], user_name="Guest")
    return jsonify(result)


@conversations_bp.route('/process_prompt', methods=['POST'])
async def process_prompt_endpoint():
    """
    Process a user prompt using their selected profile AND selected models.
    IDOR PROTECTION ADDED: Verifies ownership before processing.
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
    
    conversation_id = data['conversation_id']

    # --- SECURITY: Verify Ownership ---
    # --- SECURITY: Verify Ownership (and Auto-Create for External Bots) ---
    if not db.ensure_conversation_access(user_id, conversation_id):
        return jsonify({"error": "You do not have permission to access this conversation."}), 403
    # ----------------------------------
    # ----------------------------------

    if limit > 0:
        db.record_prompt_usage(user_id)
    
    # 1. Resolve User Configuration
    user_details = db.get_user_details(user_id)
    if not user_details:
         return jsonify({"error": "User not found."}), 404

    user_profile_name = user_details.get('active_profile') or Config.DEFAULT_PROFILE
    intellect_model = user_details.get('intellect_model') or Config.INTELLECT_MODEL
    will_model = user_details.get('will_model') or Config.WILL_MODEL
    conscience_model = user_details.get('conscience_model') or Config.CONSCIENCE_MODEL
    
    full_name = user_details.get('name', 'User')
    user_name = full_name.split(' ')[0] if full_name else 'User'

    # 2. Get Cached Instance
    saf_system = global_safi_cache.get_or_create(
        user_profile_name, 
        intellect_model, 
        will_model, 
        conscience_model
    )
    
    # 3. Process
    result = await saf_system.process_prompt(
        data['message'], 
        user_id, 
        conversation_id,
        user_name=user_name
    )
    return jsonify(result)


@conversations_bp.route('/audit_result/<message_id>', methods=['GET'])
def get_audit_result_endpoint(message_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # Note: message_id is unique, but ideally we should verify the user owns the conversation 
    # that this message belongs to. 
    # Since we lack a direct mapping from message_id -> user_id without a join, 
    # we rely on the UUID complexity of message_id for now, but a strict implementation would join here too.
    
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
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    return jsonify({"models": Config.AVAILABLE_MODELS})

@conversations_bp.route('/profiles', methods=['GET'])
def profiles_list():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    user_profile_name = get_user_profile_name()
    
    all_profiles = []
    # FIX: Pass user_id to filter private agents
    for p in list_profiles(owner_id=user_id):
        try:
            profile_details = get_profile(p['key'])
            profile_details['key'] = p['key'] 
            # Pass ownership info to frontend
            profile_details['is_custom'] = p.get('is_custom', False)
            profile_details['created_by'] = p.get('created_by')
            all_profiles.append(profile_details)
        except KeyError:
            continue 
            
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
    
    conversations_with_timestamps = []
    for convo in conversations:
        # Pass user_id for security
        history = db.fetch_chat_history_for_conversation(convo['id'], limit=1, offset=0, user_id=user_id) 
        
        full_history = db.fetch_chat_history_for_conversation(convo['id'], limit=9999, offset=0, user_id=user_id)
        
        if full_history:
            last_message = full_history[-1]
            convo['last_updated'] = last_message.get('timestamp')
        else:
            convo['last_updated'] = convo.get('created_at')

        conversations_with_timestamps.append(convo)
    
    return jsonify(conversations_with_timestamps)


@conversations_bp.route('/conversations', methods=['POST'])
def handle_create_conversation():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    new_convo = db.create_conversation(user_id)
    
    if 'created_at' in new_convo:
        new_convo['last_updated'] = new_convo['created_at']
    else:
        new_convo['last_updated'] = datetime.now(timezone.utc).isoformat()

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
    
    # IDOR check is implicit in the DB function now
    db.rename_conversation(conversation_id, new_title, user_id=user_id)
    return jsonify({"status": "success"})

@conversations_bp.route('/conversations/<conversation_id>/pin', methods=['PATCH'])
def handle_pin_conversation(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    data = request.json
    is_pinned = data.get('is_pinned')
    if is_pinned is None or not isinstance(is_pinned, bool):
        return jsonify({"error": "'is_pinned' boolean field is required."}), 400
    
    # IDOR check is implicit in the DB function now
    db.toggle_conversation_pin(conversation_id, is_pinned, user_id=user_id)
    return jsonify({"status": "success", "is_pinned": is_pinned})

@conversations_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def handle_delete_conversation(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # IDOR check is implicit in the DB function now
    db.delete_conversation(conversation_id, user_id=user_id)
    return jsonify({"status": "success"})

@conversations_bp.route('/conversations/<conversation_id>/history', methods=['GET'])
def get_chat_history(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    # SECURITY: Pass user_id to enforce ownership check
    history = db.fetch_chat_history_for_conversation(conversation_id, limit=limit, offset=offset, user_id=user_id)
    
    return jsonify(history)

@conversations_bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_chat_history(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    # SECURITY: Pass user_id
    history = db.fetch_chat_history_for_conversation(conversation_id, limit=9999, offset=0, user_id=user_id)
    
    # We also check user_convos to get the title, which implicitly checks ownership if logic is consistent
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