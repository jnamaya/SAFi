from flask import Blueprint, request, jsonify, session, current_app
from ..persistence import database as db
from ..core.rbac import require_role
import logging
import json

import re
from datetime import datetime

from ..core.services.model_routing import detect_provider as _detect_provider, build_providers_config as _build_providers_config
from ..core.rbac import get_current_org_id
from ..core.services.provider_governance import activate_org
# Single source of truth with the governance compiler: what the compiler would
# strip (ordinary value) or raise on (hard gate) at chat time, we reject at
# save time — the author is looking at the form, not at a user's failed chat.
from ..core.faculties.synderesis import _has_usable_rubric

policy_api_bp = Blueprint('policy_api', __name__)


# --- Integration endpoint, resolved per deployment -------------------------
# The policy wizard's closing "getting started" panel prints an endpoint URL
# and pastes it into a copy-pasteable Teams bot. That URL was hardcoded to the
# public demo host, so every self-hoster — and every localhost developer — was
# handed a snippet that pointed their bot at somebody else's SAFi, authenticated
# with a key that instance has never heard of. It would fail as a 401 from a
# domain the reader never typed.
#
# WEB_BASE_URL is the right source: it is what the OAuth callback and CORS
# origins already derive from, so if it is wrong the deployment is already
# broken in more visible ways. Resolved server-side rather than from
# window.location.origin because the mobile shell serves from capacitor://
# localhost, which is not an address any bot can post to.

def _bot_endpoint_url():
    from ..config import Config
    return f"{Config.WEB_BASE_URL.rstrip('/')}/api/bot/process_prompt"


def _is_publicly_reachable():
    """False when the endpoint is a loopback address.

    Teams, Slack and every other webhook caller reach the endpoint from the
    internet. On a laptop the URL is correct and still unusable, and saying so
    is the difference between a five-minute fix and an afternoon of debugging
    Azure. Not a security control — purely a truthful hint in the guide.
    """
    from ..config import Config
    host = Config.WEB_BASE_URL.lower()
    return not any(h in host for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))


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
        else:
            for v in data['values']:
                if not isinstance(v, dict):
                    errors.append("Each value must be an object.")
                    break
                vname = v.get('name') or v.get('value') or '<unnamed>'
                if not _has_usable_rubric(v):
                    if v.get('hard_gate'):
                        errors.append(
                            f"Non-negotiable standard '{vname}' has no scoring criteria. "
                            "Agents under this policy would block every response. "
                            "Fill in its rubric before saving."
                        )
                    else:
                        errors.append(
                            f"Standard '{vname}' has no scoring criteria, so it can never "
                            "be scored. Fill in its rubric before saving."
                        )
                try:
                    weight = float(v.get('weight') or 0)
                except (TypeError, ValueError):
                    weight = 0
                if not v.get('hard_gate') and weight <= 0:
                    errors.append(
                        f"Standard '{vname}' has an importance of 0, so it never affects "
                        "scoring. Give it an importance or mark it non-negotiable."
                    )

    # will_rules may be either a legacy list of strings or a structured dict
    # ({structural_requirements, early_prompt_blacklist, allowed_tools, rules}).
    if 'will_rules' in data and not isinstance(data['will_rules'], (list, dict)):
        errors.append("will_rules must be a list or dict.")

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

        org_id = user.get('org_id')

        # Idempotency guard: a policy with this name already exists in the same
        # scope (org, or creator for personal). This stops a double-submit /
        # network retry from creating identical duplicate policies.
        existing = db.find_policy_by_name(data.get("name"), org_id=org_id, created_by=user_id)
        if existing:
            return jsonify({
                "error": f"A policy named '{data.get('name')}' already exists.",
                "code": "DUPLICATE_NAME",
                "policy_id": existing['id'],
            }), 409

        # --- Readable ID Generation ---
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

        policy_config = {
            "business_unit":      data.get("business_unit", ""),
            "scope_statement":    data.get("scope_statement", ""),
            "ethical_memory":     data.get("ethical_memory", 0.90),
            "alignment_threshold": data.get("alignment_threshold", 0.5),
        }
        pid = db.create_policy(
            name=data.get("name"),
            worldview=data.get("worldview", ""),
            will_rules=data.get("will_rules", []),
            values=data.get("values", []),
            created_by=user_id,
            org_id=user.get('org_id'),
            policy_id=readable_id,
            policy_config=policy_config
        )
        
        # Policies carry their own version history, so the log records the
        # governance surface — how many standards, how many block — rather than
        # duplicating content the versions table already holds.
        _vals = data.get("values") or []
        db.append_compliance_log(user.get('org_id'), 'policy_created', f"user:{user_id}", {
            "policy_id": pid, "name": data.get("name"),
            "standards": len(_vals),
            "blocking": sum(1 for v in _vals if isinstance(v, dict) and v.get('hard_gate')),
        })

        # Auto-generate credentials for immediate use
        default_key = db.create_api_key(pid, "Initial Key")
        
        return jsonify({
            "ok": True,
            "policy_id": pid,
            "credentials": {
                "policy_id": pid,
                "api_key": default_key,
                "endpoint_url": _bot_endpoint_url(),
                "is_public_url": _is_publicly_reachable(),
            }
        }), 201
    except Exception as e:
        current_app.logger.error(f"create_policy error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@policy_api_bp.route('/policies', methods=['GET'], strict_slashes=False)
def list_policies():
    user = session.get('user')
    user_id = user.get('id') if user else None
    org_id = user.get('org_id') if user else None
    
    if not user_id: return jsonify({"error": "Unauthorized"}), 401
    try:
        policies = db.list_policies(user_id=user_id, org_id=org_id)
        return jsonify({"ok": True, "policies": policies})
    except Exception as e:
        current_app.logger.error(f"list_policies error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

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

        policy_config = {
            "business_unit":      data.get("business_unit", ""),
            "scope_statement":    data.get("scope_statement", ""),
            "ethical_memory":     data.get("ethical_memory", 0.90),
            "alignment_threshold": data.get("alignment_threshold", 0.5),
        }
        db.update_policy(
            policy_id,
            name=data.get('name'),
            worldview=data.get('worldview'),
            will_rules=data.get('will_rules'),
            values=data.get('values'),
            policy_config=policy_config
        )
        
        _vals = data.get('values') or []
        _after = db.get_policy(policy_id) or {}
        db.append_compliance_log(get_current_org_id(), 'policy_updated',
                                 f"user:{session.get('user', {}).get('id')}", {
            "policy_id": policy_id, "name": data.get('name'),
            "version": _after.get('version'),
            "standards": len(_vals),
            "blocking": sum(1 for v in _vals if isinstance(v, dict) and v.get('hard_gate')),
        })

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
                "api_key": api_key,
                "endpoint_url": _bot_endpoint_url(),
                "is_public_url": _is_publicly_reachable(),
            }
        })
    except Exception as e:
        current_app.logger.error(f"update_policy error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@policy_api_bp.route('/policies/<policy_id>/versions', methods=['GET'], strict_slashes=False)
def list_policy_version_history(policy_id):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        if not db.get_policy(policy_id): return jsonify({"error": "Not found"}), 404
        return jsonify({"ok": True, "versions": db.list_policy_versions(policy_id)})
    except Exception as e:
        current_app.logger.error(f"list_policy_versions error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@policy_api_bp.route('/policies/<policy_id>/versions/<int:version>', methods=['GET'], strict_slashes=False)
def get_policy_version_detail(policy_id, version):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        v = db.get_policy_version(policy_id, version)
        if not v: return jsonify({"error": "Version not found"}), 404
        return jsonify({"ok": True, "version": v})
    except Exception as e:
        current_app.logger.error(f"get_policy_version error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


@policy_api_bp.route('/policies/<policy_id>/versions/<int:version>/restore', methods=['POST'], strict_slashes=False)
@require_role('editor')
def restore_policy_version_endpoint(policy_id, version):
    user = session.get('user')
    user_id = user.get('id') if user else None
    try:
        if not db.get_policy(policy_id): return jsonify({"error": "Not found"}), 404
        ok = db.restore_policy_version(policy_id, version, restored_by=user_id)
        if not ok: return jsonify({"error": "Version not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"restore_policy_version error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500


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
                "api_key": new_key,
                "endpoint_url": _bot_endpoint_url(),
                "is_public_url": _is_publicly_reachable(),
            }
        })
    except Exception as e:
        current_app.logger.error(f"rotate_key error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@policy_api_bp.route('/policies/<policy_id>', methods=['DELETE'], strict_slashes=False)
@require_role('editor')
def delete_policy(policy_id):
    try:
        policy = db.get_policy(policy_id)
        if not policy: return jsonify({"error": "Not found"}), 404
        # Ownership check removed in favor of strict Admin RBAC

        db.delete_policy(policy_id)
        db.append_compliance_log(get_current_org_id(), 'policy_deleted',
                                 f"user:{session.get('user', {}).get('id')}",
                                 {"policy_id": policy_id, "name": policy.get('name')})
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"delete_policy error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

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
        current_app.logger.error(f"generate_key error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@policy_api_bp.route('/policies/<policy_id>/keys', methods=['GET'], strict_slashes=False)
def list_keys(policy_id):
    if not session.get('user'): return jsonify({"error": "Unauthorized"}), 401
    try:
        keys = db.get_policy_keys(policy_id)
        return jsonify({"ok": True, "keys": keys})
    except Exception as e:
        current_app.logger.error(f"list_keys error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

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
        
        # Most wizard tasks are short drafting jobs the light model handles well.
        # The ones that WRITE GOVERNANCE are not: a rubric per standard is
        # structured output the light model degenerates on. Measured on a real
        # policy, gpt-oss-20b returned a bare "{}" — two characters — where the
        # Conscience model returned a full analysis. A degenerate "{}" is the
        # dangerous shape because it PARSES, so it reaches the author as an
        # empty finding rather than a failure.
        _DOCUMENT_TASKS = ('compile_rules', 'ai_standards')
        model = Config.CONSCIENCE_MODEL if gen_type in _DOCUMENT_TASKS else Config.BACKEND_MODEL
        detected_provider = _detect_provider(model)
        
        llm_config = {
            "providers": _build_providers_config(Config),
            "routes": { "intellect": { "provider": detected_provider, "model": model } }
        }
        activate_org(get_current_org_id())  # provider allow-list applies to wizard calls too
        provider = LLMProvider(llm_config)
        
        prompt = ""
        sys_prompt = "You are an AI Governance Consultant."
        # Drafting types (agent, style, worldview) want some latitude; the
        # document types are extraction, where latitude means inventing clauses
        # that are not in the source. Set per branch.
        gen_temperature = 0.7
        gen_max_tokens = 4096

        if gen_type == 'worldview':
            prompt = (
                f"Draft a concise Purpose statement for an AI policy governing: '{context}'. "
                "In under 150 words of plain prose, cover: what this unit exists to do, who its "
                "agents serve, the outcomes they own, the priorities that win when goals conflict, "
                "and where their authority ends. Write it as the operating frame an agent reasons "
                "from. Be specific and concrete; avoid marketing language. "
                "Output flowing paragraphs only: no headings, no section labels, no bullet points, "
                "no bold or any other markdown."
            )
        
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
                 "4. -1.0 = Violation/Negative. The -1.0 criteria MUST describe something "
                 "the response actively DOES (an act of commission — e.g. 'reveals "
                 "confidential data', 'promises a specific outcome'), never a mere "
                 "omission like 'fails to mention X'. Policies govern many unrelated "
                 "requests; omission-based penalties punish responses where the value "
                 "simply wasn't in play.\n"
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
                 f"Generate 5 candidate prohibitions for an AI agent. Context: '{context}'.\n\n"
                 "IMPORTANT: These are DRAFT TEXT. They do not block anything by themselves — "
                 "the author compiles them into hard-gate standards with rubrics (the 'compile_rules' "
                 "step), and it is those compiled standards the Will enforces. Write each one so it "
                 "can be checked against a draft response, because that is what it becomes.\n"
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
        
        # Compiles plain-language prohibitions into hard-gate values the engine
        # actually enforces. Prose rules reach no enforcement path on their own:
        # WillGate is deterministic and reads only structural_requirements,
        # hard-gate values in the Conscience ledger, and tool constraints. A
        # written rule therefore governs nothing until it becomes a value with a
        # rubric, which is what this produces.
        elif gen_type == 'compile_rules':
             raw_rules = data.get('rules') or []
             if not isinstance(raw_rules, list):
                 return jsonify({"error": "rules must be an array"}), 400
             rules = [str(r).strip() for r in raw_rules if str(r).strip()]
             if not rules:
                 return jsonify({"error": "No rules to compile."}), 400
             if len(rules) > 25:
                 return jsonify({"error": "Too many rules to compile at once (max 25)."}), 400

             # Strict-JSON output, so no sampling latitude: at 0.7 this branch
             # returned malformed JSON often enough to fail a real import.
             gen_temperature = 0.0
             # Each gate carries a full rubric, and the definitions block makes
             # them longer. At the 4096 default the reply is truncated mid-object,
             # which surfaces as "invalid JSON" and hides the real cause.
             gen_max_tokens = 8192

             # Definitions from the source document, when this is pass 2 of the
             # document flow. A policy that enumerates what a term covers ("Personal
             # Information means name, signature, passport number, ...") turns a
             # rubric the Conscience has to interpret into one it can check. Most
             # documents do not provide this; wasting it when they do is the
             # difference between a usable gate and an inconsistent one.
             definitions_block = ""
             raw_defs = data.get('definitions') or []
             if isinstance(raw_defs, list) and raw_defs:
                 lines = []
                 for d in raw_defs[:15]:
                     if not isinstance(d, dict):
                         continue
                     term = str(d.get("term") or "").strip()
                     enum = str(d.get("enumeration") or "").strip()
                     if term and enum:
                         lines.append(f"- {term}: {enum}")
                 if lines:
                     definitions_block = (
                         "\nDEFINITIONS FROM THE SOURCE POLICY — when a rule uses one of these "
                         "terms, write the -1.0 criteria against the ENUMERATION, not the term. "
                         "A rubric saying 'discloses Personal Information' forces the auditor to "
                         "guess; one naming the actual categories does not.\n"
                         + "\n".join(lines) + "\n"
                     )

             sys_prompt += " Output a single JSON object only."
             rules_block = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))
             prompt = (
                 f"Context: '{context}'.\n\n"
                 "Below are plain-language rules an author wrote for an AI agent. Convert each one "
                 "into a HARD GATE: a named standard with a rubric that an auditor model can score "
                 "against the agent's draft response.\n\n"
                 f"RULES:\n{rules_block}\n"
                 f"{definitions_block}\n"
                 "CRITICAL — a rule that requires the response to INCLUDE something cannot become a\n"
                 "standard here. Its only failure mode is an omission, and an omission-based standard\n"
                 "blocks every response that simply did not raise the topic. Put those in\n"
                 "'unconvertible' with the reason 'This mandates including something, so it must be\n"
                 "enforced as a required disclaimer rather than a scored standard.' Examples:\n"
                 '- "Disclose that AI was used" -> unconvertible (a required disclaimer)\n'
                 '- "Always cite your sources" -> unconvertible (a required disclaimer)\n'
                 "Only rules forbidding an ACT can become standards.\n\n"
                 "CRITICAL — the subject must be the AGENT'S RESPONSE.\n"
                 "A rule whose real subject is a person or a business process cannot be scored "
                 "against a response, and must NOT be invented into a gate. Put those in "
                 "'unconvertible' with a short reason instead. Examples that are NOT convertible:\n"
                 '- "Employees must complete AI training annually" (subject is a person)\n'
                 '- "All AI output must be reviewed by a manager before publication" (subject is a workflow)\n'
                 "Converting these produces a gate that scores the wrong party and blocks correct answers.\n\n"
                 "RUBRIC RULES:\n"
                 "1. BINARY scale only: 1.0 and -1.0. Do NOT emit 0.0 — a hard gate has no neutral state.\n"
                 "2. The -1.0 criteria MUST describe an act of COMMISSION — something the response "
                 "actively DOES (e.g. 'discloses another employee's compensation'), never an omission "
                 "like 'fails to mention'. A gate is evaluated on every request, including ones where "
                 "the topic never arises; an omission-based gate would block those.\n"
                 "3. The 1.0 criteria must be satisfiable by a response that simply never touches the "
                 "topic, so word it as the absence of the prohibited act.\n\n"
                 "Return a single JSON object with exactly two keys:\n"
                 '- "gates": array of objects, each with "name" (short noun phrase, 2-4 words), '
                 '"description" (one sentence), "source_rule" (the original rule text, verbatim), and '
                 '"rubric" (object with "description" and "scoring_guide").\n'
                 '- "unconvertible": array of objects, each with "rule" (verbatim) and "reason".\n\n'
                 "Example gate:\n"
                 '{ "name": "Compensation Confidentiality",\n'
                 '  "description": "The response must never disclose another employee\'s pay.",\n'
                 '  "source_rule": "Never disclose employee compensation",\n'
                 '  "rubric": { "description": "Checks whether the response reveals compensation data.",\n'
                 '    "scoring_guide": [\n'
                 '      { "score": 1.0, "criteria": "Does not disclose any individual compensation figure." },\n'
                 '      { "score": -1.0, "criteria": "States or estimates a specific person\'s pay." } ] } }'
             )

        # Candidate org-wide AI standards from a short description, not from a
        # document. Importing a policy PDF was tried and withdrawn: classifying
        # 28k characters produced a surface where a wrong answer and an empty one
        # look identical, and the output lands in the tier that governs every
        # agent. This is the small-input, small-output shape instead — the same
        # one the charter's value generator has been reliable with.
        elif gen_type == 'ai_standards':
             sys_prompt += " Output JSON Array only."
             prompt = (
                 f"Suggest 4-6 organization-wide AI standards for: '{context}'.\n\n"
                 "These bind EVERY AI agent in the organization, so keep them broad and "
                 "uncontroversial — the rules almost any organization would want. Leave "
                 "anything specific to one team out; that belongs to that team's policy.\n\n"
                 "Typical subjects: disclosing personal or sensitive data, confidential "
                 "company information, giving professional advice the agent is not qualified "
                 "to give, asserting facts it cannot support.\n\n"
                 "Each is scored by an auditor model against the agent's response on EVERY "
                 "request, including requests where the subject never comes up. So:\n"
                 "- The -1.0 criteria MUST describe something the response actively DID "
                 "(an act of commission, e.g. 'states a specific person's bank account "
                 "number'). NEVER an omission such as 'fails to mention' or 'does not "
                 "include' — that would flag every unrelated answer.\n"
                 "- The 1.0 criteria must be satisfiable by a response that never touches "
                 "the subject at all.\n"
                 "- Do NOT suggest standards that require the response to INCLUDE something "
                 "(a disclaimer, a citation). Those are enforced as automatic checks, not here.\n\n"
                 "Return a JSON array. Each object: 'name' (2-4 words), 'description' (one "
                 "sentence), and 'rubric' with 'description' and a 'scoring_guide' of exactly "
                 "two entries, scores 1.0 and -1.0, each with 'criteria'."
             )
             gen_temperature = 0.3
             gen_max_tokens = 4096

        elif gen_type == 'scope':
            sys_prompt = "You are an AI Governance Consultant. Output a single sentence only — no quotes, no formatting."
            prompt = (
                f"Write a single-sentence scope statement for an AI agent serving this context: '{context}'.\n\n"
                "Format: '[topic area] only — [specific subtopics]. No [excluded areas].'\n\n"
                "Examples:\n"
                "- STEM education only — math, physics, chemistry, biology, engineering. No homework completion.\n"
                "- HR employee questions only — benefits, PTO, onboarding, workplace policies. No legal or medical advice.\n"
                "- Financial education and market analysis only. No personalized investment advice.\n\n"
                "Return ONLY the sentence. No quotes, no preamble, no markdown."
            )

        elif gen_type == 'guardrails':
            sys_prompt += " Output JSON List only."
            prompt = (
                f"Generate 4-6 behavioral guardrails for an AI agent. Context: '{context}'.\n\n"
                "Guardrails are softer behavioral boundaries — not hard rejections, but guidance on how the agent should handle edge cases.\n"
                "Unlike hard rules, guardrails allow the agent to use judgment. Use phrases like:\n"
                "'Always recommend...', 'Avoid...', 'When uncertain...', 'Prefer...'\n\n"
                "Examples:\n"
                '- "Always recommend consulting a licensed professional for complex legal or financial decisions."\n'
                '- "Avoid speculative language when discussing outcomes or predictions."\n'
                '- "When uncertain about a fact, acknowledge the uncertainty rather than guessing."\n'
                '- "Prefer plain language over technical jargon unless the user demonstrates expertise."\n\n'
                "Return a JSON array of guardrail strings."
            )

        # --- IMPROVED CONCISE AGENT PROMPT ---
        elif gen_type == 'agent':
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

        response_text = await provider._chat_completion(
            route="intellect",
            system_prompt=sys_prompt,
            user_prompt=prompt,
            temperature=gen_temperature,
            max_tokens=gen_max_tokens,
        )
        
        # FIX: Robust Cleaning
        cleaned = response_text.strip()
        if "```" in cleaned:
             try:
                cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
             except IndexError:
                # Fallback if markdown format is weird
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        if gen_type == 'compile_rules':
            try:
                if "{" in cleaned: cleaned = cleaned[cleaned.find("{"):]
                if "}" in cleaned: cleaned = cleaned[:cleaned.rfind("}")+1]
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                # Log enough to tell truncation from malformation. A bare 422
                # sent an operator hunting through a 15-page document for a
                # clause that was never the problem.
                current_app.logger.warning(
                    "compile_rules returned unparseable JSON (%d chars, %d rules): %s | tail=%r",
                    len(cleaned), len(rules), e, cleaned[-200:],
                )
                truncated = not cleaned.rstrip().endswith("}")
                return jsonify({"ok": False, "error": (
                    "The model's reply was cut off before it finished. Select fewer standards "
                    "and convert them in batches." if truncated else
                    "The model returned malformed JSON. Try again."
                )}), 422

            # hard_gate and weight are set here, never taken from the model: a
            # gate the Conscience cannot score fails closed on EVERY request
            # (synderesis._validate_value_rubrics raises, and the agent stops
            # loading), so a malformed rubric must be dropped rather than saved.
            gates = []
            dropped = []
            for g in (parsed.get("gates") or []):
                if not isinstance(g, dict):
                    continue
                name = str(g.get("name") or "").strip()
                rubric = g.get("rubric")
                guide = rubric.get("scoring_guide") if isinstance(rubric, dict) else None
                if not name or not isinstance(guide, list) or not guide:
                    dropped.append({
                        "rule": str(g.get("source_rule") or g.get("name") or "<unnamed>"),
                        "reason": "The generated standard had no usable rubric and would have blocked every request.",
                    })
                    continue

                # Refuse omission-based failure criteria, whatever the prompt was
                # told. A standard whose -1.0 reads "does not include X" fires on
                # every response that never raised the topic — which is how a
                # required disclosure blocked every answer an agent gave. The
                # obligation is real; it belongs to the disclaimer check, which
                # APPENDS the missing text instead of refusing the turn.
                fail = next((c for c in guide if isinstance(c, dict) and float(c.get("score", 0)) < 0), None)
                fail_text = str((fail or {}).get("criteria") or (fail or {}).get("descriptor") or "").lower()
                if any(p in fail_text for p in (
                    "does not include", "does not contain", "does not disclose", "does not state",
                    "fails to include", "fails to mention", "fails to disclose", "fails to state",
                    "omits", "without disclosing", "lacks a", "no statement",
                )):
                    dropped.append({
                        "rule": str(g.get("source_rule") or name),
                        "reason": ("This requires the response to include something, so it can only be "
                                   "broken by omission — as a standard it would block every answer that "
                                   "never raised the topic. Set it as a required disclaimer instead."),
                    })
                    continue
                gates.append({
                    "name": name,
                    "description": str(g.get("description") or "").strip(),
                    "source_rule": str(g.get("source_rule") or "").strip(),
                    "hard_gate": True,
                    "weight": 0.0,
                    "rubric": {
                        "description": str(rubric.get("description") or "").strip(),
                        "scoring_guide": guide,
                    },
                })

            unconvertible = [
                u for u in (parsed.get("unconvertible") or []) if isinstance(u, dict)
            ] + dropped
            return jsonify({"ok": True, "content": {"gates": gates, "unconvertible": unconvertible}})

        # Specific Handling for JSON types to prevent crashes
        if gen_type in ['values', 'rules', 'ai_standards']:
             try:
                 # Find list/object start
                 if "[" in cleaned: cleaned = cleaned[cleaned.find("["):]
                 if "]" in cleaned: cleaned = cleaned[:cleaned.rfind("]")+1]
                 
                 # Verify JSON
                 parsed = json.loads(cleaned)
                 return jsonify({"ok": True, "content": parsed}) # Return object, not string
             except json.JSONDecodeError:
                 return jsonify({"ok": False, "error": "AI generated invalid JSON. Please try again."}), 422

        return jsonify({"ok": True, "content": cleaned})

    except Exception as e:
        current_app.logger.error(f"Gen Error: {e}")
        return jsonify({"error": "An internal error occurred."}), 500
