from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
import logging
import json

policy_api_bp = Blueprint('policy_api', __name__)

def validate_policy_data(data):
    errors = []
    if 'name' in data and not isinstance(data['name'], str):
        errors.append("Name must be a string.")
    if 'will_rules' in data and not isinstance(data['will_rules'], list):
        errors.append("will_rules must be a list.")
    if errors: return False, "; ".join(errors)
    return True, None

@policy_api_bp.route('/policies', methods=['POST'], strict_slashes=False)
def create_policy():
    user = session.get('user')
    user_id = user.get('id') if user else None
    if not user_id: return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("name"): return jsonify({"error": "Name required"}), 400
            
        valid, msg = validate_policy_data(data)
        if not valid: return jsonify({"error": msg}), 400

        pid = db.create_policy(
            name=data.get("name"), 
            worldview=data.get("worldview", ""), 
            will_rules=data.get("will_rules", []), 
            values=data.get("values", []), 
            created_by=user_id
        )
        return jsonify({"ok": True, "policy_id": pid}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies', methods=['GET'], strict_slashes=False)
def list_policies():
    user = session.get('user')
    user_id = user.get('id') if user else None
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    try:
        policies = db.list_policies(user_id=user_id)
        return jsonify({"ok": True, "policies": policies})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['GET'], strict_slashes=False)
def get_policy(policy_id):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        return jsonify({"ok": True, "policy": policy})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['PUT'], strict_slashes=False)
def update_policy(policy_id):
    user = session.get('user')
    user_id = user.get('id') if user else None
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    
    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        if policy.get('created_by') != user_id and not policy.get('is_demo'):
             return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json(force=True, silent=True) or {}
        valid, msg = validate_policy_data(data)
        if not valid: return jsonify({"error": msg}), 400

        db.update_policy(
            policy_id, 
            name=data.get('name'),
            worldview=data.get('worldview'),
            will_rules=data.get('will_rules'),
            values=data.get('values')
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['DELETE'], strict_slashes=False)
def delete_policy(policy_id):
    user = session.get('user')
    user_id = user.get('id') if user else None
    if not user_id: return jsonify({"error": "Unauthorized"}), 401

    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        if policy.get('created_by') != user_id: return jsonify({"error": "Unauthorized"}), 403

        db.delete_policy(policy_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['POST'], strict_slashes=False)
def generate_key(policy_id):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.get_json(force=True, silent=True) or {}
        label = data.get("label", "Default Key")
        raw_key = db.create_api_key(policy_id, label)
        return jsonify({"ok": True, "api_key": raw_key}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['GET'], strict_slashes=False)
def list_keys(policy_id):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        keys = db.get_policy_keys(policy_id)
        return jsonify({"ok": True, "keys": keys})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/ai/generate', methods=['POST'], strict_slashes=False)
async def generate_policy_content_endpoint():
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401
         
    try:
        data = request.get_json(force=True, silent=True) or {}
        gen_type = data.get('type')
        context = data.get('context', 'General Organization')
        agent_name = data.get('name', 'Agent')
        
        from safi_app.core.services.llm_provider import LLMProvider
        from safi_app.config import Config
        
        llm_config = {
            "providers": { "openai": { "type": "openai", "api_key": Config.OPENAI_API_KEY }, "groq": { "type": "openai", "api_key": Config.GROQ_API_KEY, "base_url": "https://api.groq.com/openai/v1" } },
            "routes": { "intellect": { "provider": "groq", "model": Config.INTELLECT_MODEL or "llama-3.1-8b-instant" } }
        }
        provider = LLMProvider(llm_config)
        
        prompt = ""
        sys_prompt = "You are an AI Governance Consultant."
        
        if gen_type == 'worldview':
            prompt = f"Draft an AI Worldview for: '{context}'. Keep it under 150 words. Start with 'You are...'"
        
        elif gen_type == 'values':
             sys_prompt += " Output JSON Array only."
             prompt = f"Generate 3-5 core values with rubrics for: '{context}'. Return JSON Array of objects with 'name', 'description', 'rubric' (object with scoring_guide list)."
        
        elif gen_type == 'rules':
             sys_prompt += " Output JSON List only."
             prompt = f"Generate 5 hard constraints for: '{context}'. Return JSON list of strings."
        
        # --- IMPROVED CONCISE PERSONA PROMPT ---
        elif gen_type == 'persona':
             sys_prompt = "You are a creative writer. Output a single, concise paragraph."
             prompt = (
                 f"Write a short, immersive system prompt for an AI agent named '{agent_name}'. "
                 f"Context: '{context}'.\n"
                 "Requirements:\n"
                 "1. Write in the second person ('You are...').\n"
                 "2. Keep it under 4 sentences.\n"
                 "3. Be direct and concise.\n"
                 "4. NO lists, NO tables, NO markdown formatting.\n"
                 "5. Just the raw text paragraph."
             )
             
        # --- IMPROVED CONCISE STYLE PROMPT ---
        elif gen_type == 'style':
             sys_prompt = "You are a creative writer. Output a single, concise paragraph."
             prompt = (
                 f"Write a brief communication style guide for an AI agent named '{agent_name}'. "
                 f"Context: '{context}'.\n"
                 "Requirements:\n"
                 "1. Describe the tone, vocabulary, and sentence structure.\n"
                 "2. Keep it under 3 sentences.\n"
                 "3. NO lists or bullet points.\n"
                 "Example: 'Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.'"
             )
        else:
             return jsonify({"error": "Invalid type"}), 400

        response_text = await provider._chat_completion(route="intellect", system_prompt=sys_prompt, user_prompt=prompt, temperature=0.7)
        
        # FIX: Robust Cleaning
        cleaned = response_text.strip()
        if "```" in cleaned:
             try:
                cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
             except IndexError:
                # Fallback if markdown format is weird
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        # Specific Handling for JSON types to prevent crashes
        if gen_type in ['values', 'rules']:
             try:
                 # Find list/object start
                 if "[" in cleaned: cleaned = cleaned[cleaned.find("["):]
                 if "]" in cleaned: cleaned = cleaned[:cleaned.rfind("]")+1]
                 
                 # Verify JSON
                 parsed = json.loads(cleaned)
                 return jsonify({"ok": True, "content": parsed}) # Return object, not string
             except json.JSONDecodeError:
                 return jsonify({"ok": False, "error": "AI generated invalid JSON. Please try again.", "raw": response_text}), 422
        
        return jsonify({"ok": True, "content": cleaned})

    except Exception as e:
        current_app.logger.error(f"Gen Error: {e}")
        return jsonify({"error": str(e)}), 500