"""
Voice input API.

Accepts an audio upload, transcribes it locally to text, and returns the text.
The frontend puts that text into the composer and the user sends it through the
normal governed pipeline, so the transcript, not the audio, is what Phase Zero
scans and what lands in the audit record. Raw audio is never sent to a model and
is not stored. This mirrors documents.py (upload -> extracted text -> composer).
"""
import hashlib

from flask import Blueprint, session, jsonify, request, current_app

from ..config import Config
from ..persistence import database as db
from ..core.rbac import get_current_org_id

audio_bp = Blueprint('audio', __name__)


def _user_id():
    user = session.get('user')
    if not user:
        return None
    return user.get('sub') or user.get('id')


@audio_bp.route('/audio/transcribe', methods=['POST'])
def transcribe_audio():
    """multipart/form-data with a 'file' audio field -> {text, sha256, chars}."""
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401

    # Feature gate. Off by default; the app-config flag keeps the mic button
    # hidden, and this is the server-side enforcement behind it.
    if not Config.VOICE_INPUT_ENABLED:
        return jsonify({"error": "Voice input is not enabled on this deployment."}), 404

    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({"error": "No audio provided."}), 400

    audio = request.files['file']

    # Size check before reading the bytes into memory. MAX_CONTENT_LENGTH is the
    # framework-level backstop; this gives a clean, specific message.
    audio.seek(0, 2)
    size_bytes = audio.tell()
    audio.seek(0)
    if size_bytes > Config.MAX_AUDIO_SIZE_MB * 1024 * 1024:
        size_mb = size_bytes / (1024 * 1024)
        return jsonify({
            "error": f"Audio too large ({size_mb:.1f}MB). Maximum: {Config.MAX_AUDIO_SIZE_MB}MB."
        }), 400

    data = audio.read()
    digest = hashlib.sha256(data).hexdigest()

    from ..core.services.transcription import transcribe, TranscriptionError
    try:
        text = transcribe(data, audio.filename)
    except TranscriptionError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Audio transcription failed: {e}")
        return jsonify({"error": "Transcription failed."}), 500

    # Org-level provenance, same spirit as the document-attach evidence. The
    # transcript is governed and audited when the user sends it; here we only note
    # that an audio input was transcribed, with its digest, without storing audio.
    try:
        org_id = get_current_org_id()
        if org_id:
            db.append_compliance_log(org_id, 'chat_audio_transcribed', f"user:{user_id}", {
                "sha256": digest,
                "bytes": size_bytes,
                "chars": len(text),
            })
    except Exception as e:
        current_app.logger.error(f"Could not log audio transcription: {e}")

    return jsonify({"text": text, "sha256": digest, "chars": len(text)})
