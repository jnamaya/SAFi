from flask import Blueprint, jsonify, session

from ..persistence import attention_store
from ..persistence import tool_approval_store
from ..role_config import ROLE_CONFIG
from ..core.rbac import check_any_role

attention_bp = Blueprint('attention_api', __name__)

_CATEGORIES = {
    "kb_documents":  ("knowledge", "Documents awaiting review"),
    "review_queue":  ("review", "Flagged turns awaiting disposition"),
    "tool_requests": ("agents", "Tool grants awaiting approval"),
    "policy_changes": ("governance", "Policy changes awaiting approval"),
    "my_pending_requests": ("agents", "Your requests: awaiting review"),
    "my_tool_requests": ("agents", "Your requests: decided"),
    "invitations":   ("organization", "Open invitations"),
    "incidents":     ("compliance", "Open security incidents"),
    "schedules":     ("schedules", "Scheduled updates failing"),
}

_DISMISSIBLE = {"my_tool_requests"}

_INFORMATIONAL = {"my_pending_requests", "my_tool_requests"}


def _item(key, agg):
    target, title = _CATEGORIES[key]
    return {
        "key": key,
        "title": title,
        "target": target,
        "count": agg["count"],
        "oldest": agg["oldest"].isoformat() if agg.get("oldest") else None,
        "examples": agg.get("examples") or [],
        "dismissible": key in _DISMISSIBLE,
        "actionable": key not in _INFORMATIONAL,
    }


@attention_bp.route('/attention', methods=['GET'], strict_slashes=False)
def get_attention():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Authentication required."}), 401
    user_id = user.get('id') or user.get('sub')
    org_id = user.get('org_id')

    items = []
    try:
        agg = attention_store.failed_schedules(user_id)
        if agg["count"]:
            items.append(_item("schedules", agg))
    except Exception:
        pass
    try:
        agg = tool_approval_store.pending_own_requests(user_id)
        if agg["count"]:
            items.append(_item("my_pending_requests", agg))
    except Exception:
        pass
    try:
        agg = tool_approval_store.unacknowledged_outcomes(user_id)
        if agg["count"]:
            items.append(_item("my_tool_requests", agg))
    except Exception:
        pass

    if org_id and check_any_role(('admin', 'auditor')):
        for key, fn in (("kb_documents", attention_store.pending_kb_documents),
                        ("review_queue", attention_store.pending_review_items)):
            try:
                agg = fn(org_id)
                if agg["count"]:
                    items.append(_item(key, agg))
            except Exception:
                pass

    if org_id:
        try:
            if tool_approval_store.is_reviewer(
                org_id, user_id, user.get('role'),
                reviewer_roles=ROLE_CONFIG["reviewer_roles"],
            ):
                agg = tool_approval_store.pending_summary(org_id)
                if agg["count"]:
                    items.append(_item("tool_requests", agg))
        except Exception:
            pass
        try:
            if tool_approval_store.is_reviewer(
                org_id, user_id, user.get('role'), kind='policy',
                reviewer_roles=ROLE_CONFIG["reviewer_roles"],
            ):
                agg = tool_approval_store.pending_policy_summary(org_id)
                if agg["count"]:
                    items.append(_item("policy_changes", agg))
        except Exception:
            pass

    if org_id and check_any_role(('admin',)):
        for key, fn in (("invitations", attention_store.pending_invitations),
                        ("incidents", attention_store.open_incidents)):
            try:
                agg = fn(org_id)
                if agg["count"]:
                    items.append(_item(key, agg))
            except Exception:
                pass

    return jsonify({"ok": True, "items": items,
                    "total": sum(i["count"] for i in items)})


@attention_bp.route('/attention/actions', methods=['GET'], strict_slashes=False)
def get_attention_actions():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Authentication required."}), 401
    user_id = user.get('id') or user.get('sub')
    org_id = user.get('org_id')

    policy_changes = []
    tool_requests = []

    if org_id:
        try:
            if tool_approval_store.is_reviewer(
                org_id, user_id, user.get('role'), kind='policy',
                reviewer_roles=ROLE_CONFIG["reviewer_roles"],
            ):
                for r in tool_approval_store.list_policy_changes(org_id, 'pending'):
                    policy_changes.append({
                        "id": r["id"],
                        "policy_name": r.get("policy_name") or r.get("policy_id"),
                        "requester_name": r.get("requester_name") or r.get("requested_by"),
                        "changed": r.get("changed") or [],
                        "created_at": r["created_at"].isoformat() if getattr(r.get("created_at"), "isoformat", None) else r.get("created_at"),
                    })
        except Exception:
            pass
        try:
            if tool_approval_store.is_reviewer(
                org_id, user_id, user.get('role'),
                reviewer_roles=ROLE_CONFIG["reviewer_roles"],
            ):
                for r in tool_approval_store.list_requests(org_id, 'pending'):
                    tool_requests.append({
                        "id": r["id"],
                        "request_type": r.get("request_type") or "agent",
                        "agent_name": r.get("agent_name") or r.get("agent_key"),
                        "policy_name": r.get("policy_name") or r.get("policy_id"),
                        "requester_name": r.get("requester_name") or r.get("requested_by"),
                        "added": r.get("added") or [],
                        "created_at": r["created_at"].isoformat() if getattr(r.get("created_at"), "isoformat", None) else r.get("created_at"),
                    })
        except Exception:
            pass

    return jsonify({"ok": True, "policy_changes": policy_changes,
                    "tool_requests": tool_requests})
