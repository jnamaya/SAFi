import csv
import io
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, current_app, session, Response

from ..persistence import database as db
from ..persistence import incident_store
from ..core.rbac import require_role, get_current_org_id

incidents_bp = Blueprint('incidents', __name__)

VALID_STATUS = ("open", "assessing", "notifying", "closed")
VALID_SEVERITY = ("low", "medium", "high", "critical")
VALID_SOURCE = ("internal", "vendor")
VALID_HARM = ("notification_required", "no_substantial_harm")
VALID_EVENT_TYPES = ("assessment", "containment", "harm_determination",
                     "notification_sent", "ag_delay", "note",
                     "authority_notified", "individuals_notified",
                     "hhs_notified", "media_notified", "ce_notified")

NOTIFICATION_WINDOW_DAYS = 30
VENDOR_NOTICE_HOURS = 72

EU_CLASSES = ("general", "death_or_serious_harm", "widespread")
EU_WINDOW_DAYS = {"general": 15, "death_or_serious_harm": 10, "widespread": 2}
HIPAA_ROLES = ("covered_entity", "business_associate")
HIPAA_WINDOW_DAYS = 60
HIPAA_LARGE_BREACH = 500


def _parse_dt(value):
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


def _deadline_clock(key, label, regime, aware, notified, due, now, window_days):
    clock = {"key": key, "label": label, "regime": regime, "state": "running",
             "window_days": window_days, "due_at": due.isoformat() if due else None,
             "days_remaining": None, "days_taken": None,
             "notified_at": notified.isoformat() if notified else None}
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


def _reg_sp_clocks(incident, now):
    clock = compute_notification_clock(incident, now=now)
    clock.update({"key": "customer_notice", "label": "Customer notice — Reg S-P (30d)",
                  "regime": "reg_sp", "window_days": NOTIFICATION_WINDOW_DAYS,
                  "notified_at": None})
    notified = _parse_dt(incident.get("customers_notified_at"))
    if notified:
        clock["notified_at"] = notified.isoformat()
    return [clock]


def _eu_ai_act_clocks(incident, now):
    aware = _parse_dt(incident.get("firm_aware_at"))
    cls = incident.get("eu_incident_class") or "general"
    days = EU_WINDOW_DAYS.get(cls, EU_WINDOW_DAYS["general"])
    due = aware + timedelta(days=days) if aware else None
    label = f"Authority report — EU AI Act Art. 73 ({days}d, {cls.replace('_', ' ')})"
    return [_deadline_clock("eu_authority", label, "eu_ai_act", aware,
                            _parse_dt(incident.get("authority_notified_at")), due, now, days)]


def _hipaa_clocks(incident, now):
    aware = _parse_dt(incident.get("firm_aware_at"))
    due60 = aware + timedelta(days=HIPAA_WINDOW_DAYS) if aware else None
    if (incident.get("hipaa_role") or "covered_entity") == "business_associate":
        return [_deadline_clock("hipaa_ce", "Covered-entity notice — HIPAA BA (60d)",
                                "hipaa", aware, _parse_dt(incident.get("ce_notified_at")),
                                due60, now, HIPAA_WINDOW_DAYS)]
    clocks = [_deadline_clock("hipaa_individuals", "Individual notices — HIPAA (60d)",
                              "hipaa", aware, _parse_dt(incident.get("individuals_notified_at")),
                              due60, now, HIPAA_WINDOW_DAYS)]
    count = incident.get("affected_count")
    if count is not None and int(count) >= HIPAA_LARGE_BREACH:
        clocks.append(_deadline_clock("hipaa_hhs", "HHS notice — HIPAA ≥500 (with individual notices)",
                                      "hipaa", aware, _parse_dt(incident.get("hhs_notified_at")),
                                      due60, now, HIPAA_WINDOW_DAYS))
        clocks.append(_deadline_clock("hipaa_media", "Media notice — HIPAA ≥500 (60d)",
                                      "hipaa", aware, _parse_dt(incident.get("media_notified_at")),
                                      due60, now, HIPAA_WINDOW_DAYS))
    else:
        due = None
        if aware:
            due = datetime(aware.year, 12, 31, 23, 59, 59,
                           tzinfo=timezone.utc) + timedelta(days=HIPAA_WINDOW_DAYS)
        clocks.append(_deadline_clock("hipaa_hhs", "HHS annual log — HIPAA <500 (60d after year end)",
                                      "hipaa", aware, _parse_dt(incident.get("hhs_notified_at")),
                                      due, now, None))
    return clocks


REGIME_RULES = {
    "reg_sp": {"label": "SEC Reg S-P", "clocks": _reg_sp_clocks},
    "eu_ai_act": {"label": "EU AI Act", "clocks": _eu_ai_act_clocks},
    "hipaa": {"label": "HIPAA", "clocks": _hipaa_clocks},
}


def incident_regimes(incident):
    tags = incident.get("regimes")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = None
    if not isinstance(tags, list) or not tags:
        return ["reg_sp"]
    return [k for k in REGIME_RULES if k in tags] or ["reg_sp"]


def compute_notification_clocks(incident, now=None):
    now = now or datetime.now(timezone.utc)
    clocks = []
    for key in incident_regimes(incident):
        clocks.extend(REGIME_RULES[key]["clocks"](incident, now))
    return clocks


def _actor():
    user = session.get('user') or {}
    return user.get('id'), user.get('email')


def _mirror_to_compliance_log(org_id, event_type, actor_id, detail):
    try:
        db.append_compliance_log(org_id, event_type, f"user:{actor_id}", detail)
    except Exception as e:
        current_app.logger.error(f"incident compliance mirror failed ({event_type}): {e}")


def _validate(data, creating):
    if creating:
        if not (data.get("title") or "").strip():
            return "title is required"
        if not data.get("firm_aware_at"):
            return "firm_aware_at is required — it starts the 30-day notification clock"
    for field, allowed in (("status", VALID_STATUS), ("severity", VALID_SEVERITY),
                           ("source", VALID_SOURCE), ("harm_determination", VALID_HARM),
                           ("eu_incident_class", EU_CLASSES), ("hipaa_role", HIPAA_ROLES)):
        if data.get(field) is not None and data[field] not in allowed:
            return f"{field} must be one of {', '.join(allowed)}"
    if data.get("source") == "vendor" and not (data.get("vendor_name") or "").strip():
        return "vendor_name is required when source is 'vendor'"
    if data.get("regimes") is not None:
        tags = data["regimes"]
        if not isinstance(tags, list) or not tags:
            return "regimes must be a non-empty list"
        unknown = sorted({str(t) for t in tags} - set(REGIME_RULES))
        if unknown:
            return f"unknown regimes: {', '.join(unknown)} (valid: {', '.join(REGIME_RULES)})"
    if data.get("affected_count") is not None:
        try:
            if int(data["affected_count"]) < 0:
                return "affected_count must be a non-negative integer"
        except (ValueError, TypeError):
            return "affected_count must be a non-negative integer"
    return None


def _decorated(incident):
    regimes = incident_regimes(incident)
    incident["regimes"] = regimes
    incident["clocks"] = compute_notification_clocks(incident)
    incident["clock"] = next((c for c in incident["clocks"] if c["regime"] == "reg_sp"), None)
    return incident


@incidents_bp.route('/organizations/<org_id>/incidents', methods=['GET'])
@require_role('admin')
def list_incidents(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        rows = [_decorated(r) for r in incident_store.list_security_incidents(org_id)]
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
    if not data.get("regimes"):
        data["regimes"] = incident_store.get_org_incident_regimes(org_id)
    try:
        actor_id, actor_email = _actor()
        iid = incident_store.create_security_incident(org_id, data, actor_id, actor_email)
        _mirror_to_compliance_log(org_id, 'incident_created', actor_id, {
            "incident": iid, "title": data.get("title"),
            "severity": data.get("severity") or "medium",
            "regimes": data.get("regimes")})
        return jsonify(_decorated(incident_store.get_security_incident(org_id, iid))), 201
    except Exception as e:
        current_app.logger.error(f"Error creating incident: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incidents/<incident_id>', methods=['GET'])
@require_role('admin')
def get_incident(org_id, incident_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    try:
        incident = incident_store.get_security_incident(org_id, incident_id)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"incident": _decorated(incident),
                        "events": incident_store.list_incident_events(org_id, incident_id)})
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
        before = incident_store.get_security_incident(org_id, incident_id)
        incident = incident_store.update_security_incident(org_id, incident_id, data, actor_id, actor_email)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        if before:
            if str(before.get('status')) != str(incident.get('status')):
                _mirror_to_compliance_log(org_id, 'incident_status_changed', actor_id, {
                    "incident": incident_id, "title": incident.get("title"),
                    "from": before.get('status'), "to": incident.get('status')})
            if str(before.get('harm_determination') or '') != str(incident.get('harm_determination') or ''):
                _mirror_to_compliance_log(org_id, 'incident_harm_determination', actor_id, {
                    "incident": incident_id, "title": incident.get("title"),
                    "determination": incident.get('harm_determination')})
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
        if not incident_store.append_incident_event(org_id, incident_id, event_type, detail, actor_id, actor_email):
            return jsonify({"error": "Not found"}), 404
        incident = incident_store.get_security_incident(org_id, incident_id)
        _mirror_to_compliance_log(org_id, 'incident_notice_recorded', actor_id, {
            "incident": incident_id, "title": (incident or {}).get("title"),
            "notice": event_type})
        return jsonify({"incident": _decorated(incident),
                        "events": incident_store.list_incident_events(org_id, incident_id)})
    except Exception as e:
        current_app.logger.error(f"Error logging incident event: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@incidents_bp.route('/organizations/<org_id>/incident-regimes', methods=['GET'])
@require_role('admin')
def get_incident_regimes(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "regimes": incident_store.get_org_incident_regimes(org_id),
        "available": [{"key": k, "label": v["label"]} for k, v in REGIME_RULES.items()],
    })


@incidents_bp.route('/organizations/<org_id>/incident-regimes', methods=['PUT'])
@require_role('admin')
def update_incident_regimes(org_id):
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    if "regimes" not in data:
        return jsonify({"error": "pass regimes: [regime keys]"}), 400
    try:
        actor_id, actor_email = _actor()
        return jsonify(incident_store.set_org_incident_regimes(
            org_id, data["regimes"], actor_email or actor_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating incident regimes: {e}")
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
        incident = incident_store.get_security_incident(org_id, incident_id)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        events = incident_store.list_incident_events(org_id, incident_id)
        actor_id, actor_email = _actor()
        incident_store.append_incident_event(
            org_id, incident_id, "exported", f"Record exported as {fmt.upper()}",
            actor_id, actor_email)
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
