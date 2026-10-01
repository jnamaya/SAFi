"""Default role names and assignments, separate from generic RBAC mechanics."""
ROLE_CONFIG_VERSION = "default-role-config-1"

ROLE_CONFIG = {
    "levels": {
        "member": 1,
        "auditor": 2,
        "editor": 3,
        "admin": 4,
    },
    "default_role": "member",
    "organization_admin_roles": ["admin"],
    "reviewer_roles": ["admin", "auditor"],
    "visibility_roles": {
        "private": [],
        "member": ["member", "auditor", "editor", "admin"],
        "auditor": ["auditor", "editor", "admin"],
        "editor": ["editor", "admin"],
        "admin": ["admin"],
    },
}
