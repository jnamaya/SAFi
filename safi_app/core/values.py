from typing import Dict, Any, List
import copy

# 1. Import Governance (Updated for Contoso structure)
from .governance.contoso.policy import CONTOSO_GLOBAL_POLICY

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

    # C. Merge Values & Math
    global_values = copy.deepcopy(governance.get("global_values", []))
    agent_values = final_profile.get("values", [])
    
    # Calculate Weight Distribution
    global_weight_sum = sum(v["weight"] for v in global_values) 
    remaining_space = 1.0 - global_weight_sum
    
    # Scale Agent Values
    current_agent_sum = sum(v["weight"] for v in agent_values)
    scale_factor = remaining_space / current_agent_sum if current_agent_sum > 0 else 0
    
    for val in agent_values:
        val["weight"] = round(val["weight"] * scale_factor, 3)
        
    # Combine
    final_profile["values"] = global_values + agent_values
    
    return final_profile

# 6. Public Accessors
def list_profiles() -> List[Dict[str, str]]:
    return sorted(
        [{"key": key, "name": persona["name"]} for key, persona in PERSONAS.items()],
        key=lambda x: x["name"]
    )

def get_profile(name: str) -> Dict[str, Any]:
    """
    Retrieves a persona. 
    Checks the GOVERNANCE_MAP to see if a policy should be applied.
    """
    key = (name or "").lower().strip()
    
    if key not in PERSONAS:
        raise KeyError(f"Unknown persona '{name}'. Available: {[p['key'] for p in list_profiles()]}")
        
    raw_persona = PERSONAS[key]

    # --- CONDITIONAL GOVERNANCE LOGIC ---
    # If this persona is assigned to a governance policy, apply it.
    if key in GOVERNANCE_MAP:
        return assemble_agent(raw_persona, GOVERNANCE_MAP[key])
    
    # Otherwise, return the raw persona (Independent)
    return raw_persona