
from flask import session, jsonify, request
from functools import wraps

# Define Role Hierarchy
ROLES = {
    'admin': 4,
    'editor': 3,
    'auditor': 2,
    'member': 1
}

def check_permission(required_role):
    """
    Checks if the current user has the required role (or higher).
    """
    user = session.get('user')
    if not user:
        return False
    
    user_role = user.get('role', 'member')
    
    # If role not in definitions, default to member (lowest)
    user_level = ROLES.get(user_role, 1)
    required_level = ROLES.get(required_role, 1)
    
    return user_level >= required_level

def require_role(role):
    """
    Decorator to protect routes based on role.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not check_permission(role):
                return jsonify({"error": f"Forbidden: Requires {role} role."}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_current_org_id():
    """
    Helper to get the organization ID from the session.
    """
    user = session.get('user')
    if user:
        return user.get('org_id')
    return None
