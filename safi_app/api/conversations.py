import asyncio
import json
from flask import Blueprint, session, jsonify, request, Response
from datetime import datetime, timezone

from ..persistence import database as db
from ..core.orchestrator import SAFi
from ..core.values import get_guardian_ethic_values
from ..config import Config

conversations_bp = Blueprint('conversations', __name__)

db.init_db(Config.DATABASE_NAME)
saf_system = SAFi(config=Config, value_set=get_guardian_ethic_values())

def get_user_id():
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')

@conversations_bp.route('/health')
def health_check():
    return jsonify({"status": "ok"})

@conversations_bp.route('/conversations', methods=['GET'])
def get_conversations():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    conversations = db.fetch_user_conversations(Config.DATABASE_NAME, user_id)
    return jsonify(conversations)

@conversations_bp.route('/conversations', methods=['POST'])
def handle_create_conversation():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    new_convo = db.create_conversation(Config.DATABASE_NAME, user_id)
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
        
    db.rename_conversation(Config.DATABASE_NAME, conversation_id, new_title)
    return jsonify({"status": "success"})

@conversations_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def handle_delete_conversation(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    db.delete_conversation(Config.DATABASE_NAME, conversation_id)
    return jsonify({"status": "success"})

@conversations_bp.route('/conversations/<conversation_id>/history', methods=['GET'])
def get_chat_history(conversation_id):
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    history = db.fetch_chat_history_for_conversation(Config.DATABASE_NAME, conversation_id)
    return jsonify(history)

@conversations_bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_chat_history(conversation_id):
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

@conversations_bp.route('/process_prompt', methods=['POST'])
def process_prompt_endpoint():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
        
    data = request.json
    if 'message' not in data or 'conversation_id' not in data:
        return jsonify({"error": "'message' and 'conversation_id' are required."}), 400
        
    result = asyncio.run(saf_system.process_prompt(data['message'], user_id, data['conversation_id']))
    return jsonify(result)
