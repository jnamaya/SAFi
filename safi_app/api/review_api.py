# safi_app/api/review_api.py
"""Human review queue API (Phase E2): FINRA 3110/3120 supervisory review and
EU AI Act Art. 14 human oversight over sampled governance turns.

Org-scoped. The reviewer set is an explicit role check — admin|auditor —
not the rbac hierarchy: editors rank above auditors but content authors
don't supervise themselves. Config changes are admin-only and go through
db.set_org_review_config so the evidence log can never be skipped.

Review is post-hoc supervision, never a delivery gate: an override does NOT
retract a delivered message — it is the documented supervisory determination
about it. Each disposition rides the message's chat_audit_trail hash chain
('review' entry, same transaction as the queue-state change), so the sign-off
inherits the same tamper-evidence as the record it supervises.
"""
import csv
import io
import json
import threading
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, current_app, session, Response

from ..persistence import database as db
from ..core.rbac import require_role, require_any_role, get_current_org_id
from ..core.services import review_alerts

review_bp = Blueprint('review', __name__)

REVIEWER_ROLES = ("admin", "auditor")
VALID_STATUS = ("pending", "approved", "overridden")
VALID_TRIGGERS = ("hard_gate_block", "gateway_violation", "low_alignment",
                  "drift_spike", "random_sample")
REPORT_DEFAULT_WINDOW_DAYS = 30


def _actor():
    user = session.get('user') or {}
    return user.get('id'), user.get('email')


def _org_forbidden(org_id):
    return str(org_id) != str(get_current_org_id())


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


@review_bp.route('/organizations/<org_id>/review/queue', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def list_queue(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    status = request.args.get("status")
    trigger = request.args.get("trigger")
    if status and status not in VALID_STATUS:
        return jsonify({"error": f"status must be one of {', '.join(VALID_STATUS)}"}), 400
    if trigger and trigger not in VALID_TRIGGERS:
        return jsonify({"error": f"trigger must be one of {', '.join(VALID_TRIGGERS)}"}), 400
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400
    try:
        rows, total = db.list_review_queue(
            org_id, status=status, trigger=trigger,
            profile=request.args.get("profile"), limit=limit, offset=offset)
        # Opportunistic queue_backlog check (design §6): off the request
        # thread so a slow webhook can never delay the queue read.
        threading.Thread(target=review_alerts.check_queue_backlog,
                         args=(org_id,), daemon=True).start()
        return jsonify({"items": rows, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        current_app.logger.error(f"Error listing review queue: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@review_bp.route('/organizations/<org_id>/review/queue/<int:queue_id>', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def get_queue_item(org_id, queue_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    try:
        item = db.get_review_item(org_id, queue_id)
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item)
    except Exception as e:
        current_app.logger.error(f"Error fetching review item: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@review_bp.route('/organizations/<org_id>/review/queue/<int:queue_id>/action', methods=['POST'])
@require_any_role(*REVIEWER_ROLES)
def act_on_queue_item(org_id, queue_id):
    """Approve or override. Override requires a reason (it becomes part of the
    hash-chained trail evidence). A non-pending row returns 409 — dispositions
    are one-shot; re-review would need a new sampled turn."""
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    action = data.get("action")
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        return jsonify({"error": "reason must be a string"}), 400
    if reason and len(reason) > 10_000:
        return jsonify({"error": "reason is too long (max 10000 chars)"}), 400
    try:
        reviewer_id, reviewer_email = _actor()
        row = db.apply_review_action(org_id, queue_id, action, reason,
                                     reviewer_id, reviewer_email)
        if row is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"item": row})
    except ValueError as e:
        code = 409 if "already reviewed" in str(e) else 400
        return jsonify({"error": str(e)}), code
    except Exception as e:
        current_app.logger.error(f"Error applying review action: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@review_bp.route('/organizations/<org_id>/review/config', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def get_config(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(db.get_org_review_config(org_id))


@review_bp.route('/organizations/<org_id>/review/config', methods=['PUT'])
@require_role('admin')
def update_config(org_id):
    """Partial update; merged server-side. Evidence-logged to
    org_compliance_log in the same transaction (auditors see every change to
    the sampling rules — thin sampling is visible, not hidden)."""
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    try:
        _, actor_email = _actor()
        return jsonify(db.set_org_review_config(org_id, request.json or {},
                                                actor_email or "unknown"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating review config: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@review_bp.route('/organizations/<org_id>/review/report', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def coverage_report(org_id):
    """Supervisory coverage for [from, to) — defaults to the last 30 days.
    format=json (default) is the dashboard read surface; format=csv downloads
    an attachment and logs 'review_report_exported' to org_compliance_log as
    chain of custody (mirroring the examiner export)."""
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv"):
        return jsonify({"error": "format must be json or csv"}), 400
    date_to = _parse_date(request.args.get("to")) or datetime.utcnow()
    date_from = _parse_date(request.args.get("from")) or (date_to - timedelta(days=REPORT_DEFAULT_WINDOW_DAYS))
    if date_from >= date_to:
        return jsonify({"error": "'from' must be earlier than 'to'"}), 400
    try:
        report = db.get_review_report(org_id, date_from, date_to)
        if fmt == "json":
            return jsonify(report)
        _, actor_email = _actor()
        db.append_compliance_log(org_id, "review_report_exported", actor_email or "unknown", {
            "range": report["range"],
            "counts": {"total_turns": report["total_turns"], "sampled": report["sampled"],
                       "reviewed": report["reviewed"]},
        })
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["field", "value"])
        for k, v in report.items():
            w.writerow([k, json.dumps(v, default=str) if isinstance(v, (dict, list)) else v])
        w.writerow([])
        w.writerow(["exported_at", datetime.now(timezone.utc).isoformat()])
        w.writerow(["exported_by", actor_email or "unknown"])
        fname = f"review-report-{org_id[:8]}-{date_from.date()}-{date_to.date()}.csv"
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        current_app.logger.error(f"Error building review report: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@review_bp.route('/organizations/<org_id>/review/alerts', methods=['GET'])
@require_any_role(*REVIEWER_ROLES)
def list_alerts(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    try:
        return jsonify({"alerts": db.list_review_alerts(org_id, limit)})
    except Exception as e:
        current_app.logger.error(f"Error listing review alerts: {e}")
        return jsonify({"error": "Internal Server Error"}), 500
