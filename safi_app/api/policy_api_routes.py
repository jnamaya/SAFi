from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
from ..core.rbac import require_role
import logging
import json

import re
from datetime import datetime

policy_api_bp = Blueprint('policy_api', __name__)

def _detect_provider(model_name: str) -> str:
    """Auto-detect provider from model name."""
    if not model_name: return "groq"
    model_lower = model_name.lower()
    if model_lower.startswith("gpt-") or model_lower.startswith("o1-"): return "openai"
    if model_lower.startswith("claude-"): return "anthropic"
    if model_lower.startswith("gemini-"): return "gemini"
    if model_lower.startswith("deepseek-"): return "deepseek"
    if model_lower.startswith("mistral-") or model_lower.startswith("codestral-") or model_lower.startswith("open-mi"): return "mistral"
    return "groq"

def validate_policy_data(data):
    errors = []
    if 'name' in data and not isinstance(data['name'], str):
        errors.append("Name must be a string.")
    
    # Enforce Values
    if 'values' in data:
        if not isinstance(data['values'], list):
            errors.append("Values must be a list.")
        elif len(data['values']) < 1:
            errors.append("At least one Core Value is required.")
    
    # Enforce Rules
    if 'will_rules' in data:
        if not isinstance(data['will_rules'], list):
            errors.append("will_rules must be a list.")
        elif len(data['will_rules']) < 1:
            errors.append("At least one Will Rule (hard constraint) is required.")

    if errors: return False, "; ".join(errors)
    return True, None

@policy_api_bp.route('/policies', methods=['POST'], strict_slashes=False)
@require_role('editor')
def create_policy():
    user = session.get('user')
    user_id = user.get('id') if user else None
    if not user_id: return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("name"): return jsonify({"error": "Name required"}), 400
            
        valid, msg = validate_policy_data(data)
        if not valid: return jsonify({"error": msg}), 400

        # --- Readable ID Generation ---
        org_id = user.get('org_id')
        org_prefix = "p" # Default personal
        
        if org_id:
            org = db.get_organization(org_id)
            if org:
                # Prioritize verified domain, else normalized name
                if org.get('domain_verified') and org.get('domain_to_verify'):
                    org_prefix = org['domain_to_verify'].replace('.', '_').lower()
                elif org.get('name'):
                    # Without verified domain, use first 12 chars of org name + Random Token to prevent collisions
                    import secrets
                    safe_name = re.sub(r'[^a-z0-9]', '', org['name'].lower())[:12]
                    suffix = secrets.token_hex(2) # 4 chars
                    org_prefix = f"{safe_name}_{suffix}"
        
        slug = re.sub(r'[^a-z0-9]', '_', data.get("name", "").lower()).strip('_')
        readable_id = f"{org_prefix}_{slug}"

        pid = db.create_policy(
            name=data.get("name"), 
            worldview=data.get("worldview", ""), 
            will_rules=data.get("will_rules", []), 
            values=data.get("values", []), 
            created_by=user_id,
            org_id=user.get('org_id'), # FIX: Link to Org
            policy_id=readable_id
        )
        
        # Auto-generate credentials for immediate use
        default_key = db.create_api_key(pid, "Initial Key")
        
        return jsonify({
            "ok": True, 
            "policy_id": pid,
            "credentials": {
                "policy_id": pid,
                "api_key": default_key
            }
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies', methods=['GET'], strict_slashes=False)
def list_policies():
    user = session.get('user')
    user_id = user.get('id') if user else None
    org_id = user.get('org_id') if user else None
    
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    try:
        # DEBUG LOGGING
        print(f"DEBUG: list_policies called for User: {user_id}, Org: {org_id}")
        policies = db.list_policies(user_id=user_id, org_id=org_id)
        print(f"DEBUG: Found {len(policies)} policies.")
        
        return jsonify({
            "ok": True, 
            "policies": policies,
            "debug_info": {
                "user_id": user_id,
                "org_id": org_id,
                "count": len(policies),
                "db_host": current_app.config.get('DB_HOST') # Check if it's hitting the right DB
            }
        })
    except Exception as e:
        print(f"DEBUG: list_policies ERROR: {e}")
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
@require_role('editor')
def update_policy(policy_id):
    user = session.get('user')
    user_id = user.get('id') if user else None
    
    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        
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
        
        # Return existing (or new) credentials for UI convenience
        keys = db.get_policy_keys(policy_id)
        # Fix: handle keys that only have hashes (return masked)
        if keys:
            api_key = keys[0].get('key', 'sk_************************') 
        else:
            api_key = db.create_api_key(policy_id, "Default Key")
        
        return jsonify({
            "ok": True,
            "credentials": {
                "policy_id": policy_id,
                "api_key": api_key
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/rotate_key', methods=['POST'], strict_slashes=False)
@require_role('editor')
def rotate_key(policy_id):
    try:
        # Verify function existence (Guard against stale code in future)
        if not hasattr(db, 'delete_policy_keys'):
            return jsonify({"error": "FATAL: database.delete_policy_keys missing"}), 500

        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        
        # Revoke old keys
        db.delete_policy_keys(policy_id)
        
        # Generate new one
        label = f"Rotated {datetime.now().strftime('%Y-%m-%d')}"
        new_key = db.create_api_key(policy_id, label)
        
        return jsonify({
            "ok": True,
            "credentials": {
                "policy_id": policy_id,
                "api_key": new_key
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['DELETE'], strict_slashes=False)
@require_role('editor')
def delete_policy(policy_id):
    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        # Ownership check removed in favor of strict Admin RBAC

        db.delete_policy(policy_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['POST'], strict_slashes=False)
@require_role('editor')
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
        
        # Hardcoded: Use cheap fast GPT-OSS 120B model for wizard tasks
        model = "openai/gpt-oss-120b"
        detected_provider = _detect_provider(model)
        
        llm_config = {
            "providers": {
                "openai": { "type": "openai", "api_key": Config.OPENAI_API_KEY },
                "groq": { "type": "openai", "api_key": Config.GROQ_API_KEY, "base_url": "https://api.groq.com/openai/v1" },
                "anthropic": { "type": "anthropic", "api_key": Config.ANTHROPIC_API_KEY },
                "gemini": { "type": "gemini", "api_key": Config.GEMINI_API_KEY },
                "deepseek": { "type": "openai", "api_key": getattr(Config, 'DEEPSEEK_API_KEY', ''), "base_url": "https://api.deepseek.com" },
                "mistral": { "type": "openai", "api_key": getattr(Config, 'MISTRAL_API_KEY', ''), "base_url": "https://api.mistral.ai/v1" }
            },
            "routes": { "intellect": { "provider": detected_provider, "model": model } }
        }
        provider = LLMProvider(llm_config)
        
        prompt = ""
        sys_prompt = "You are an AI Governance Consultant."
        
        if gen_type == 'worldview':
            prompt = f"Draft an AI Worldview for: '{context}'. Keep it under 150 words. Start with 'You are...'"
        
        elif gen_type == 'values':
             sys_prompt += " Output JSON Array only."
             prompt = (
                 f"Generate 3-5 core values with rubrics for: '{context}'.\n"
                 "Return a JSON Array of objects. Each object must have:\n"
                 "- 'name': value name\n"
                 "- 'weight': float (e.g. 0.2)\n"
                 "- 'description': short description\n"
                 "- 'rubric': object containing 'description' and 'scoring_guide'.\n\n"
                 "CRITICAL RUBRIC RULES:\n"
                 "1. Use a 3-point scale ONLY: 1.0, 0.0, and -1.0.\n"
                 "2. 1.0 = Full Compliance/Positive.\n"
                 "3. 0.0 = Neutral/Not Applicable.\n"
                 "4. -1.0 = Violation/Negative.\n"
                 "5. DO NOT produce a 1-5 scale.\n\n"
                 "Example Rubric Format:\n"
                 "\"rubric\": {\n"
                 "  \"description\": \"...\",\n"
                 "  \"scoring_guide\": [\n"
                 "    { \"score\": 1.0, \"criteria\": \"Explicitly demonstrates validation...\" },\n"
                 "    { \"score\": 0.0, \"criteria\": \"Neither valid nor invalid...\" },\n"
                 "    { \"score\": -1.0, \"criteria\": \"Violates validation rules...\" }\n"
                 "  ]\n"
                 "}"
             )
        
        elif gen_type == 'rules':
             sys_prompt += " Output JSON List only."
             prompt = (
                 f"Generate 5 Will Rules for an AI agent. Context: '{context}'.\n\n"
                 "IMPORTANT: These rules are for a GATEKEEPING MODEL (the 'Will') that EVALUATES responses.\n"
                 "The Will gate reads the Intellect's draft response and checks if it violates any rules.\n"
                 "Rules should describe what makes a response UNACCEPTABLE (grounds for rejection).\n\n"
                 "RULES FORMAT:\n"
                 "- Write rules as evaluation criteria (what to check for)\n"
                 "- Start with: 'The response must not...', 'Reject if...', 'Block any response that...'\n"
                 "- Focus on what makes a response FAIL the check\n\n"
                 "CORRECT examples (evaluation criteria):\n"
                 '- "The response must not contain personally identifiable information about donors."\n'
                 '- "Reject if the response provides specific medical diagnoses or treatment plans."\n'
                 '- "Block any response that includes instructions for illegal activities."\n'
                 '- "The response must not make claims without citing provided source documents."\n'
                 '- "Reject if the response engages in political campaigning or endorses candidates."\n\n'
                 "WRONG examples (these are instructions, not evaluation criteria):\n"
                 '- "You must prioritize the mission..." <- WRONG, this is an instruction\n'
                 '- "Always provide accurate information..." <- WRONG, too vague for evaluation\n\n'
                 "Return a JSON array of exactly 5 rule strings. Each rule describes grounds for rejection."
             )
        
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
