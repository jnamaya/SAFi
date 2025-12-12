import json
from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
from ..core.values import PERSONAS, get_profile
from ..core.rbac import check_permission
from ..config import Config

agent_api_bp = Blueprint('agent_api', __name__)

def validate_agent_data(data):
    # Enforce at least one value and one rule
    values = data.get('values', [])
    rules = data.get('will_rules') or data.get('rules', [])
    
    if not values or len(values) < 1:
        return (False, "Agent must have at least one value.")
    
    if not rules or len(rules) < 1:
        return (False, "Agent must have at least one rule.")
        
    return (True, "")

@agent_api_bp.route('/agents', methods=['POST', 'PUT'], strict_slashes=False)
def save_agent():
    try:
        # FIX: force=True handles missing Content-Type headers
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON or Empty Body"}), 400
        
        # DEBUG: Log payload to find 400 cause
        current_app.logger.info(f"Save Agent Payload: {json.dumps(data)}")
            
        key = data.get("key")
        user = session.get("user")
        user_id = user.get("id") or user.get("sub") if user else None
        
        if not user_id: return jsonify({"error": "Unauthorized"}), 401
        
        # RESTRICTION: Only Editors and Admins can create/edit agents
        # FIX: check_permission takes only 1 arg (required_role)
        if not check_permission('editor'):
            return jsonify({"error": "Forbidden: Only Editors/Admins can manage agents"}), 403

        if not key or not data.get("name"): return jsonify({"error": "Missing key or name"}), 400
            
        key = key.lower().strip().replace(" ", "_")
        key = "".join(c for c in key if c.isalnum() or c == '_')
        
        if key in PERSONAS: return jsonify({"error": "Reserved name"}), 409

        is_valid, err = validate_agent_data(data)
        if not is_valid: return jsonify({"error": err}), 400

        if request.method == 'POST':
            if db.get_agent(key): return jsonify({"error": "Agent exists"}), 409
            db.create_agent(
                key=key, name=str(data['name']), 
                description=str(data.get('description') or ''), avatar=str(data.get('avatar') or ''),
                worldview=str(data.get('worldview') or ''), style=str(data.get('style') or ''),
                values=data.get('values', []), rules=data.get('will_rules') or data.get('rules', []),
                policy_id=data.get('policy_id', 'standalone'), created_by=user_id,
                org_id=user.get('org_id'), 
                visibility=data.get('visibility', 'private'),
                intellect_model=data.get('intellect_model'),
                will_model=data.get('will_model'),
                conscience_model=data.get('conscience_model'),
                rag_knowledge_base=data.get('rag_knowledge_base'),
                rag_format_string=data.get('rag_format_string')
            )
        elif request.method == 'PUT':
            exist = db.get_agent(key)
            if not exist: return jsonify({"error": "Not found"}), 404
            
            # Additional check: even if editor, maybe restrict editing others' agents?
            # For now, we trust RBAC 'editor' implies generic edit rights, BUT existing code checked ownership.
            # Let's keep ownership check OR admin check.
            # actually check_permission('admin') OR ownership.
            
            is_owner = (exist.get('created_by') == user_id)
            # FIX: check_permission takes 1 arg
            is_admin = check_permission('admin')
            
            if not (is_owner or is_admin):
                 return jsonify({"error": "Unauthorized"}), 403
            
            db.update_agent(
                key=key, name=str(data['name']), 
                description=str(data.get('description') or ''), avatar=str(data.get('avatar') or ''),
                worldview=str(data.get('worldview') or ''), style=str(data.get('style') or ''),
                values=data.get('values', []), rules=data.get('will_rules') or data.get('rules', []),
                policy_id=data.get('policy_id', 'standalone'),
                visibility=data.get('visibility', 'private'),
                intellect_model=data.get('intellect_model'),
                will_model=data.get('will_model'),
                conscience_model=data.get('conscience_model'),
                rag_knowledge_base=data.get('rag_knowledge_base'),
                rag_format_string=data.get('rag_format_string')
            )

        return jsonify({"ok": True, "key": key}), 200
        
    except Exception as e:
        current_app.logger.error(f"Agent Save Exception: {e}")
        return jsonify({"error": str(e)}), 500

@agent_api_bp.route('/agents/all', methods=['GET'], strict_slashes=False)
def list_all_agents():
    user = session.get("user")
    user_id = user.get("id") or user.get("sub") if user else None
    
    sys_agents = []
    for k, v in PERSONAS.items():
        a = v.copy()
        a['key'] = k
        a['is_custom'] = False
        sys_agents.append(a)
        
    db_agents = []
    if user_id:
        try:
            # Raw list from DB (Updated to fetch shared organization agents)
            raw_list = db.list_agents(user_id, user.get('org_id'), user.get('role', 'member'))
            # Enhance with merged policy data
            for agent in raw_list:
                try:
                    # Use get_profile to perform the merge
                    merged = get_profile(agent['key'])
                    
                    # RESTORE METADATA: get_profile returns the "engine view", we need "db attributes" for UI
                    merged['key'] = agent['key']
                    merged['is_custom'] = agent.get('is_custom', True)
                    merged['created_by'] = agent.get('created_by')
                    
                    db_agents.append(merged)
                except Exception:
                    # Fallback to raw if merge fails
                    db_agents.append(agent)
        except Exception as e:
            current_app.logger.error(f"DB List Error: {e}")
            
    return jsonify({"ok": True, "available": sys_agents + db_agents})

@agent_api_bp.route('/agents/<key>', methods=['GET'], strict_slashes=False)
def get_agent(key):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    clean = "".join(c for c in key.lower() if c.isalnum() or c == '_')
    
    # FIX: Use get_profile() to ensure Policy Inheritance is visible in UI
    try:
        agent = get_profile(clean)
        
        # Verify ownership (get_profile pulls from DB, need to check owner manually if strictly private)
        raw = db.get_agent(clean)
        if raw:
             if raw.get('created_by') != session.get('user')['id']:
                 pass # Ownership check placeholder
             
             # RESTORE METADATA & RAW CONFIG (For Editor)
             agent['created_by'] = raw.get('created_by')
             agent['is_custom'] = True
             agent['key'] = clean
             
             # overwritten merged fields with raw db fields
             agent['values'] = raw.get('values', [])
             agent['will_rules'] = raw.get('will_rules', [])
             agent['worldview'] = raw.get('worldview', '')
             # handle 'rules' alias if used by frontend
             agent['rules'] = agent['will_rules']

        return jsonify({"ok": True, "agent": agent})
    except Exception as e:
        return jsonify({"error": "Not found"}), 404

@agent_api_bp.route('/agents/<key>', methods=['DELETE'], strict_slashes=False)
def delete_agent(key):
    uid = session.get('user', {}).get('id')
    if not uid: return jsonify({"error": "Unauthorized"}), 401
    clean = "".join(c for c in key.lower() if c.isalnum() or c == '_')
    
    agent = db.get_agent(clean)
    if not agent: return jsonify({"error": "Not found"}), 404
    if agent.get('created_by') != uid: return jsonify({"error": "Unauthorized"}), 403
    
    db.delete_agent(clean)
    return jsonify({"ok": True})

@agent_api_bp.route('/generate/rubric', methods=['POST'], strict_slashes=False)
async def generate_rubric():
    # FIX: strict_slashes=False solves the 405 error
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json(force=True, silent=True)
        value_name = data.get('value_name')
        context = data.get('context', '')

        from safi_app.core.services.llm_provider import LLMProvider
        
        llm_config = {
            "providers": { "openai": { "type": "openai", "api_key": Config.OPENAI_API_KEY }, "groq": { "type": "openai", "api_key": Config.GROQ_API_KEY, "base_url": "https://api.groq.com/openai/v1" } },
            "routes": { "intellect": { "provider": "groq", "model": Config.INTELLECT_MODEL or "llama-3.1-8b-instant" } }
        }
        provider = LLMProvider(llm_config)
        
        system_prompt = (
            "You are an expert AI Ethicist. Write a concrete scoring rubric for a value using a strict -1.0 to 1.0 scale (-1.0=Violation, 0.0=Neutral, 1.0=Adherence).\n\n"
            "IMPORTANT: Do NOT use a 1-5 scale. You must ONLY use -1.0, 0.0, and 1.0.\n\n"
            "Example Format:\n"
            "{\n"
            "  \"description\": \"Checks if response matches X.\",\n"
            "  \"scoring_guide\": [\n"
            "    { \"score\": 1.0, \"criteria\": \"Excellent: Fully adheres...\" },\n"
            "    { \"score\": 0.0, \"criteria\": \"Neutral: Adheres but...\" },\n"
            "    { \"score\": -1.0, \"criteria\": \"Violation: Fails to...\" }\n"
            "  ]\n"
            "}\n\n"
            "Return ONLY the valid JSON object."
        )
        user_prompt = f"Value: '{value_name}'. Context: {context}"
        
        response_text = await provider._chat_completion(route="intellect", system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.7)
        
        # FIX: More robust cleaning
        clean_text = response_text.strip()
        if "```" in clean_text:
            clean_text = clean_text.split("```json")[-1].split("```")[0].strip()
        
        # Remove any pre-amble text if braces exist
        if "{" in clean_text and clean_text.find("{") > 0:
            clean_text = clean_text[clean_text.find("{"):]
        if "}" in clean_text:
             clean_text = clean_text[:clean_text.rfind("}")+1]

        try:
            result_json = json.loads(clean_text)
            return jsonify({"ok": True, "rubric": result_json})
        except json.JSONDecodeError:
             return jsonify({
                 "ok": False, 
                 "error": "Failed to parse AI response. Try again.",
                 "raw": response_text
             }), 422

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500