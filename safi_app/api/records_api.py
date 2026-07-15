# safi_app/api/records_api.py
"""Records governance API: retention config, legal hold, compliance-log
evidence, and examiner-production export (SEA 17a-4 / Advisers Act 204-2).

Admin-only, org-scoped. Retention config changes go through
db.set_org_retention_config so the evidence log can never be skipped.
The export produces decrypted message records plus audit-trail metadata
(actions/actors/timestamps/hashes — snapshot states omitted) and logs
itself to org_compliance_log as chain of custody.
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, current_app, session, Response

from ..persistence import database as db
from ..persistence import crypto
from ..core.rbac import require_role, get_current_org_id

records_bp = Blueprint('records', __name__)

EXPORT_MESSAGE_CAP = 50_000
DECRYPT_FIELDS = ("content", "spirit_note", "conscience_ledger", "reasoning_log")


def _actor():
    user = session.get('user') or {}
    return user.get('email') or user.get('id') or 'unknown'


def _parse_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@records_bp.route('/organizations/<org_id>/retention', methods=['GET'])
@require_role('admin')
def get_retention(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(db.get_org_retention_config(org_id))


@records_bp.route('/organizations/<org_id>/retention', methods=['PUT'])
@require_role('admin')
def update_retention(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    changes = {}
    if "retention_years" in data:
        changes["retention_years"] = data["retention_years"]
    if "legal_hold" in data:
        changes["legal_hold"] = data["legal_hold"]
    if not changes:
        return jsonify({"error": "nothing to change — pass retention_years and/or legal_hold"}), 400
    try:
        cfg = db.set_org_retention_config(org_id, changes, _actor())
        return jsonify(cfg)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating retention config: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@records_bp.route('/organizations/<org_id>/compliance-log', methods=['GET'])
@require_role('admin')
def compliance_log(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
        return jsonify({"events": db.list_compliance_log(org_id, limit)})
    except Exception as e:
        current_app.logger.error(f"Error listing compliance log: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@records_bp.route('/organizations/<org_id>/records/export', methods=['GET'])
@require_role('admin')
def export_records(org_id):
    """Examiner production: all message records in [from, to) for the org
    (optionally one user), decrypted, with trail metadata as integrity
    evidence. JSON attachment; the export itself is logged."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    date_from = _parse_date(request.args.get("from"))
    date_to = _parse_date(request.args.get("to"))
    if not date_from or not date_to or date_from >= date_to:
        return jsonify({"error": "valid 'from' and 'to' dates are required (ISO, from < to)"}), 400
    user_filter = request.args.get("user_id")

    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        params = [org_id, date_from, date_to]
        user_sql = ""
        if user_filter:
            user_sql = "AND u.id = %s "
            params.append(user_filter)
        cursor.execute(
            "SELECT COUNT(*) AS n FROM chat_history ch "
            "JOIN conversations c ON c.id = ch.conversation_id "
            "JOIN users u ON u.id = c.user_id "
            f"WHERE u.org_id = %s AND ch.timestamp >= %s AND ch.timestamp < %s {user_sql}",
            tuple(params),
        )
        total = cursor.fetchone()["n"]
        if total > EXPORT_MESSAGE_CAP:
            return jsonify({"error": f"range matches {total} messages (cap {EXPORT_MESSAGE_CAP}) — narrow the date range"}), 413

        cursor.execute(
            "SELECT ch.*, c.title AS conversation_title, c.created_at AS conversation_created_at, "
            "u.email AS user_email, u.id AS user_id "
            "FROM chat_history ch "
            "JOIN conversations c ON c.id = ch.conversation_id "
            "JOIN users u ON u.id = c.user_id "
            f"WHERE u.org_id = %s AND ch.timestamp >= %s AND ch.timestamp < %s {user_sql}"
            "ORDER BY ch.conversation_id, ch.id",
            tuple(params),
        )
        rows = cursor.fetchall()

        conversations = {}
        for r in rows:
            crypto.decrypt_fields(r, DECRYPT_FIELDS)
            cid = r["conversation_id"]
            if cid not in conversations:
                conversations[cid] = {
                    "id": cid,
                    "title": r["conversation_title"],
                    "created_at": r["conversation_created_at"],
                    "user_id": r["user_id"],
                    "user_email": r["user_email"],
                    "messages": [],
                    "trail": [],
                }
            conversations[cid]["messages"].append({
                k: r[k] for k in ("id", "message_id", "role", "content", "audit_status",
                                  "conscience_ledger", "spirit_score", "drift", "spirit_note",
                                  "profile_name", "policy_id", "policy_version",
                                  "reasoning_log", "timestamp")
            })

        # Trail metadata per conversation — integrity evidence, states omitted.
        for cid, conv in conversations.items():
            cursor.execute(
                "SELECT id, message_pk, message_id, action, actor, event_at, "
                "prev_hash, entry_hash, created_at FROM chat_audit_trail "
                "WHERE conversation_id = %s ORDER BY id", (cid,),
            )
            conv["trail"] = cursor.fetchall()

        actor = _actor()
        doc = {
            "organization_id": org_id,
            "range": {"from": str(date_from), "to": str(date_to)},
            "user_filter": user_filter,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": actor,
            "counts": {"conversations": len(conversations), "messages": total,
                       "trail_entries": sum(len(c["trail"]) for c in conversations.values())},
            "note": "Audit-trail snapshot states are omitted; entry hashes allow integrity "
                    "verification against the live chat_audit_trail table. An absent chain "
                    "means the record passed its retention period and was purged — see "
                    "org_compliance_log.",
            "conversations": list(conversations.values()),
        }
        db.append_compliance_log(org_id, "examiner_export", actor, {
            "range": doc["range"], "user_filter": user_filter, "counts": doc["counts"],
        })
        fname = f"records-{org_id[:8]}-{date_from.date()}-{date_to.date()}.json"
        return Response(json.dumps(doc, indent=2, default=str), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        current_app.logger.error(f"Error exporting records: {e}")
        return jsonify({"error": "Internal Server Error"}), 500
    finally:
        cursor.close()
        conn.close()
