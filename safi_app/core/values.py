from typing import Dict, Any, List, Optional
import copy
import json
from pathlib import Path

# 1. Import Governance
from .governance.contoso.policy import CONTOSO_GLOBAL_POLICY
from ..persistence import database as db

# 2. Import Personas
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
    "contoso_admin": THE_CONTOSO_ADMIN_PERSONA,
    "fiduciary": THE_FIDUCIARY_PERSONA,
    "health_navigator": THE_HEALTH_NAVIGATOR_PERSONA,
    "bible_scholar": THE_BIBLE_SCHOLAR_PERSONA,
    "safi": THE_SAFI_STEWARD_PERSONA,
    "tutor": THE_SOCRATIC_TUTOR_PERSONA,
    "vault": THE_VAULT_PERSONA,
    "negotiator": THE_NEGOTIATOR_PERSONA,
}

# 4. Governance Mapping
GOVERNANCE_MAP: Dict[str, Dict[str, Any]] = {
    "contoso_admin": CONTOSO_GLOBAL_POLICY,
}

# 5. Compiler Logic
def assemble_agent(base_profile: Dict[str, Any], governance: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies the Governance Layer to a base persona.
    """
    final_profile = copy.deepcopy(base_profile)
    
    # A. Merge Worldview (Gov on top)
    final_profile["worldview"] = (
        f"--- Organizational Policy ---\n"
        f"{governance.get('global_worldview', '')}\n"
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
    
    # Target Ratios
    if not agent_values:
        g_target, a_target = 1.0, 0.0
    elif not global_values:
         g_target, a_target = 0.0, 1.0
    else:
        g_target, a_target = 0.40, 0.60
    
    # Normalize
    g_sum = sum(v.get("weight", 0) for v in global_values)
    if g_sum > 0:
        factor = g_target / g_sum
        for v in global_values: v["weight"] = round(v.get("weight", 0) * factor, 3)
    
    a_sum = sum(v.get("weight", 0) for v in agent_values)
    if a_sum > 0:
        factor = a_target / a_sum
        for v in agent_values: v["weight"] = round(v.get("weight", 0) * factor, 3)
    
    final_profile["values"] = global_values + agent_values
    return final_profile

# 6. Loading Helpers (DB UPDATED)

def load_custom_persona(name: str) -> Optional[Dict[str, Any]]:
    """
    Loads a custom persona from the Database.
    Replaces old file-based logic.
    """
    try:
        # Normalize key
        clean_name = name.lower().strip().replace(" ", "_")
        clean_name = "".join(c for c in clean_name if c.isalnum() or c == '_')
        
        # Fetch from DB
        agent = db.get_agent(clean_name)
        if agent:
            # Ensure critical keys exist
            if "values" not in agent: agent["values"] = []
            if "will_rules" not in agent: agent["will_rules"] = []
            
            # --- COMPATIBILITY FIX ---
            # Map 'name' -> 'value' for the core engine
            if isinstance(agent["values"], list):
                for v in agent["values"]:
                    if "name" in v and "value" not in v:
                        v["value"] = v["name"]
            
            return agent
            
    except Exception as e:
        print(f"Error loading custom persona {name} from DB: {e}")
        return None
    return None

def list_custom_personas(owner_id: Optional[str] = None, include_all: bool = False) -> List[Dict[str, Any]]:
    """
    Lists personas from the Database.
    """
    try:
        # DB List function already filters by owner_id
        return db.list_agents(owner_id)
    except Exception as e:
        print(f"Error listing custom personas: {e}")
        return []

# 7. Public Accessors
def list_profiles(owner_id: Optional[str] = None, include_all: bool = False) -> List[Dict[str, str]]:
    # Built-in Personas
    builtins = [{"key": key, "name": persona["name"], "is_custom": False, "created_by": None} for key, persona in PERSONAS.items()]
    
    # Custom Personas (From DB)
    customs = list_custom_personas(owner_id, include_all=include_all)
    
    all_profiles = builtins + customs
    return sorted(all_profiles, key=lambda x: x["name"])

def get_profile(name: str) -> Dict[str, Any]:
    """
    Retrieves a persona. Checks DB first, then built-ins.
    """
    key = (name or "").lower().strip()
    
    # 1. Check Built-ins
    if key in PERSONAS:
        raw_persona = PERSONAS[key]
    else:
        # 2. Check DB
        raw_persona = load_custom_persona(key)
        if not raw_persona:
            raise KeyError(f"Unknown persona '{name}'.")

    # --- GOVERNANCE LOGIC ---
    
    # A. Dynamic Policy from DB
    policy_id = raw_persona.get("policy_id")
    if policy_id and policy_id != "standalone":
        try:
            db_policy = db.get_policy(policy_id)
            if db_policy:
                gov_dict = {
                    "global_worldview": db_policy.get("worldview", ""),
                    "global_will_rules": db_policy.get("will_rules", []),
                    "global_values": db_policy.get("values_weights", [])
                }
                # Fix field names for DB values
                for v in gov_dict["global_values"]:
                     if "name" in v and "value" not in v:
                         v["value"] = v["name"]
                         
                return assemble_agent(raw_persona, gov_dict)
        except Exception as e:
            print(f"Error applying policy {policy_id}: {e}")

    # B. Legacy Hardcoded Map
    if key in GOVERNANCE_MAP:
        return assemble_agent(raw_persona, GOVERNANCE_MAP[key])
    
    return raw_persona