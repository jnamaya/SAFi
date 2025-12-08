import json
import os
from flask import Blueprint, request, jsonify, g, session, current_app
from pathlib import Path
from ..core.values import CUSTOM_PERSONAS_DIR, get_profile
from ..core.orchestrator import SAFi  # Need access to LLM provider for generation
from ..config import Config

agent_api_bp = Blueprint('agent_api', __name__)

@agent_api_bp.route('/agents', methods=['POST'], strict_slashes=False)
def save_agent():
    """
    [POST /api/agents]
    Saves a new or updated custom agent JSON.
    Payload: { "key": "my_agent", "name": "...", ... }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON or Empty Body"}), 400
            
        key = data.get("key")
        
        # Security: Get ID (Assuming auth middleware or session)
        user = session.get("user")
        # FIX: Check 'id' first (used by auth.py), then fallback to 'sub'
        user_id = user.get("id") or user.get("sub") if user else None
        
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        # Validation
        if not key or not data.get("name"):
            return jsonify({"error": "Missing key or name"}), 400
            
        # Sanitize key
        key = key.lower().strip().replace(" ", "_")
        key = "".join(c for c in key if c.isalnum() or c == '_')
        
        if not key:
             return jsonify({"ok": False, "error": "Invalid key provided."}), 400

        # Construct path
        if not CUSTOM_PERSONAS_DIR.exists():
            CUSTOM_PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
            
        file_path = CUSTOM_PERSONAS_DIR / f"{key}.json"
        
        # IDOR / Ownership Check
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                creator = existing.get("created_by")
                # If it has a creator, and it's not you => Forbid
                if creator and creator != user_id:
                     return jsonify({"error": "You cannot edit an agent created by someone else."}), 403
        
        # Inject Ownership
        data["created_by"] = user_id
        
        # Normalize 'values': Ensure 'value' key exists (frontend sends 'name')
        if "values" in data and isinstance(data["values"], list):
            for v in data["values"]:
                if "name" in v and "value" not in v:
                    v["value"] = v["name"]
        
        # Save JSON
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        current_app.logger.info(f"User {user_id} saved custom agent: {key}")
        
        return jsonify({"ok": True, "key": key}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error saving agent: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@agent_api_bp.route('/agents/<key>', methods=['GET'])
def get_agent(key):
    """
    [GET /api/agents/<key>]
    Retrieves the JSON for a specific agent.
    """
    user_id = session.get('user', {}).get('id')
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    
    try:
        # Re-use our logic from get_profile, but we want the RAW json
        # We can just read the file directly for editing purposes
        clean_key = key.lower().strip().replace(" ", "_")
        clean_key = "".join(c for c in clean_key if c.isalnum() or c == '_')
        
        file_path = CUSTOM_PERSONAS_DIR / f"{clean_key}.json"
        
        if not file_path.exists():
             return jsonify({"ok": False, "error": "Agent not found"}), 404
             
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return jsonify({"ok": True, "agent": data})
            
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@agent_api_bp.route('/agents/<key>', methods=['DELETE'])
def delete_agent(key):
    """
    [DELETE /api/agents/<key>]
    Deletes a custom agent if the requesting user created it.
    """
    user = session.get('user')
    user_id = user.get('id') or user.get('sub') if user else None
    
    if not user_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        # Sanitize key
        clean_key = key.lower().strip().replace(" ", "_")
        clean_key = "".join(c for c in clean_key if c.isalnum() or c == '_')
        
        file_path = CUSTOM_PERSONAS_DIR / f"{clean_key}.json"

        if not file_path.exists():
            return jsonify({"ok": False, "error": "Agent not found"}), 404

        # IDOR / Ownership Check
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                creator = data.get("created_by")
                
                # If there is a creator and it matches the current user, allow delete.
                # If there is NO creator, assume it's a system/legacy file and forbid delete via API.
                if not creator:
                     return jsonify({"ok": False, "error": "Cannot delete system or protected agents."}), 403
                
                if creator != user_id:
                     return jsonify({"ok": False, "error": "You do not have permission to delete this agent."}), 403
                     
            except json.JSONDecodeError:
                # If file is corrupt, but exists in custom dir, we might want to allow delete?
                # For safety, fail.
                return jsonify({"ok": False, "error": "Agent file is corrupted."}), 500

        # Perform Deletion
        os.remove(file_path)
        current_app.logger.info(f"User {user_id} deleted custom agent: {clean_key}")
        
        return jsonify({"ok": True})

    except Exception as e:
        current_app.logger.error(f"Error deleting agent: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@agent_api_bp.route('/generate/rubric', methods=['POST'], strict_slashes=False)
async def generate_rubric():
    """
    [POST /api/generate/rubric]
    Uses the Intellect Engine to generate a scoring rubric for a value.
    Payload: { "value_name": "Honesty", "context": "Optional context about the agent" }
    """
    # FIX: Use .get('id') to match auth.py session structure
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    if not user_id:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
        
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "Invalid JSON"}), 400

        value_name = data.get('value_name')
        context = data.get('context', '')
        
        if not value_name:
            return jsonify({"ok": False, "error": "Missing value_name"}), 400

        # We need an LLM client. We can instantiate a temp LLMProvider or re-use one if available.
        # Ideally, we should grab the app's SAFi instance, but that's not easily accessible in a route.
        # We will create a fresh LLMProvider.
        from ..core.services.llm_provider import LLMProvider
        
        # Reconstruct minimal config
        # NOTE: In a real app we'd use 'current_app.safi_instance' 
        # but simpler here to just init the provider with API keys from Config
        
        llm_config = {
            "providers": {
                "openai": { "type": "openai", "api_key": Config.OPENAI_API_KEY },
                "groq": { "type": "openai", "api_key": Config.GROQ_API_KEY, "base_url": "https://api.groq.com/openai/v1" }
            },
            "routes": {
                 # Use a fast model for generation
                "intellect": { "provider": "groq", "model": Config.INTELLECT_MODEL or "llama-3.1-8b-instant" }
            }
        }
        
        provider = LLMProvider(llm_config)
        
        system_prompt = (
            "You are an expert AI Ethicist. Your job is to write a concrete scoring rubric for a specific value.\n"
            "Return ONLY a JSON object with this structure:\n"
            "{\n"
            '  "description": "A single sentence definition of the value.",\n'
            '  "scoring_guide": [\n'
            '     { "score": -1.0, "criteria": "What constitutes a clear violation." },\n'
            '     { "score": 0.0, "criteria": "What constitutes a neutral or partial adherence." },\n'
            '     { "score": 1.0, "criteria": "What constitutes perfect adherence." }\n'
            '  ]\n'
            "}"
        )
        
        user_prompt = f"Write a rubric for the value: '{value_name}'. Context for this agent: {context}"
        
        response_text = await provider._chat_completion(
            route="intellect",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7
        )
        
        # Clean up code blocks if model output them
        clean_text = response_text.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(clean_text)
        
        return jsonify({"ok": True, "rubric": result_json})

    except Exception as e:
        current_app.logger.error(f"Rubric gen error: {e}")
        return jsonify({"ok": False, "error": f"Failed to generate: {e}"}), 500