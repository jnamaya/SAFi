"""Optional incident-management persistence, outside the governance TCB."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import database as db

_MUTABLE = [
    "title", "description", "status", "severity", "occurred_at",
    "occurred_range_end", "firm_aware_at", "source", "vendor_name",
    "vendor_aware_at", "vendor_notified_firm_at", "data_types",
    "affected_scope", "affected_user_ids", "assessment_notes",
    "containment_notes", "harm_assessment", "harm_determination",
    "ag_delay", "ag_delay_reference", "ag_delay_until",
    "regimes", "eu_incident_class", "hipaa_role", "affected_count",
]
_JSON_COLS = ("data_types", "affected_user_ids", "regimes")
_DATETIME_COLS = (
    "occurred_at", "occurred_range_end", "firm_aware_at",
    "vendor_aware_at", "vendor_notified_firm_at", "ag_delay_until",
)
_REGIME_KEYS = ("reg_sp", "eu_ai_act", "hipaa")
_EVENT_STAMPS = {
    "notification_sent": "customers_notified_at",
    "authority_notified": "authority_notified_at",
    "individuals_notified": "individuals_notified_at",
    "hhs_notified": "hhs_notified_at",
    "media_notified": "media_notified_at",
    "ce_notified": "ce_notified_at",
}


def init_schema():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_incidents (
                id CHAR(36) PRIMARY KEY,
                org_id CHAR(36) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                severity VARCHAR(20) DEFAULT 'medium',
                occurred_at DATETIME NULL,
                occurred_range_end DATETIME NULL,
                firm_aware_at DATETIME NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'internal',
                vendor_name VARCHAR(255) NULL,
                vendor_aware_at DATETIME NULL,
                vendor_notified_firm_at DATETIME NULL,
                data_types JSON,
                affected_scope TEXT,
                affected_user_ids JSON,
                assessment_notes TEXT,
                containment_notes TEXT,
                harm_assessment TEXT,
                harm_determination VARCHAR(40) NULL,
                harm_determined_by VARCHAR(255) NULL,
                harm_determined_at DATETIME NULL,
                ag_delay BOOLEAN DEFAULT FALSE,
                ag_delay_reference VARCHAR(500) NULL,
                ag_delay_until DATETIME NULL,
                customers_notified_at DATETIME NULL,
                regimes JSON NULL,
                eu_incident_class VARCHAR(40) NULL,
                hipaa_role VARCHAR(20) NULL,
                affected_count INT NULL,
                authority_notified_at DATETIME NULL,
                individuals_notified_at DATETIME NULL,
                hhs_notified_at DATETIME NULL,
                media_notified_at DATETIME NULL,
                ce_notified_at DATETIME NULL,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_incident_org (org_id)
            )
        """)
        cursor.execute("SHOW COLUMNS FROM security_incidents LIKE 'regimes'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN regimes JSON NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN eu_incident_class VARCHAR(40) NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN hipaa_role VARCHAR(20) NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN affected_count INT NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN authority_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN individuals_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN hhs_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN media_notified_at DATETIME NULL")
            cursor.execute("ALTER TABLE security_incidents ADD COLUMN ce_notified_at DATETIME NULL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_events (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                incident_id CHAR(36) NOT NULL,
                org_id CHAR(36) NOT NULL,
                event_type VARCHAR(40) NOT NULL,
                detail TEXT,
                changes JSON,
                actor_id VARCHAR(255),
                actor_email VARCHAR(255),
                event_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ievent_incident (incident_id),
                INDEX idx_ievent_org (org_id)
            )
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _store_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return value
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _store_value(column, value):
    if column in _JSON_COLS:
        return json.dumps(value) if value is not None else None
    if column in _DATETIME_COLS:
        return _store_datetime(value)
    return value


def _append_event(cursor, org_id, incident_id, event_type, detail, actor_id, actor_email, changes=None):
    cursor.execute(
        "INSERT INTO incident_events "
        "(incident_id, org_id, event_type, detail, changes, actor_id, actor_email) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (incident_id, org_id, event_type, detail, json.dumps(changes) if changes else None,
         actor_id, actor_email),
    )


def _decode_incident(row):
    if row:
        for column in _JSON_COLS:
            if isinstance(row.get(column), str):
                try:
                    row[column] = json.loads(row[column])
                except (ValueError, TypeError):
                    pass
    return row


def create_security_incident(org_id, data, actor_id, actor_email):
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        incident_id = str(uuid.uuid4())
        columns, values = ["id", "org_id", "created_by"], [incident_id, org_id, actor_id]
        for column in _MUTABLE:
            if column in data and data[column] is not None:
                columns.append(column)
                values.append(_store_value(column, data[column]))
        cursor.execute(
            f"INSERT INTO security_incidents ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(values))})",
            tuple(values),
        )
        _append_event(cursor, org_id, incident_id, "created",
                      f"Incident opened: {data.get('title', '')}", actor_id, actor_email)
        conn.commit()
        return incident_id
    finally:
        cursor.close()
        conn.close()


def list_security_incidents(org_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE org_id=%s ORDER BY firm_aware_at DESC",
                       (org_id,))
        return [_decode_incident(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def get_security_incident(org_id, incident_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE id=%s AND org_id=%s",
                       (incident_id, org_id))
        return _decode_incident(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()


def update_security_incident(org_id, incident_id, changes, actor_id, actor_email):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM security_incidents WHERE id=%s AND org_id=%s FOR UPDATE",
                       (incident_id, org_id))
        current = cursor.fetchone()
        if not current:
            return None
        diff, sets, values = {}, [], []
        for column in _MUTABLE:
            if column not in changes:
                continue
            new_value = changes[column]
            stored = _store_value(column, new_value)
            old = current.get(column)
            old_cmp = old if isinstance(old, bool) else (str(old) if old is not None else None)
            new_cmp = str(stored) if stored is not None else None
            if column == "ag_delay":
                new_cmp = bool(new_value)
                old_cmp = bool(old)
                stored = new_cmp
            if old_cmp != new_cmp:
                diff[column] = {"from": old if not isinstance(old, bytes) else str(old), "to": new_value}
                sets.append(f"{column}=%s")
                values.append(stored)
        if "harm_determination" in diff and changes.get("harm_determination"):
            sets.extend(["harm_determined_by=%s", "harm_determined_at=UTC_TIMESTAMP()"])
            values.append(actor_email or actor_id)
        if sets:
            values.extend([incident_id, org_id])
            cursor.execute(
                f"UPDATE security_incidents SET {', '.join(sets)} WHERE id=%s AND org_id=%s",
                tuple(values),
            )
            event_type = "status_changed" if "status" in diff else (
                "harm_determination" if "harm_determination" in diff else "updated"
            )
            _append_event(cursor, org_id, incident_id, event_type, None,
                          actor_id, actor_email, changes=diff)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_security_incident(org_id, incident_id)


def append_incident_event(org_id, incident_id, event_type, detail, actor_id, actor_email):
    stamp_column = _EVENT_STAMPS.get(event_type)
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT {stamp_column or 'id'} FROM security_incidents WHERE id=%s AND org_id=%s FOR UPDATE",
            (incident_id, org_id),
        )
        row = cursor.fetchone()
        if not row:
            return False
        if stamp_column and row[0] is None:
            cursor.execute(
                f"UPDATE security_incidents SET {stamp_column}=UTC_TIMESTAMP() "
                "WHERE id=%s AND org_id=%s", (incident_id, org_id),
            )
        _append_event(cursor, org_id, incident_id, event_type, detail, actor_id, actor_email)
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()


def list_incident_events(org_id, incident_id):
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM incident_events WHERE incident_id=%s AND org_id=%s ORDER BY id ASC",
            (incident_id, org_id),
        )
        rows = cursor.fetchall()
        for row in rows:
            if isinstance(row.get("changes"), str):
                try:
                    row["changes"] = json.loads(row["changes"])
                except (ValueError, TypeError):
                    pass
        return rows
    finally:
        cursor.close()
        conn.close()


def get_org_incident_regimes(org_id):
    org = db.get_organization(org_id)
    stored = ((org or {}).get("settings") or {}).get("incident_regimes")
    if isinstance(stored, list) and stored:
        kept = [key for key in _REGIME_KEYS if key in stored]
        if kept:
            return kept
    return ["reg_sp"]


def set_org_incident_regimes(org_id, regimes, actor):
    if not isinstance(regimes, list) or not regimes:
        raise ValueError("regimes must be a non-empty list of regime keys")
    unknown = sorted({str(value) for value in regimes} - set(_REGIME_KEYS))
    if unknown:
        raise ValueError(f"unknown regimes: {', '.join(unknown)}")
    regimes = [key for key in _REGIME_KEYS if key in {str(value) for value in regimes}]
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT settings FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("organization not found")
        settings = {}
        if row[0]:
            try:
                settings = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (ValueError, TypeError):
                settings = {}
        old = settings.get("incident_regimes")
        old = [key for key in _REGIME_KEYS if isinstance(old, list) and key in old] or None
        if old != regimes:
            settings["incident_regimes"] = regimes
            db.append_compliance_log(
                org_id, "incident_regimes_changed", actor,
                {"changed": {"incident_regimes": {"old": old, "new": regimes}}},
                cursor=cursor,
            )
            cursor.execute("UPDATE organizations SET settings=%s WHERE id=%s",
                           (json.dumps(settings), org_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return {"regimes": get_org_incident_regimes(org_id)}
