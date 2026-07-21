# safi_app/api/audit_api.py
"""Native Audit Hub API: the observe surface over governance_records.

Org-scoped, session-authenticated, admin|editor|auditor — the same auth
regime as every other tab (no dashboard JWT, no query-string credentials).
Observe stays observe: no write actions live here — dispositions belong to
the Review API. The one exception is evidence ABOUT observation: downloads
of decrypted governance data custody-log 'audit_export' (counts + filters,
never content) to org_compliance_log, mirroring the examiner export.

KPI/trend/explorer endpoints read plaintext filter/aggregate columns only;
decryption happens exclusively in the drill-down, prompt search, and export
paths (see database.py's governance-records section for the caps).
"""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, current_app, session, Response

from ..persistence import database as db
from ..core.rbac import require_any_role, get_current_org_id

audit_bp = Blueprint('audit', __name__)

OBSERVER_ROLES = ("admin", "editor", "auditor")
VALID_FILTERS = ("flagged", "approved", "redirected", "violation")
VALID_BUCKETS = ("day", "hour")
DEFAULT_WINDOW_DAYS = 30


def _org_forbidden(org_id):
    return str(org_id) != str(get_current_org_id())


def _actor_email():
    user = session.get('user') or {}
    return user.get('email') or "unknown"


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


def _common_filters():
    """Parses the filter params shared by every read endpoint. Returns
    (kwargs, error_response). Dates default to the last 30 days so an
    unbounded query never scans the whole table by accident."""
    flt = request.args.get("filter")
    if flt and flt not in VALID_FILTERS:
        return None, (jsonify({"error": f"filter must be one of {', '.join(VALID_FILTERS)}"}), 400)
    date_to = _parse_date(request.args.get("to")) or datetime.utcnow()
    date_from = _parse_date(request.args.get("from")) or (date_to - timedelta(days=DEFAULT_WINDOW_DAYS))
    if date_from >= date_to:
        return None, (jsonify({"error": "'from' must be earlier than 'to'"}), 400)
    return {
        "profile": request.args.get("profile") or None,
        "policy_id": request.args.get("policy_id") or None,
        "flt": flt,
        "date_from": date_from,
        "date_to": date_to,
    }, None


@audit_bp.route('/organizations/<org_id>/audit/filters', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_filters(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    try:
        return jsonify(db.list_governance_filters(org_id))
    except Exception as e:
        current_app.logger.error(f"Error listing audit filters: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@audit_bp.route('/organizations/<org_id>/audit/summary', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_summary(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    filters, err = _common_filters()
    if err:
        return err
    filters.pop("flt", None)  # KPIs always cover the whole window
    try:
        summary = db.governance_summary(org_id, **filters)
        summary["range"] = {"from": filters["date_from"].isoformat(),
                            "to": filters["date_to"].isoformat()}
        return jsonify(summary)
    except Exception as e:
        current_app.logger.error(f"Error building audit summary: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@audit_bp.route('/organizations/<org_id>/audit/trend', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_trend(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    bucket = request.args.get("bucket", "day")
    if bucket not in VALID_BUCKETS:
        return jsonify({"error": f"bucket must be one of {', '.join(VALID_BUCKETS)}"}), 400
    filters, err = _common_filters()
    if err:
        return err
    filters.pop("flt", None)  # the trend tracks all turns, like the KPIs
    try:
        return jsonify({"buckets": db.governance_trend(org_id, bucket=bucket, **filters)})
    except Exception as e:
        current_app.logger.error(f"Error building audit trend: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@audit_bp.route('/organizations/<org_id>/audit/events', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_events(org_id):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    filters, err = _common_filters()
    if err:
        return err
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400
    q = (request.args.get("q") or "").strip()
    try:
        if q:
            # Decrypt-scan under the hard cap; offset pagination doesn't
            # apply (matches stream newest-first up to limit).
            rows, window = db.search_governance_events(org_id, q, limit=limit, **filters)
            return jsonify({"items": rows, "total": len(rows), "window": window,
                            "limit": limit, "offset": 0, "search": q})
        rows, total = db.list_governance_events(org_id, limit=limit, offset=offset, **filters)
        return jsonify({"items": rows, "total": total, "limit": limit, "offset": offset})
    except ValueError as e:
        return jsonify({"error": str(e)}), 413
    except Exception as e:
        current_app.logger.error(f"Error listing audit events: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@audit_bp.route('/organizations/<org_id>/audit/events/<int:message_pk>', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_event_detail(org_id, message_pk):
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    try:
        detail = db.get_governance_event(org_id, message_pk)
        if not detail:
            return jsonify({"error": "Not found"}), 404
        return jsonify(detail)
    except Exception as e:
        current_app.logger.error(f"Error fetching audit event: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@audit_bp.route('/organizations/<org_id>/audit/export', methods=['GET'])
@require_any_role(*OBSERVER_ROLES)
def audit_export(org_id):
    """Filtered records download, decrypted. Custody-logs 'audit_export'
    (counts + filters, never content) BEFORE streaming — the Streamlit Hub
    was the one surface that produced records invisibly; this closes it."""
    if _org_forbidden(org_id):
        return jsonify({"error": "Forbidden"}), 403
    filters, err = _common_filters()
    if err:
        return err
    try:
        rows = db.export_governance_events(org_id, **filters)
    except ValueError as e:
        return jsonify({"error": str(e)}), 413
    except Exception as e:
        current_app.logger.error(f"Error exporting audit events: {e}")
        return jsonify({"error": "Internal Server Error"}), 500
    try:
        db.append_compliance_log(org_id, "audit_export", _actor_email(), {
            "count": len(rows),
            "filters": {
                "profile": filters["profile"], "policy_id": filters["policy_id"],
                "filter": filters["flt"],
                "from": filters["date_from"].isoformat(),
                "to": filters["date_to"].isoformat(),
            },
        })
    except Exception as e:
        # Custody log is the point of this surface — no evidence, no export.
        current_app.logger.error(f"audit_export custody log failed — refusing export: {e}")
        return jsonify({"error": "Internal Server Error"}), 500
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": _actor_email(),
        "org_id": org_id,
        "count": len(rows),
        "records": rows,
    }
    fname = f"safi-audit-export-{org_id[:8]}-{filters['date_from'].date()}-{filters['date_to'].date()}.json"
    return Response(json.dumps(payload, indent=2, default=str), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})
