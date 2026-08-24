"""
Custom groups (backlog 55): named sets of org members used as sharing
grantees.

Group management is admin-only in v1. Membership is data, not authority: a
group confers nothing by itself; it only aggregates who a per-agent grant
reaches, and grants confer 'can_use' only. Every change appends compliance
evidence, same as member and role changes.
"""
from flask import Blueprint, request, jsonify, session, current_app

from ..persistence import database as db
from ..persistence import sharing_store
from ..persistence import conversation_sharing_store
from ..core.rbac import require_role, get_current_org_id

groups_bp = Blueprint('groups_api', __name__)

GROUP_NAME_MAX = 100


def _actor():
    user = session.get('user') or {}
    return user.get('id') or user.get('sub')


def _org_group_or_404(group_id):
    """The group, if it belongs to the caller's org; None otherwise. A foreign
    org's group answers 404, never 403, so ids are not confirmable."""
    org_id = get_current_org_id()
    if not org_id:
        return None
    group = sharing_store.get_group(group_id)
    if not group or str(group.get('org_id')) != str(org_id):
        return None
    return group


@groups_bp.route('/groups', methods=['GET'], strict_slashes=False)
@require_role('admin')
def list_groups():
    org_id = get_current_org_id()
    if not org_id:
        return jsonify({"error": "You are not part of an organization."}), 400
    return jsonify({"ok": True, "groups": sharing_store.list_groups(org_id)})


@groups_bp.route('/groups', methods=['POST'], strict_slashes=False)
@require_role('admin')
def create_group():
    org_id = get_current_org_id()
    if not org_id:
        return jsonify({"error": "You are not part of an organization."}), 400
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name or len(name) > GROUP_NAME_MAX:
        return jsonify({"error": f"'name' is required (max {GROUP_NAME_MAX} characters)."}), 400
    if sharing_store.group_name_taken(org_id, name):
        return jsonify({"error": "A group with that name already exists."}), 409
    group_id = sharing_store.create_group(org_id, name, _actor())
    db.append_compliance_log(org_id, 'group_created', f"user:{_actor()}",
                             {"group_id": group_id, "name": name})
    return jsonify({"ok": True, "id": group_id, "name": name}), 201


@groups_bp.route('/groups/<group_id>', methods=['DELETE'], strict_slashes=False)
@require_role('admin')
def delete_group(group_id):
    group = _org_group_or_404(group_id)
    if not group:
        return jsonify({"error": "Not found"}), 404
    sharing_store.delete_group(group_id)
    conversation_sharing_store.delete_grants_for_group(group_id)
    db.append_compliance_log(get_current_org_id(), 'group_deleted', f"user:{_actor()}",
                             {"group_id": group_id, "name": group.get('name')})
    return jsonify({"ok": True})


@groups_bp.route('/groups/<group_id>/members', methods=['GET'], strict_slashes=False)
@require_role('admin')
def list_members(group_id):
    group = _org_group_or_404(group_id)
    if not group:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True, "group": {"id": group['id'], "name": group['name']},
                    "members": sharing_store.list_group_members(group_id)})


@groups_bp.route('/groups/<group_id>/members', methods=['POST'], strict_slashes=False)
@require_role('admin')
def add_member(group_id):
    group = _org_group_or_404(group_id)
    if not group:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    user_id = (data.get('user_id') or '').strip()
    if not user_id:
        return jsonify({"error": "'user_id' is required."}), 400
    target = db.get_user_details(user_id)
    if not target or str(target.get('org_id')) != str(get_current_org_id()):
        return jsonify({"error": "That user is not a member of your organization."}), 400
    sharing_store.add_group_member(group_id, user_id, _actor())
    db.append_compliance_log(get_current_org_id(), 'group_member_added', f"user:{_actor()}",
                             {"group_id": group_id, "group": group.get('name'),
                              "member": user_id})
    return jsonify({"ok": True})


@groups_bp.route('/groups/<group_id>/members/<user_id>', methods=['DELETE'], strict_slashes=False)
@require_role('admin')
def remove_member(group_id, user_id):
    group = _org_group_or_404(group_id)
    if not group:
        return jsonify({"error": "Not found"}), 404
    removed = sharing_store.remove_group_member(group_id, user_id)
    if removed:
        db.append_compliance_log(get_current_org_id(), 'group_member_removed', f"user:{_actor()}",
                                 {"group_id": group_id, "group": group.get('name'),
                                  "member": user_id})
    return jsonify({"ok": True, "removed": removed})
