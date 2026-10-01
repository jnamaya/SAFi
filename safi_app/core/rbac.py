"""Generic role/capability enforcement over host-supplied role data."""
from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify, request, session


def _role_config():
    try:
        return current_app.config.get("ROLE_CONFIG", {}) or {}
    except RuntimeError:
        return {}


def check_permission(required_role):
    """Compare role ranks from host configuration; unknown roles fail closed."""
    user = session.get("user")
    if not user:
        return False
    levels = _role_config().get("levels", {})
    current_role = user.get("role") or _role_config().get("default_role")
    current_level = levels.get(current_role)
    required_level = levels.get(required_role)
    return current_level is not None and required_level is not None and current_level >= required_level


def require_role(role):
    def decorator(function):
        @wraps(function)
        def decorated_function(*args, **kwargs):
            if not check_permission(role):
                return jsonify({"error": f"Forbidden: Requires {role} role."}), 403
            return function(*args, **kwargs)
        return decorated_function
    return decorator


def check_any_role(roles):
    user = session.get("user")
    role = user.get("role") if user else None
    role = role or _role_config().get("default_role")
    return bool(user) and role in roles


def require_any_role(*roles):
    def decorator(function):
        @wraps(function)
        def decorated_function(*args, **kwargs):
            if not check_any_role(roles):
                return jsonify({"error": f"Forbidden: Requires one of: {', '.join(roles)}."}), 403
            return function(*args, **kwargs)
        return decorated_function
    return decorator


def get_current_org_id():
    user = session.get("user")
    return user.get("org_id") if user else None


def get_current_role():
    user = session.get("user") or {}
    return user.get("role") or _role_config().get("default_role")
