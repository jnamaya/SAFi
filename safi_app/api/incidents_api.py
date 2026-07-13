# safi_app/api/incidents_api.py
"""Security-incident registry API (SEC Reg S-P, 17 CFR 248.30).

Org-scoped, admin-only. SAFi records incidents, tracks the three required
incident-response program elements (assessment, containment, notification),
and computes the 30-day customer-notification clock on read. SAFi does NOT
send notices — the firm sends them through its own channels and logs a
'notification_sent' event here as evidence.

Auditor read access is a one-word change (require_role('auditor') on the GET
routes) when that phase arrives — the role hierarchy already supports it.
"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, current_app, session, Response

from ..persistence import database as db
from ..core.rbac import require_role, get_current_org_id

incidents_bp = Blueprint('incidents', __name__)

VALID_STATUS = ("open", "assessing", "notifying", "closed")
VALID_SEVERITY = ("low", "medium", "high", "critical")
VALID_SOURCE = ("internal", "vendor")
VALID_HARM = ("notification_required", "no_substantial_harm")
VALID_EVENT_TYPES = ("assessment", "containment", "harm_determination",
                     "notification_sent", "ag_delay", "note")

NOTIFICATION_WINDOW_DAYS = 30
VENDOR_NOTICE_HOURS = 72


def _parse_dt(value):
    """Accepts datetime, ISO string, or MySQL 'YYYY-MM-DD HH:MM:SS'. Returns
    an aware UTC datetime or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_notification_clock(incident, now=None):
    """Pure 30-day-clock computation for one incident row.

    States: 'excepted' (documented no-substantial-harm determination),
    'notified' (customers_notified_at set), 'overdue', or 'running'.
    The due date is firm_aware_at + 30 days, extended to ag_delay_until while
    an Attorney-General delay is in effect and later than day 30.
    """
    now = now or datetime.now(timezone.utc)
    clock = {"state": "running", "due_at": None, "days_remaining": None,
             "days_taken": None, "vendor_notice_hours": None, "vendor_notice_late": None}

    v_aware = _parse_dt(incident.get("vendor_aware_at"))
    v_notified = _parse_dt(incident.get("vendor_notified_firm_at"))
    if v_aware and v_notified:
        hours = (v_notified - v_aware).total_seconds() / 3600.0
        clock["vendor_notice_hours"] = round(hours, 1)
        clock["vendor_notice_late"] = hours > VENDOR_NOTICE_HOURS

    aware = _parse_dt(incident.get("firm_aware_at"))
    notified = _parse_dt(incident.get("customers_notified_at"))

    if incident.get("harm_determination") == "no_substantial_harm":
        clock["state"] = "excepted"
        return clock

    due = None
    if aware:
        due = aware + timedelta(days=NOTIFICATION_WINDOW_DAYS)
        if incident.get("ag_delay"):
            ag_until = _parse_dt(incident.get("ag_delay_until"))
            if ag_until and ag_until > due:
                due = ag_until
        clock["due_at"] = due.isoformat()

    if notified:
        clock["state"] = "notified"
        if aware:
            clock["days_taken"] = (notified - aware).days
        return clock

    if due:
        remaining = (due - now).total_seconds() / 86400.0
        clock["days_remaining"] = int(remaining) if remaining >= 0 else -int(-remaining // 1)
        clock["state"] = "overdue" if remaining < 0 else "running"
    return clock


def _actor():
    user = session.get('user') or {}
    return user.get('id'), user.get('email')


def _validate(data, creating):
    if creating:
        if not (data.get("title") or "").strip():
            return "title is required"
        if not data.get("firm_aware_at"):
            return "firm_aware_at is required — it starts the 30-day notification clock"
    for field, allowed in (("status", VALID_STATUS), ("severity", VALID_SEVERITY),
                           ("source", VALID_SOURCE), ("harm_determination", VALID_HARM)):
        if data.get(field) is not None and data[field] not in allowed:
            return f"{field} must be one of {', '.join(allowed)}"
    if data.get("source") == "vendor" and not (data.get("vendor_name") or "").strip():
        return "vendor_name is required when source is 'vendor'"
    return None


def _decorated(incident):
    incident["clock"] = compute_notification_clock(incident)
    return incident


@incidents_bp.route('/organizations/<org_id>/incidents', methods=['GET'])
@require_role('admin')
def list_incidents(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        rows = [_decorated(r) for r in db.list_security_incidents(org_id)]
        return jsonify({"incidents": rows})
    except Exception as e:
        current_app.logger.error(f"Error listing incidents: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents', methods=['POST'])
@require_role('admin')
def create_incident(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    err = _validate(data, creating=True)
    if err:
        return jsonify({"error": err}), 400
    try:
        actor_id, actor_email = _actor()
        iid = db.create_security_incident(org_id, data, actor_id, actor_email)
        return jsonify(_decorated(db.get_security_incident(org_id, iid))), 201
    except Exception as e:
        current_app.logger.error(f"Error creating incident: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents/<incident_id>', methods=['GET'])
@require_role('admin')
def get_incident(org_id, incident_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        incident = db.get_security_incident(org_id, incident_id)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"incident": _decorated(incident),
                        "events": db.list_incident_events(org_id, incident_id)})
    except Exception as e:
        current_app.logger.error(f"Error fetching incident: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents/<incident_id>', methods=['PUT'])
@require_role('admin')
def update_incident(org_id, incident_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    err = _validate(data, creating=False)
    if err:
        return jsonify({"error": err}), 400
    try:
        actor_id, actor_email = _actor()
        incident = db.update_security_incident(org_id, incident_id, data, actor_id, actor_email)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        return jsonify(_decorated(incident))
    except Exception as e:
        current_app.logger.error(f"Error updating incident: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents/<incident_id>/events', methods=['POST'])
@require_role('admin')
def log_incident_event(org_id, incident_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    event_type = data.get("event_type")
    detail = (data.get("detail") or "").strip()
    if event_type not in VALID_EVENT_TYPES:
        return jsonify({"error": f"event_type must be one of {', '.join(VALID_EVENT_TYPES)}"}), 400
    if not detail:
        return jsonify({"error": "detail is required"}), 400
    try:
        actor_id, actor_email = _actor()
        if not db.append_incident_event(org_id, incident_id, event_type, detail, actor_id, actor_email):
            return jsonify({"error": "Not found"}), 404
        return jsonify({"incident": _decorated(db.get_security_incident(org_id, incident_id)),
                        "events": db.list_incident_events(org_id, incident_id)})
    except Exception as e:
        current_app.logger.error(f"Error logging incident event: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents/<incident_id>/export', methods=['GET'])
@require_role('admin')
def export_incident(org_id, incident_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv"):
        return jsonify({"error": "format must be json or csv"}), 400
    try:
        incident = db.get_security_incident(org_id, incident_id)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        events = db.list_incident_events(org_id, incident_id)
        actor_id, actor_email = _actor()
        # Chain of custody: examiner productions are themselves events.
        db.append_incident_event(org_id, incident_id, "exported",
                                 f"Record exported as {fmt.upper()}", actor_id, actor_email)
        doc = {"incident": _decorated(incident), "events": events,
               "exported_at": datetime.now(timezone.utc).isoformat(),
               "exported_by": actor_email or actor_id}
        fname = f"incident-{incident_id[:8]}.{fmt}"
        if fmt == "json":
            body = json.dumps(doc, indent=2, default=str)
            return Response(body, mimetype="application/json",
                            headers={"Content-Disposition": f"attachment; filename={fname}"})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["field", "value"])
        for k, v in incident.items():
            w.writerow([k, json.dumps(v, default=str) if isinstance(v, (dict, list)) else v])
        w.writerow([])
        w.writerow(["event_at", "event_type", "actor", "detail", "changes"])
        for e in events:
            w.writerow([e["event_at"], e["event_type"], e.get("actor_email") or e.get("actor_id"),
                        e.get("detail"), json.dumps(e.get("changes"), default=str) if e.get("changes") else ""])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        current_app.logger.error(f"Error exporting incident: {e}")
        return jsonify({"error": "Internal Server Error"}), 500
