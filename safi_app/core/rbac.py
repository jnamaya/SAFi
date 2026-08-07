
"""Role-based access control.

This module is the ONLY authorization model SAFi enforces. A parallel
capability model once lived in core/permissions.py — naming permissions like
"policy:read" and "logs:read" — but nothing ever called it, so it advertised
an access-control system that did not exist. It was removed rather than left
to mislead the next reader; if per-capability authorization is wanted, it
should be built here, where the 60+ enforcement points already are.

The four roles, and what they mean in practice:

  admin   (Governor)             full authority: org settings, policies,
                                 members, provider allow-list, all agents
  editor  (Alignment Engineer)   builds agents and rubrics; reads policy
  auditor (Compliance Officer)   read-only over agents, policy, logs, config
  member  (Operator)             chat only

Two enforcement styles, and the distinction matters:

  require_role(x)      >= on the ladder below. Use for escalating authority.
  require_any_role(..) explicit set membership, no ladder. Use where rank is
                       the wrong question — supervisory review is admin|auditor
                       because editors outrank auditors yet must not sign off
                       on content they authored.
"""
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

def check_any_role(roles):
    """True when the current user's role is IN the explicit set — no hierarchy.
    For permissions the linear ladder can't express (e.g. the review queue's
    reviewer set is admin|auditor: editors rank above auditors but content
    authors don't supervise themselves)."""
    user = session.get('user')
    if not user:
        return False
    return user.get('role', 'member') in roles

def require_any_role(*roles):
    """Decorator: allow only an explicit set of roles (set membership, not
    the >= hierarchy of require_role)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not check_any_role(roles):
                return jsonify({"error": f"Forbidden: Requires one of: {', '.join(roles)}."}), 403
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


def get_current_role():
    """The session user's role, defaulting to the least privileged.

    Callers that pass this to a visibility-filtered query (db.list_agents)
    must get 'member' rather than None when there is no session, so an
    unauthenticated path can never widen what is returned.
    """
    user = session.get('user') or {}
    return user.get('role') or 'member'
