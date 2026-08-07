"""
API routes for user-created knowledge bases (RAG corpora).

AUTHORIZATION MODEL — three distinct gates, deliberately not one
----------------------------------------------------------------
1. **Build/attach: `editor`+.** Not a new rule — creating an agent is already
   `editor`+ (`agent_api_routes.py`), and a `member` (Operator) cannot build an
   agent at all, so cannot attach a corpus to one. Knowledge bases inherit that
   gate rather than inventing a parallel one.

2. **Read: visibility ladder**, identical to agents. Owner always; org members
   as their role clears `knowledge_bases.visibility`.

3. **Approve: `admin|auditor` via `require_any_role` — never
   `require_role('auditor')`.** The role ladder puts `editor` (3) ABOVE
   `auditor` (2), so `require_role` would let the very editors who upload
   documents approve their own. This is the trap `rbac.py` documents and
   `review_api.py` avoids; it is the single easiest line in this file to get
   wrong. Separation of duties itself lives in the persistence layer
   (`set_knowledge_base_document_status` raises SelfReviewError) so that a
   future batch or scripted path inherits it.

APPROVAL ATTACHES TO SHARING, NOT TO DOCUMENTS
----------------------------------------------
A private KB has no eligible approver — self-approval is exactly what
separation of duties forbids, and reviewing a document only its uploader can
retrieve would be a rubber stamp. So a private KB's documents are 'private'
and indexable on upload; the moment a KB is shared org-wide every document
becomes 'pending' and must be approved by someone else before it is indexed.
"""
from flask import Blueprint, session, jsonify, request, current_app

from ..config import Config
from ..core.rbac import (check_permission, get_current_org_id, get_current_role,
                         require_any_role)
from ..persistence import database as db
from ..persistence.database import SelfReviewError

knowledge_bp = Blueprint('knowledge', __name__)

REVIEWER_ROLES = ("admin", "auditor")

# Visibility values that mean "shared with the org" — i.e. approval applies.
SHARED_VISIBILITIES = ("member", "auditor", "editor", "admin")


def _actor():
    user = session.get('user') or {}
    return (user.get('id') or user.get('sub')), user.get('email')


def _can_read(kb, user_id, org_id, role):
    """Owner always; otherwise the org visibility ladder, same as agents."""
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
    """Mutating a KB's contents is the owner's right.

    Mirrors delete_agent, which checks `created_by == uid` rather than rank:
    an org admin governs *whether* a corpus may be shared and *what* it may
    contain (via approval), which is a different power from editing someone
    else's working set.
    """
    return bool(kb) and str(kb.get('created_by')) == str(user_id)


def _shape(kb, documents=None):
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
        "indexed_at": kb.get("indexed_at").isoformat() if kb.get("indexed_at") else None,
        "created_at": kb.get("created_at").isoformat() if kb.get("created_at") else None,
        "is_shared": kb.get("visibility") in SHARED_VISIBILITIES,
    }
    if documents is not None:
        out["documents"] = [_shape_doc(d) for d in documents]
        out["pending_count"] = sum(1 for d in documents if d.get("status") == "pending")
    elif "pending_count" in kb:
        # From list_knowledge_bases, which counts in SQL rather than making the
        # list view fetch every document just to render a card.
        out["pending_count"] = int(kb["pending_count"] or 0)
    return out


def _shape_doc(doc):
    return {
        "id": doc["id"],
        "filename": doc["filename"],
        "size_bytes": doc.get("size_bytes") or 0,
        "char_count": doc.get("char_count") or 0,
        "status": doc.get("status"),
        "uploaded_by": doc.get("uploaded_by"),
        "reviewer_email": doc.get("reviewer_email"),
        "reviewed_at": doc.get("reviewed_at").isoformat() if doc.get("reviewed_at") else None,
        "reason": doc.get("reason"),
        "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
    }


# --- Knowledge bases ------------------------------------------------------

@knowledge_bp.route('/knowledge-bases', methods=['GET'], strict_slashes=False)
def list_knowledge_bases():
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    rows = db.list_knowledge_bases(user_id, get_current_org_id(), get_current_role())
    return jsonify({"knowledge_bases": [_shape(kb) for kb in rows]})


@knowledge_bp.route('/knowledge-bases/available', methods=['GET'], strict_slashes=False)
def list_available_knowledge_bases():
    """The agent wizard's picker. Only KBs that can actually ground an answer.

    A KB with no indexed vectors would look configured on the agent and answer
    nothing — the same 'allowed is not the same as useful' failure the
    connector tab already fixed."""
    user_id, _ = _actor()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    rows = db.list_knowledge_bases_for_agent_picker(
        user_id, get_current_org_id(), get_current_role())
    return jsonify({"knowledge_bases": [
        {"id": kb["id"], "name": kb["name"], "chunk_count": kb.get("chunk_count") or 0}
        for kb in rows]})


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
        # 404 not 403: a KB the caller cannot see should not be confirmed to exist.
        return jsonify({"error": "Not found."}), 404
    documents = db.list_knowledge_base_documents(kb_id)
    return jsonify(_shape(kb, documents))


@knowledge_bp.route('/knowledge-bases/<kb_id>', methods=['PUT'])
def update_knowledge_base(kb_id):
    """Rename, re-describe, or change visibility.

    Changing visibility is the approval trigger. Sharing re-flags every
    'private' document as 'pending' and rebuilds, so a corpus cannot become
    org-readable while carrying unreviewed content — the vectors have to go
    away before anyone else can retrieve them, not after review catches up.
    """
    user_id, _ = _actor()
    kb = db.get_knowledge_base(kb_id)
    if not kb or not _can_read(kb, user_id, get_current_org_id(), get_current_role()):
        return jsonify({"error": "Not found."}), 404
    if not _can_write(kb, user_id):
        return jsonify({"error": "Forbidden: only the owner can modify this knowledge base."}), 403

    data = request.get_json(force=True, silent=True) or {}
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
        # Rebuild either way: sharing must drop unreviewed vectors, unsharing
        # restores the owner's own documents.
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

    # An agent still pointing at this KB would keep a dangling name. Retrieval
    # already degrades to "no documents found" rather than erroring, so this
    # is reported, not repaired — silently rewriting someone's agent config is
    # worse than telling them.
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


# --- Documents ------------------------------------------------------------

@knowledge_bp.route('/knowledge-bases/<kb_id>/documents', methods=['POST'])
def upload_document(kb_id):
    """Extracts a file's text and stores it in the KB, then queues a rebuild.

    The extraction ceiling here is the indexer's, NOT Config.MAX_DOCUMENT_CHARS
    (50k). That limit exists to bound a single prompt; applied to indexing it
    would silently store the first chapter of a long PDF and let the agent
    answer confidently from a truncated corpus.
    """
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

    # A shared KB's uploads are unreviewed until someone else signs off.
    status = 'pending' if kb.get('visibility') in SHARED_VISIBILITIES else 'private'
    doc = db.add_knowledge_base_document(
        kb_id=kb_id, filename=file.filename, text=text,
        uploaded_by=user_id, size_bytes=size_bytes, status=status)

    if kb.get('org_id'):
        db.append_compliance_log(
            kb['org_id'], 'kb_document_uploaded', f'user:{user_id}',
            {"kb_id": kb_id, "document_id": doc["id"], "filename": file.filename,
             "sha256": doc.get("sha256"), "char_count": total_chars, "status": status})

    # Queue regardless: for a private KB this indexes the new text; for a
    # shared one it is a no-op on content but keeps status honest.
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
    # Without this the deleted document's vectors keep answering questions.
    enqueue_rebuild(kb_id)
    return jsonify({"ok": True, "knowledge_base": _shape(db.get_knowledge_base(kb_id))})


# --- Approval -------------------------------------------------------------

@knowledge_bp.route('/knowledge-bases/<kb_id>/documents/<doc_id>/review',
                    methods=['POST'])
@require_any_role(*REVIEWER_ROLES)
def review_document(kb_id, doc_id):
    """Approve or reject one document. `admin|auditor` only — see the module
    docstring for why this is set membership and not the role ladder."""
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
            reason=data.get('reason'), org_id=kb['org_id'])
    except SelfReviewError as e:
        # 403, not 400: the request was well formed, the actor was wrong.
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not updated:
        return jsonify({"error": "Not found."}), 404

    # Approval changes what may be retrieved, so the index must follow.
    from ..core.services.kb_indexer import enqueue_rebuild
    enqueue_rebuild(kb_id)

    return jsonify({"document": _shape_doc(updated),
                    "knowledge_base": _shape(db.get_knowledge_base(kb_id))})


@knowledge_bp.route('/knowledge-bases/pending-reviews', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def list_pending_reviews():
    """Every document awaiting sign-off across the org — the reviewer's inbox.

    Self-uploaded rows are included but flagged: hiding them would make the
    queue look empty to the one person who cannot clear it, which reads as
    'nothing to do' rather than 'someone else must do this'."""
    user_id, _ = _actor()
    org_id = get_current_org_id()
    if not org_id:
        return jsonify({"pending": []})

    pending = []
    for kb in db.list_knowledge_bases(user_id, org_id, get_current_role()):
        if kb.get('visibility') not in SHARED_VISIBILITIES:
            continue
        for doc in db.list_knowledge_base_documents(kb['id'], statuses=('pending',)):
            item = _shape_doc(doc)
            item['kb_id'] = kb['id']
            item['kb_name'] = kb['name']
            item['self_uploaded'] = str(doc.get('uploaded_by')) == str(user_id)
            pending.append(item)
    return jsonify({"pending": pending})
