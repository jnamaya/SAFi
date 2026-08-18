"""
GET /api/attention (backlog 57): the role-aware inbox of everything waiting
on this user. One read-only endpoint; the bell in the sidebar shows the total
and the panel deep-links each category to the tab where the action happens.

Role shaping happens HERE, not in the store: the store answers "what is
pending", this layer decides who may see which answer. Members see only
their own items; auditors add the review workloads; admins see everything.
The response deliberately contains no content bodies (no document text, no
flagged turns), only counts, ages, and short labels, so this endpoint never
becomes a second place where sensitive content must be access-controlled.
"""
from flask import Blueprint, jsonify, session

from ..persistence import attention_store
from ..persistence import tool_approval_store
from ..core.rbac import check_any_role

attention_bp = Blueprint('attention_api', __name__)

# category key -> (control panel tab it deep-links to, human title)
_CATEGORIES = {
    "kb_documents":  ("knowledge", "Documents awaiting review"),
    "review_queue":  ("review", "Flagged turns awaiting disposition"),
    "tool_requests": ("agents", "Tool grants awaiting approval"),
    "my_tool_requests": ("agents", "Your tool requests: decided"),
    "invitations":   ("organization", "Open invitations"),
    "incidents":     ("compliance", "Open security incidents"),
    "schedules":     ("schedules", "Scheduled updates failing"),
}

# Categories that are information rather than work: the reader may dismiss
# them, the one exception to "items leave on their own once the work is
# done" (an outcome has no work to do the leaving).
_DISMISSIBLE = {"my_tool_requests"}


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
    }


@attention_bp.route('/attention', methods=['GET'], strict_slashes=False)
def get_attention():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Authentication required."}), 401
    user_id = user.get('id') or user.get('sub')
    org_id = user.get('org_id')

    items = []
    # Everyone: their own failing schedules, and the outcomes of their own
    # tool requests (backlog 57c).
    try:
        agg = attention_store.failed_schedules(user_id)
        if agg["count"]:
            items.append(_item("schedules", agg))
    except Exception:
        pass  # a broken source must never take the inbox down
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

    # Tool requests route to the ACTIVE approver set (backlog 57e): the
    # designated approver group when one exists, admin|auditor otherwise. A
    # designated approver may hold any role, so this is not role-gated.
    if org_id:
        try:
            if tool_approval_store.is_reviewer(org_id, user_id, user.get('role')):
                agg = tool_approval_store.pending_summary(org_id)
                if agg["count"]:
                    items.append(_item("tool_requests", agg))
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
