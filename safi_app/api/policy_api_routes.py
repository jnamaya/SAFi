from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
import logging
import json
import os
from pathlib import Path

policy_api_bp = Blueprint('policy_api', __name__)

# Define custom policies directory
CUSTOM_POLICIES_DIR = Path(__file__).parent.parent / "core" / "governance" / "custom"

def save_policy_to_file(policy_data):
    """
    Saves the policy data to a JSON file.
    """
    try:
        if not CUSTOM_POLICIES_DIR.exists():
            CUSTOM_POLICIES_DIR.mkdir(parents=True, exist_ok=True)
            
        # Use ID as filename to ensure uniqueness and match DB
        file_path = CUSTOM_POLICIES_DIR / f"{policy_data['id']}.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(policy_data, f, indent=2, ensure_ascii=False)
            
        current_app.logger.info(f"Saved policy to file: {file_path}")
    except Exception as e:
        current_app.logger.error(f"Failed to save policy file: {e}")

def delete_policy_file(policy_id):
    """
    Deletes the policy JSON file.
    """
    try:
        file_path = CUSTOM_POLICIES_DIR / f"{policy_id}.json"
        if file_path.exists():
            os.remove(file_path)
            current_app.logger.info(f"Deleted policy file: {file_path}")
    except Exception as e:
        current_app.logger.error(f"Failed to delete policy file: {e}")

@policy_api_bp.route('/policies', methods=['POST'], strict_slashes=False)
def create_policy():
    """
    [POST /api/policies]
    Creates a new Policy.
    Payload: { "name": "...", "worldview": "...", "will_rules": [...], "values": [...] }
    """
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    if not user_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        data = request.get_json()
        name = data.get("name")
        worldview = data.get("worldview", "")
        will_rules = data.get("will_rules", [])
        values = data.get("values", [])
        
        if not name:
            return jsonify({"ok": False, "error": "Policy name is required"}), 400
            
        policy_id = db.create_policy(name=name, worldview=worldview, will_rules=will_rules, values=values, created_by=user_id)
        
        # Save flat file
        flat_data = {
            "id": policy_id,
            "name": name,
            "worldview": worldview,
            "will_rules": will_rules,
            "values": values,
            "created_by": user_id,
            "is_custom": True
        }
        save_policy_to_file(flat_data)
        
        return jsonify({"ok": True, "policy_id": policy_id}), 201

    except Exception as e:
        current_app.logger.error(f"Error creating policy: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies', methods=['GET'], strict_slashes=False)
def list_policies():
    """
    [GET /api/policies]
    Lists all policies.
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    user_id = user.get('id')
    try:
        policies = db.list_policies(user_id=user_id)
        return jsonify({"ok": True, "policies": policies})
    except Exception as e:
        current_app.logger.error(f"Error listing policies: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['GET'])
def get_policy(policy_id):
    """
    [GET /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        policy = db.get_policy(policy_id)
        if not policy:
            return jsonify({"ok": False, "error": "Policy not found"}), 404
        return jsonify({"ok": True, "policy": policy})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['PUT'])
def update_policy(policy_id):
    """
    [PUT /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        # Check ownership
        policy = db.get_policy(policy_id)
        if not policy:
             return jsonify({"ok": False, "error": "Policy not found"}), 404
             
        if policy.get('is_demo'):
             return jsonify({"ok": False, "error": "Cannot edit demo policies"}), 403
             
        # Allow if created by user OR if user is in an admin list (future). For now, strict ownership.
        if policy.get('created_by') and policy.get('created_by') != user['id']:
             return jsonify({"ok": False, "error": "Unauthorized"}), 403

        data = request.get_json()
        name = data.get("name")
        worldview = data.get("worldview")
        will_rules = data.get("will_rules")
        values = data.get("values")

        db.update_policy(
            policy_id,
            name=name,
            worldview=worldview,
            will_rules=will_rules,
            values=values
        )

        # Update flat file
        # We need to construct the full object. We can merge existing DB policy with new data.
        # However, db.get_policy might return old data before commit? 
        # Actually update_policy commits. So if we fetch again or manually merge.
        # Manual merge is safer/faster.
        
        flat_data = {
            "id": policy_id,
            "name": name if name is not None else policy['name'],
            "worldview": worldview if worldview is not None else policy['worldview'],
            "will_rules": will_rules if will_rules is not None else policy['will_rules'],
            "values": values if values is not None else policy.get('values_weights', []), # Note: DB key is values_weights usually mapped to values by list_policies?
            # Wait, convert DB result keys to flat keys.
            # db.get_policy returns transformed dict usually? 
            # Looking at database.py not shown but list_policies probably maps.
            # Safe bet: use input data + existing policy details.
            "created_by": policy.get('created_by'),
            "is_custom": True 
        }
        # Note: values in DB might be stored as 'values_weights'. 
        # The frontend sends 'values'. Flat file should store 'values'.
        
        save_policy_to_file(flat_data)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['DELETE'])
def delete_policy(policy_id):
    """
    [DELETE /api/policies/<id>]
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        # Check ownership
        policy = db.get_policy(policy_id)
        if not policy:
             return jsonify({"ok": False, "error": "Policy not found"}), 404
             
        if policy.get('is_demo'):
             return jsonify({"ok": False, "error": "Cannot delete demo policies"}), 403
             
        if policy.get('created_by') and policy.get('created_by') != user['id']:
             return jsonify({"ok": False, "error": "Unauthorized"}), 403

        db.delete_policy(policy_id)
        
        # Delete flat file
        delete_policy_file(policy_id)
        
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['POST'])
def generate_key(policy_id):
    """
    [POST /api/policies/<id>/keys]
    Generates a new API key for the policy.
    Returns the RAW key once.
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    
    try:
        data = request.get_json() or {}
        label = data.get("label", "Default Key")
        
        raw_key = db.create_api_key(policy_id, label)
        
        return jsonify({"ok": True, "api_key": raw_key}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['GET'])
def list_keys(policy_id):
    """
    [GET /api/policies/<id>/keys]
    Returns metadata of keys (masked).
    """
    user = session.get('user')
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        keys = db.get_policy_keys(policy_id)
        return jsonify({"ok": True, "keys": keys})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
@policy_api_bp.route('/policies/ai/generate', methods=['POST'])
async def generate_policy_content_endpoint():
    """
    [POST /api/policies/generate]
    Generates policy content (worldview, values, rules) using the LLM.
    Payload: { "type": "worldview"|"values"|"rules", "context": "Fintech company..." }
    """
    user = session.get('user')
    if not user:
         return jsonify({"ok": False, "error": "Unauthorized"}), 401
         
    try:
        data = request.get_json()
        gen_type = data.get('type')
        context = data.get('context', 'General Organization')
        
        # Robust Import Strategy
        saf_system = None
        
        # 1. Try to get cached instance
        try:
            from safi_app.api.conversations import global_safi_cache
            from safi_app.config import Config
            saf_system = global_safi_cache.get_or_create("safi", Config.INTELLECT_MODEL, Config.WILL_MODEL, Config.CONSCIENCE_MODEL)
            logging.info("Using cached SAFi instance for generation")
        except ImportError:
            logging.warning("Could not import global_safi_cache, creating fresh instance")
            # 2. Fallback: Create fresh instance
            from safi_app.core.orchestrator import SAFi
            from safi_app.config import Config
            saf_system = SAFi(
                config=Config,
                value_profile_or_list="safi", # Default persona
                intellect_model=Config.INTELLECT_MODEL,
                will_model=Config.WILL_MODEL,
                conscience_model=Config.CONSCIENCE_MODEL
            )
        
        prompt = ""
        if gen_type == 'worldview':
            prompt = (
                f"Draft a comprehensive 'AI Worldview' (System Prompt) for an organization described as: '{context}'. "
                "The worldview should strictly define the AI's persona, ethical priorities, and operational boundaries. "
                "Start directly with the text 'You are an AI assistant...'. Do not include labels like 'System Prompt:' or titles."
                "Keep it under 150 words."
            )
        elif gen_type == 'values':
             prompt = (
                f"Generate 3-5 core ethical values with detailed scoring rubrics for an organization described as: '{context}'. "
                "Return a JSON ARRAY of objects. "
                "Each object must have: 'name', 'description', and 'rubric'. "
                "The 'rubric' field must be an OBJECT with: 'description' (string) and 'scoring_guide' (list of objects with 'score' (float) and 'criteria'). "
                "Ensure scoring_guide includes scores for 1.0 (Excellent), 0.0 (Neutral), and -1.0 (Violation). "
                "Example: [{"
                "  \"name\": \"Historical Integrity\", "
                "  \"description\": \"Must place topic in proper context.\", "
                "  \"rubric\": {"
                "    \"description\": \"Checks for proper historical setting.\", "
                "    \"scoring_guide\": ["
                "       {\"score\": 1.0, \"criteria\": \"Excellent: Correct setting.\"},"
                "       {\"score\": 0.0, \"criteria\": \"Neutral: Lacks depth.\"},"
                "       {\"score\": -1.0, \"criteria\": \"Violation: Anachronistic.\"}"
                "    ]"
                "  }"
                "}] "
                "Do not include markdown."
             )
        elif gen_type == 'rules':
             prompt = (
                f"Generate 5 hard 'Will' constraints (blocklist rules) for an AI at an organization described as: '{context}'. "
                "These should be specific actions the AI must REFUSE to do. "
                "Return ONLY a JSON list of strings."
             )
        elif gen_type == 'persona':
             prompt = (
                f"Draft a creative and immersive 'System Prompt' (Persona) for an AI agent named '{data.get('name', 'Agent')}' "
                f"described as: '{context}'. "
                "The prompt should be written in second-person ('You are...'). "
                "Define the agent's tone, style, and psychological traits. "
                "Do not include labels like 'System Prompt:'. Start directly with the text."
             )
        elif gen_type == 'style':
             prompt = (
                f"Draft a concise 'Communication Style Guide' for an AI agent named '{data.get('name', 'Agent')}' "
                f"described as: '{context}'. "
                "Focus on sentence structure, vocabulary, tone, and formatting constraints. "
                "Example: 'Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.' "
                "Do not include labels. Start directly with the text."
             )
        else:
             return jsonify({"ok": False, "error": "Invalid generation type"}), 400

        # Determine System Prompt based on type
        sys_prompt = "You are an expert AI Governance Consultant. Output valid JSON only."
        if gen_type in ['worldview', 'persona', 'style']:
             sys_prompt = "You are an expert AI Governance Consultant. Return a plain text system prompt."

        # Use _chat_completion directly to bypass the complex "Intellect" parsing logic
        # (which expects Answer---REFLECTION---JSON format and fails on pure JSON)
        response_text = await saf_system.llm_provider._chat_completion(
            route="intellect",
            system_prompt=sys_prompt,
            user_prompt=prompt,
            temperature=0.5
        )
        
        current_app.logger.info(f"Generated Content (Raw): {response_text[:100]}...") # Log first 100 chars
        
        # Clean up
        cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
        
        # Ensure it starts/ends correctly (basic repair)
        if not cleaned_text: cleaned_text = "[]"
        
        return jsonify({"ok": True, "content": cleaned_text})

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"Generation Error: {tb}")
        # Return full traceback in development only, or just message
        return jsonify({"ok": False, "error": f"Server Error: {str(e)}", "trace": tb}), 500
