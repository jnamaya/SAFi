"""
safi_app/core/permissions.py

Defines the Role-Based Access Control (RBAC) logic for the SAFi platform.
Roles:
- Governor (admin): Full access to Org Settings, Policies, and all Agents.
- Alignment Engineer (editor): Can create/edit Agents and Rubrics. Read-only Policy.
- Auditor (auditor): Read-only access to Logs, Configs, and Agents.
- Operator (member): Chat-only access.
"""

# Map Roles to Capabilities
ROLES = {
    # The Governor: Ultimate authority
    "admin": ["*"], 
    
    # Alignment Engineer: The builder
    "editor": [
        "agent:read", "agent:write", "agent:delete", 
        "rubric:write", 
        "policy:read",
        "chat:use"
    ],
    
    # Auditor: Compliance officer
    "auditor": [
        "agent:read", 
        "policy:read", 
        "logs:read", 
        "config:read",
        "chat:use"
    ],
    
    # Operator: End user
    "member": [
        "agent:read", # Can view agent details to select them
        "chat:use"
    ]
}

def can_perform(user_role: str, action: str) -> bool:
    """
    Checks if a role has the required capability.
    """
    if not user_role:
        return False
        
    capabilities = ROLES.get(user_role, [])
    
    if "*" in capabilities:
        return True
        
    return action in capabilities

def get_effective_visibility(user_role: str, is_owner: bool) -> list:
    """
    Returns list of visibility levels this user can see within THEIR Org.
    """
    # Everyone sees Public and Internal
    levels = ["public", "internal"]
    
    # Owners and Admins can see Private
    if is_owner or user_role == "admin":
        levels.append("private")
        
    return levels
