from typing import Dict, Any, List, Optional
import copy
import json
import os
from pathlib import Path

# 1. Import Governance (Updated for Contoso structure)
# 1. Import Governance (Updated for Contoso structure)
from .governance.contoso.policy import CONTOSO_GLOBAL_POLICY
from ..persistence import database as db

# 2. Import Personas (Updated for Contoso Admin)
from .personas.contoso_admin import THE_CONTOSO_ADMIN_PERSONA
from .personas.fiduciary import THE_FIDUCIARY_PERSONA
from .personas.health_navigator import THE_HEALTH_NAVIGATOR_PERSONA
from .personas.bible_scholar import THE_BIBLE_SCHOLAR_PERSONA
from .personas.safi_steward import THE_SAFI_STEWARD_PERSONA
from .personas.socratic_tutor import THE_SOCRATIC_TUTOR_PERSONA
from .personas.vault import THE_VAULT_PERSONA
from .personas.negotiator import THE_NEGOTIATOR_PERSONA

# 3. Define the Persona Registry
PERSONAS: Dict[str, Dict[str, Any]] = {
    # The Contoso Persona (Governed)
    "contoso_admin": THE_CONTOSO_ADMIN_PERSONA,
    
    # The Independent Personas (Unchanged)
    "fiduciary": THE_FIDUCIARY_PERSONA,
    "health_navigator": THE_HEALTH_NAVIGATOR_PERSONA,
    "bible_scholar": THE_BIBLE_SCHOLAR_PERSONA,
    "safi": THE_SAFI_STEWARD_PERSONA,
    "tutor": THE_SOCRATIC_TUTOR_PERSONA,
    "vault": THE_VAULT_PERSONA,
    "negotiator": THE_NEGOTIATOR_PERSONA,
}

# 4. Define Governance Mapping
# Maps the specific persona key to the global policy
GOVERNANCE_MAP: Dict[str, Dict[str, Any]] = {
    "contoso_admin": CONTOSO_GLOBAL_POLICY,
}

# 5. Define the Compiler Logic
def assemble_agent(base_profile: Dict[str, Any], governance: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies the Governance Layer to a base persona.
    """
    final_profile = copy.deepcopy(base_profile)
    
    # A. Merge Worldview (Gov on top)
    final_profile["worldview"] = (
        f"--- Organizational Policy ---\n"
        f"{governance['global_worldview']}\n"
        f"--- SPECIFIC ROLE ---\n"
        f"{final_profile.get('worldview', '')}"
    )

    # B. Merge Will Rules (Gov First)
    final_profile["will_rules"] = (
        governance.get("global_will_rules", []) + 
        final_profile.get("will_rules", [])
    )

    # C. Merge Values & Math (Enforce 40/60 Split)
    global_values = copy.deepcopy(governance.get("global_values", []))
    agent_values = final_profile.get("values", [])
    
    # Determine Targets
    if not agent_values:
        # If agent has no values, Global takes 100%
        g_target = 1.0
        a_target = 0.0
    elif not global_values:
         # If no global policy, Agent takes 100%
         g_target = 0.0
         a_target = 1.0
    else:
        # Standard Split
        g_target = 0.40
        a_target = 0.60
    
    # 1. Normalize Global Values
    g_sum = sum(v.get("weight", 0) for v in global_values)
    if g_sum > 0:
        factor = g_target / g_sum
        for v in global_values:
            v["weight"] = round(v.get("weight", 0) * factor, 3)
    
    # 2. Normalize Agent Values
    a_sum = sum(v.get("weight", 0) for v in agent_values)
    if a_sum > 0:
        factor = a_target / a_sum
        for v in agent_values:
            v["weight"] = round(v.get("weight", 0) * factor, 3)
    
    # Combine
    final_profile["values"] = global_values + agent_values
    
    return final_profile

# 6. JSON Loading Helpers

CUSTOM_PERSONAS_DIR = Path(__file__).parent / "personas" / "custom"

def load_custom_persona(name: str) -> Optional[Dict[str, Any]]:
    """
    Attempts to load a persona from a JSON file in core/personas/custom/.
    """
    try:
        if not CUSTOM_PERSONAS_DIR.exists():
            return None
            
        # Support both 'my_agent' and 'my_agent.json' inputs
        clean_name = name.replace(".json", "")
        file_path = CUSTOM_PERSONAS_DIR / f"{clean_name}.json"
        
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure the key matches the filename
                data["key"] = clean_name
                
                # FIX for SpiritIntegrator compatibility:
                # SpiritIntegrator expects keys 'value' and 'weight', but Frontend sends 'name' and 'weight'.
                # We map 'name' -> 'value' if missing.
                if "values" in data and isinstance(data["values"], list):
                    for v in data["values"]:
                        if "name" in v and "value" not in v:
                            v["value"] = v["name"]
                
                return data
    except Exception as e:
        print(f"Error loading custom persona {name}: {e}")
        return None
    return None

def list_custom_personas(owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scans the custom directory and returns a list of minimal persona dicts.
    Filters by owner_id if provided.
    """
    results = []
    if not CUSTOM_PERSONAS_DIR.exists():
        return results

    for file_path in CUSTOM_PERSONAS_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # VISIBILITY LOGIC:
                # 1. If 'created_by' is missing, it's public (Legacy or System).
                # 2. If 'created_by' matches owner_id, it's mine -> Show.
                # 3. If 'created_by' exists and mismatch -> Hide.
                
                creator = data.get("created_by")
                
                if creator and creator != owner_id:
                    continue # Skip private agents of others

                results.append({
                    "key": file_path.stem,
                    "name": data.get("name", file_path.stem),
                    "description": data.get("description", ""),
                    "is_custom": True,
                    "created_by": creator
                })
        except Exception:
            continue
    return results

# 7. Public Accessors
def list_profiles(owner_id: Optional[str] = None) -> List[Dict[str, str]]:
    # Built-in Personas (Always visible)
    builtins = [{"key": key, "name": persona["name"], "is_custom": False, "created_by": None} for key, persona in PERSONAS.items()]
    
    # Custom Personas (Filtered by owner)
    customs = list_custom_personas(owner_id)
    
    # Merge and sort
    all_profiles = builtins + customs
    return sorted(all_profiles, key=lambda x: x["name"])

def get_profile(name: str) -> Dict[str, Any]:
    """
    Retrieves a persona. 
    Checks for a linked Policy ID or the GOVERNANCE_MAP.
    """
    key = (name or "").lower().strip()
    
    # 1. Check Built-ins
    if key in PERSONAS:
        raw_persona = PERSONAS[key]
    else:
        # 2. Check Customs
        raw_persona = load_custom_persona(key)
        if not raw_persona:
            # Fallback checks or error
            available_keys = [p['key'] for p in list_profiles()]
            # Soft error or default to avoid crashes if user deleted a file
            raise KeyError(f"Unknown persona '{name}'.")

    # --- CONDITIONAL GOVERNANCE LOGIC ---
    
    # A. Dynamic Policy from DB (New Way)
    policy_id = raw_persona.get("policy_id")
    if policy_id and policy_id != "standalone":
        try:
            db_policy = db.get_policy(policy_id)
            if db_policy:
                # Map DB Policy to assemble_agent format
                gov_dict = {
                    "global_worldview": db_policy.get("worldview", ""),
                    "global_will_rules": db_policy.get("will_rules", []),
                    "global_values": db_policy.get("values_weights", [])
                }
                # Fix field names for DB values if needed (name vs value)
                for v in gov_dict["global_values"]:
                     if "name" in v and "value" not in v:
                         v["value"] = v["name"]
                         
                return assemble_agent(raw_persona, gov_dict)
        except Exception as e:
            print(f"Error applying policy {policy_id}: {e}")
            # Fall through to raw persona or Error? For now fall through.

    # B. Legacy Hardcoded Map (Old Way)
    if key in GOVERNANCE_MAP:
        return assemble_agent(raw_persona, GOVERNANCE_MAP[key])
    
    # C. Standalone / No Governance
    return raw_persona