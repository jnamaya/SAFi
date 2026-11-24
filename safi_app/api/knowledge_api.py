from flask import Blueprint, session, jsonify, request, current_app

from ..config import Config
from ..core.rbac import (check_permission, get_current_org_id, get_current_role,
                         require_any_role)
from ..role_config import ROLE_CONFIG
from ..persistence import database as db
from ..timeutil import utc_isoformat
from ..persistence.database import SelfReviewError

knowledge_bp = Blueprint('knowledge', __name__)

REVIEWER_ROLES = tuple(ROLE_CONFIG["reviewer_roles"])

SHARED_VISIBILITIES = tuple(
    value for value in ROLE_CONFIG["visibility_roles"] if value != "private"
)


def _actor():
    user = session.get('user') or {}
    return (user.get('id') or user.get('sub')), user.get('email')


def _can_read(kb, user_id, org_id, role):
    if not kb:
        return False
    if str(kb.get('created_by')) == str(user_id):
        return True
    if not kb.get('org_id') or str(kb['org_id']) != str(org_id):
        return False
    clears = {
        'admin':   ('member', 'auditor', 'editor', 'admin'),
        'editor':  ('member', 'auditor', 'editor'),
        'auditor': ('member', 'auditor'),
        'member':  ('member',),
    }.get(role or 'member', ('member',))
    return kb.get('visibility') in clears


def _can_write(kb, user_id):
    return bool(kb) and str(kb.get('created_by')) == str(user_id)


def _shape(kb, documents=None, review_detail=True):
    out = {
        "id": kb["id"],
        "name": kb["name"],
        "description": kb.get("description") or "",
        "visibility": kb.get("visibility"),
        "status": kb.get("status"),
        "status_detail": kb.get("status_detail"),
        "chunk_count": kb.get("chunk_count") or 0,
        "created_by": kb.get("created_by"),
        "org_id": kb.get("org_id"),
        "indexed_at": utc_isoformat(kb.get("indexed_at")),
        "created_at": utc_isoformat(kb.get("created_at")),
        "is_shared": kb.get("visibility") in SHARED_VISIBILITIES,
    }
    if documents is not None:
        out["documents"] = [_shape_doc(d, include_review_detail=review_detail)
                            for d in documents]
        out["pending_count"] = sum(1 for d in documents if d.get("status") == "pending")
    elif "pending_count" in kb:
        out["pending_count"] = int(kb["pending_count"] or 0)
    return out


def _shape_doc(doc, include_review_detail=True):
    out = {
        "id": doc["id"],
        "filename": doc["filename"],
        "size_bytes": doc.get("size_bytes") or 0,
        "char_count": doc.get("char_count") or 0,
        "status": doc.get("status"),
        "created_at": utc_isoformat(doc.get("created_at")),
    }
    if include_review_detail:
        out.update({
            "uploaded_by": doc.get("uploaded_by"),
            "reviewer_email": doc.get("reviewer_email"),
            "reviewed_at": utc_isoformat(doc.get("reviewed_at")),
            "reason": doc.get("reason"),
            "self_approved": bool(doc.get("self_approved")),
        })
    return out


def _sees_review_detail(kb, user_id, role):
    return (str(kb.get('created_by')) == str(user_id)) or (role in REVIEWER_ROLES)


def _sole_reviewer(user_id, org_id):
    if not org_id:
        return False
    return db.count_other_eligible_reviewers(
        org_id, user_id, reviewer_roles=ROLE_CONFIG["reviewer_roles"]
    ) == 0


@knowledge_bp.route('/knowledge-bases', methods=['GET'], strict_slashes=False)
def list_knowledge_bases():
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    rows = db.list_knowledge_bases(
        user_id, get_current_org_id(), get_current_role(), ROLE_CONFIG["visibility_roles"]
    )
    return jsonify({"knowledge_bases": [_shape(kb) for kb in rows]})


@knowledge_bp.route('/knowledge-bases/available', methods=['GET'], strict_slashes=False)
def list_available_knowledge_bases():
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    rows = db.list_knowledge_bases_for_agent_picker(
        user_id, get_current_org_id(), get_current_role(), ROLE_CONFIG["visibility_roles"])
    out = [{"id": kb["id"], "name": kb["name"],
            "chunk_count": kb.get("chunk_count") or 0, "builtin": False}
           for kb in rows]

    if request.args.get('include_builtin') in ('1', 'true', 'yes'):
        from ..profile_resolver import ALL_AGENTS
        seen = set()
        for agent in ALL_AGENTS.values():
            name = isinstance(agent, dict) and agent.get("rag_knowledge_base")
            if name and name not in seen:
                seen.add(name)
                out.append({"id": name, "name": name.replace("_", " "),
                            "chunk_count": 0, "builtin": True})

    return jsonify({"knowledge_bases": out})


@knowledge_bp.route('/knowledge-bases', methods=['POST'], strict_slashes=False)
def create_knowledge_base():
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    if not check_permission('editor'):
        return jsonify({"error": "Forbidden: Only Editors/Admins can create knowledge bases."}), 403

    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "A name is required."}), 400
    if len(name) > 255:
        return jsonify({"error": "Name is too long (max 255 characters)."}), 400

    kb = db.create_knowledge_base(
        name=name,
        created_by=user_id,
        description=(data.get('description') or '').strip() or None,
        org_id=get_current_org_id(),
    )
    return jsonify(_shape(kb)), 201


@knowledge_bp.route('/knowledge-bases/<kb_id>', methods=['GET'])
def get_knowledge_base(kb_id):
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    kb = db.get_knowledge_base(kb_id)
    if not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    role = get_current_role()
    documents = db.list_knowledge_base_documents(kb_id)
    body = _shape(kb, documents,
                  review_detail=_sees_review_detail(kb, user_id, role))
    body["sole_reviewer"] = (role in REVIEWER_ROLES
                             and _sole_reviewer(user_id, get_current_org_id()))
    body["can_manage"] = _can_write(kb, user_id)
    return jsonify(body)


@knowledge_bp.route('/knowledge-bases/<kb_id>', methods=['PUT'])
def update_knowledge_base(kb_id):
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can modify this knowledge base."}), 403

    data = request.get_json(force=True, silent=True) or {}

    if 'name' in data and len((data.get('name') or '').strip()) > 255:
        return jsonify({"error": "Name is too long (max 255 characters)."}), 400

    visibility = data.get('visibility')
    if visibility is not None and visibility not in ('private',) + SHARED_VISIBILITIES:
        return jsonify({"error": "Invalid visibility."}), 400
    if visibility in SHARED_VISIBILITIES and not get_current_org_id():
        return jsonify({"error": "You must belong to an organization to share a knowledge base."}), 400

    was_shared = kb.get('visibility') in SHARED_VISIBILITIES
    now_shared = (visibility in SHARED_VISIBILITIES) if visibility is not None else was_shared

    updated = db.update_knowledge_base(
        kb_id,
        name=(data.get('name') or '').strip() or None,
        description=data.get('description'),
        visibility=visibility,
    )

    if visibility is not None and now_shared != was_shared:
        from ..core.services.kb_indexer import enqueue_rebuild
        if now_shared:
            count = db.mark_documents_pending_for_share(kb_id)
            db.append_compliance_log(
                get_current_org_id(), 'kb_shared', f'user:{user_id}',
                {"kb_id": kb_id, "name": kb['name'], "documents_pending_review": count})
        else:
            db.mark_documents_private_for_unshare(kb_id)
            db.append_compliance_log(
                get_current_org_id(), 'kb_unshared', f'user:{user_id}',
                {"kb_id": kb_id, "name": kb['name']})
        enqueue_rebuild(kb_id)
        updated = db.get_knowledge_base(kb_id)

    return jsonify(_shape(updated))


@knowledge_bp.route('/knowledge-bases/<kb_id>', methods=['DELETE'])
def delete_knowledge_base(kb_id):
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can delete this knowledge base."}), 403

    from ..core.services.kb_indexer import delete_kb_artifacts
    db.delete_knowledge_base(kb_id)
    delete_kb_artifacts(kb_id)

    if kb.get('org_id'):
        db.append_compliance_log(
            kb['org_id'], 'kb_deleted', f'user:{user_id}',
            {"kb_id": kb_id, "name": kb['name'], "chunk_count": kb.get('chunk_count') or 0})

    return jsonify({"ok": True})


@knowledge_bp.route('/knowledge-bases/<kb_id>/reindex', methods=['POST'])
def reindex_knowledge_base(kb_id):
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can rebuild this knowledge base."}), 403
    from ..core.services.kb_indexer import enqueue_rebuild
    enqueue_rebuild(kb_id)
    return jsonify(_shape(db.get_knowledge_base(kb_id)))


@knowledge_bp.route('/knowledge-bases/<kb_id>/documents', methods=['POST'])
def upload_document(kb_id):
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can add documents."}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    from ..core.services.document_processor import allowed_file, extract_text
    from ..core.services.kb_indexer import MAX_INDEX_CHARS_PER_DOC, enqueue_rebuild

    if not allowed_file(file.filename):
        allowed = ', '.join(Config.ALLOWED_UPLOAD_EXTENSIONS)
        return jsonify({"error": f"Unsupported file type. Allowed: {allowed}"}), 400

    file.seek(0, 2)
    size_bytes = file.tell()
    file.seek(0)
    if size_bytes / (1024 * 1024) > Config.MAX_UPLOAD_SIZE_MB:
        return jsonify({
            "error": f"File too large ({size_bytes / (1024 * 1024):.1f}MB). "
                     f"Maximum: {Config.MAX_UPLOAD_SIZE_MB}MB"
        }), 400

    try:
        text, total_chars = extract_text(file, file.filename,
                                         max_chars=MAX_INDEX_CHARS_PER_DOC)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        current_app.logger.exception("KB document extraction failed")
        return jsonify({"error": "Failed to extract text from document."}), 500

    if not (text or '').strip():
        return jsonify({"error": "No readable text found in that document."}), 400

    status = 'pending' if kb.get('visibility') in SHARED_VISIBILITIES else 'private'
    doc = db.add_knowledge_base_document(
        kb_id=kb_id, filename=file.filename, text=text,
        uploaded_by=user_id, size_bytes=size_bytes, status=status)

    if kb.get('org_id'):
        db.append_compliance_log(
            kb['org_id'], 'kb_document_uploaded', f'user:{user_id}',
            {"kb_id": kb_id, "document_id": doc["id"], "filename": file.filename,
             "sha256": doc.get("sha256"), "char_count": total_chars, "status": status})

    enqueue_rebuild(kb_id)

    return jsonify({"document": _shape_doc(doc),
                    "knowledge_base": _shape(db.get_knowledge_base(kb_id))}), 201


@knowledge_bp.route('/knowledge-bases/<kb_id>/documents/<doc_id>', methods=['DELETE'])
def delete_document(kb_id, doc_id):
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can remove documents."}), 403

    doc = db.get_knowledge_base_document(doc_id)
    if not doc or str(doc.get('kb_id')) != str(kb_id):
        return jsonify({"error": "Not found."}), 404

    from ..core.services.kb_indexer import enqueue_rebuild
    db.delete_knowledge_base_document(doc_id)
    if kb.get('org_id'):
        db.append_compliance_log(
            kb['org_id'], 'kb_document_deleted', f'user:{user_id}',
            {"kb_id": kb_id, "document_id": doc_id, "filename": doc.get("filename")})
    enqueue_rebuild(kb_id)
    return jsonify({"ok": True, "knowledge_base": _shape(db.get_knowledge_base(kb_id))})


@knowledge_bp.route('/knowledge-bases/<kb_id>/documents/<doc_id>/review',
                    methods=['POST'])
@require_any_role(*REVIEWER_ROLES)
def review_document(kb_id, doc_id):
    user_id, email = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb:
        return jsonify({"error": "Not found."}), 404
    if not kb.get('org_id') or str(kb['org_id']) != str(get_current_org_id()):
        return jsonify({"error": "Not found."}), 404
    if kb.get('visibility') not in SHARED_VISIBILITIES:
        return jsonify({
            "error": "This knowledge base is private; its documents are not "
                     "subject to review. Approval applies to shared knowledge."
        }), 400

    doc = db.get_knowledge_base_document(doc_id)
    if not doc or str(doc.get('kb_id')) != str(kb_id):
        return jsonify({"error": "Not found."}), 404

    data = request.get_json(force=True, silent=True) or {}
    action = data.get('action')
    try:
        updated = db.set_knowledge_base_document_status(
            doc_id, action, reviewer_id=user_id, reviewer_email=email,
            reason=data.get('reason'), org_id=kb['org_id'],
            reviewer_roles=ROLE_CONFIG["reviewer_roles"])
    except SelfReviewError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not updated:
        return jsonify({"error": "Not found."}), 404

    from ..core.services.kb_indexer import enqueue_rebuild
    enqueue_rebuild(kb_id)

    return jsonify({"document": _shape_doc(updated),
                    "knowledge_base": _shape(db.get_knowledge_base(kb_id))})


@knowledge_bp.route('/knowledge-bases/pending-reviews', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def list_pending_reviews():
    user_id, _ = _actor()
    org_id = get_current_org_id()
    if not org_id:
        return jsonify({"pending": []})

    sole = _sole_reviewer(user_id, org_id)
    pending = []
    for kb in db.list_knowledge_bases(
        user_id, org_id, get_current_role(), ROLE_CONFIG["visibility_roles"]
    ):
        if kb.get('visibility') not in SHARED_VISIBILITIES:
            continue
        for doc in db.list_knowledge_base_documents(kb['id'], statuses=('pending',)):
            item = _shape_doc(doc)
            item['kb_id'] = kb['id']
            item['kb_name'] = kb['name']
            item['self_uploaded'] = str(doc.get('uploaded_by')) == str(user_id)
            pending.append(item)
    return jsonify({"pending": pending, "sole_reviewer": sole})
