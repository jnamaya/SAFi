"""
Document upload and text extraction.

POST /api/documents/extract takes a multipart file upload and returns its
extracted text for injection into the user's prompt. The uploaded file is
never stored — only a sha256 digest of it.
"""
from flask import Blueprint, session, jsonify, request, current_app
from ..config import Config
from ..persistence import database as db
from ..core.rbac import get_current_org_id
import hashlib

documents_bp = Blueprint('documents', __name__)


def get_user_id():
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')


@documents_bp.route('/documents/extract', methods=['POST'])
def extract_document_text():
    """multipart/form-data upload with a 'file' field.

    Response: JSON with 'text', 'filename', 'sha256', 'bytes',
    'total_chars', 'was_truncated', 'chars_used'.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file provided."}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    from ..core.services.document_processor import allowed_file, extract_text

    if not allowed_file(file.filename):
        allowed = ', '.join(Config.ALLOWED_UPLOAD_EXTENSIONS)
        return jsonify({
            "error": f"Unsupported file type. Allowed: {allowed}"
        }), 400

    file.seek(0, 2)
    size_bytes = file.tell()
    size_mb = size_bytes / (1024 * 1024)
    file.seek(0)

    if size_mb > Config.MAX_UPLOAD_SIZE_MB:
        return jsonify({
            "error": f"File too large ({size_mb:.1f}MB). Maximum: {Config.MAX_UPLOAD_SIZE_MB}MB"
        }), 400

    # Digest the bytes before extraction consumes the stream: this is the whole
    # provenance record. The file itself is deliberately NOT stored — the text
    # already lands encrypted in chat_history and the audit trail, so keeping
    # the original would mean a second copy of the same sensitive data needing
    # its own purge, legal-hold and export coverage. A digest answers the
    # question that actually gets asked — "is this the document the agent
    # read?" — for 64 characters.
    file.seek(0)
    digest = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)

    try:
        text, total_chars = extract_text(
            file,
            file.filename,
            max_chars=Config.MAX_DOCUMENT_CHARS
        )

        truncated = total_chars > Config.MAX_DOCUMENT_CHARS
        current_app.logger.info(
            f"Document extracted: {file.filename} | "
            f"{total_chars:,} chars | sha256:{digest[:12]} | User: {user_id}"
        )

        # Org-level evidence, matching a knowledge-base upload: feeding a
        # document into a governed agent is governance-relevant (see backlog 21b).
        try:
            org_id = get_current_org_id()
            if org_id:
                db.append_compliance_log(org_id, 'chat_document_attached', f"user:{user_id}", {
                    "filename": file.filename,
                    "sha256": digest,
                    "bytes": size_bytes,
                    "chars": total_chars,
                    "truncated_to": Config.MAX_DOCUMENT_CHARS if truncated else None,
                })
        except Exception as e:
            # Evidence must not cost the user their upload.
            current_app.logger.error(f"Could not log document attachment: {e}")

        return jsonify({
            "text": text,
            "filename": file.filename,
            "sha256": digest,
            "bytes": size_bytes,
            "total_chars": total_chars,
            "was_truncated": truncated,
            "chars_used": min(total_chars, Config.MAX_DOCUMENT_CHARS),
        })

    except ValueError as e:
        # Known errors (unsupported format, missing dependency, empty document)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Document extraction failed: {e}")
        return jsonify({
            "error": "Failed to extract text from document."
        }), 500
