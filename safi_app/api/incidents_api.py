# safi_app/api/incidents_api.py
"""Security-incident registry API — multi-regime notification clocks.

Org-scoped, admin-only. SAFi records incidents, tracks the incident-response
program elements (assessment, containment, notification), and computes every
applicable notification clock on read from regime-keyed rule tables:

  reg_sp    — SEC Reg S-P 17 CFR 248.30: 30-day customer notice, AG delay,
              72h vendor notice, documented no-substantial-harm exception.
  eu_ai_act — Art. 73 serious-incident report to the market surveillance
              authority: 15d general / 10d death or serious harm / 2d
              widespread infringement, from awareness.
  hipaa     — Breach Notification Rule: 60d individual notices from
              discovery; ≥500 affected adds contemporaneous HHS + media
              notices; <500 goes in the HHS annual log (due 60d after
              calendar-year end); business associates instead owe the
              covered entity notice within 60d.

Which regimes apply is a tag on the incident (defaulting from the org's
incident_regimes setting). Tagging a regime means "reportable under this
regime" — an incident determined non-reportable under a regime is untagged,
which the field-diff event trail records. Rows created before regime tagging
existed read as reg_sp. SAFi does NOT send notices — the firm sends them
through its own channels and logs the matching *_notified event as evidence,
which stamps the clock's stop timestamp.

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
# The *_notified types stamp their clock's stop timestamp (first occurrence
# only) — see _EVENT_STAMP_COLS in the persistence layer.
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
HIPAA_LARGE_BREACH = 500  # ≥500 affected: media + contemporaneous HHS notice


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


def _deadline_clock(key, label, regime, aware, notified, due, now, window_days):
    """Shared running/overdue/notified state machine for the non-reg_sp
    regimes (reg_sp keeps its own function above: AG-delay extension, vendor
    72h check, and the harm-determination exception are specific to it)."""
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
        # <500 affected (or count not yet established): HHS goes in the
        # annual breach log, due 60 days after the calendar year of discovery.
        due = None
        if aware:
            due = datetime(aware.year, 12, 31, 23, 59, 59,
                           tzinfo=timezone.utc) + timedelta(days=HIPAA_WINDOW_DAYS)
        clocks.append(_deadline_clock("hipaa_hhs", "HHS annual log — HIPAA <500 (60d after year end)",
                                      "hipaa", aware, _parse_dt(incident.get("hhs_notified_at")),
                                      due, now, None))
    return clocks


# The regime-keyed rule table. Key order is display/canonical order.
REGIME_RULES = {
    "reg_sp": {"label": "SEC Reg S-P", "clocks": _reg_sp_clocks},
    "eu_ai_act": {"label": "EU AI Act", "clocks": _eu_ai_act_clocks},
    "hipaa": {"label": "HIPAA", "clocks": _hipaa_clocks},
}


def incident_regimes(incident):
    """Canonically ordered regime tags for a row. Rows created before regime
    tagging existed (regimes NULL) read as reg_sp; unknown keys are dropped."""
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
    """All live clocks for the incident's tagged regimes, in canonical order."""
    now = now or datetime.now(timezone.utc)
    clocks = []
    for key in incident_regimes(incident):
        clocks.extend(REGIME_RULES[key]["clocks"](incident, now))
    return clocks


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
    # Back-compat single-clock key: the Reg S-P clock when that regime applies.
    incident["clock"] = next((c for c in incident["clocks"] if c["regime"] == "reg_sp"), None)
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
    if not data.get("regimes"):
        data["regimes"] = db.get_org_incident_regimes(org_id)
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


@incidents_bp.route('/organizations/<org_id>/incident-regimes', methods=['GET'])
@require_role('admin')
def get_incident_regimes(org_id):
    """The org's default regime set for new incidents, plus the full rule
    catalog for the UI."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "regimes": db.get_org_incident_regimes(org_id),
        "available": [{"key": k, "label": v["label"]} for k, v in REGIME_RULES.items()],
    })


@incidents_bp.route('/organizations/<org_id>/incident-regimes', methods=['PUT'])
@require_role('admin')
def update_incident_regimes(org_id):
    """Set the org's default regime set. Evidence-logged to org_compliance_log
    in the same transaction — same contract as the provider allow-list."""
    if str(org_id) != str(get_current_org_id()):
        return jsonify({"error": "Forbidden"}), 403
    data = request.json or {}
    if "regimes" not in data:
        return jsonify({"error": "pass regimes: [regime keys]"}), 400
    try:
        actor_id, actor_email = _actor()
        return jsonify(db.set_org_incident_regimes(org_id, data["regimes"],
                                                   actor_email or actor_id))
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
