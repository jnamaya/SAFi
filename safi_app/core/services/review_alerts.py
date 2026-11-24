import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

import requests

from ...persistence import database as db
from .provider_governance import active_org

log = logging.getLogger(__name__)

ALERT_COOLDOWN_HOURS = 24
WEBHOOK_TIMEOUT_SECONDS = 10


def evaluate_turn_alerts(profile_name, score, drift, will_decision="approve", org_id=None):
    try:
        org_id = org_id or active_org()
        if not org_id:
            return
        cfg = db.get_org_review_config(org_id)
        if not cfg.get("enabled"):
            return
        alerts_cfg = cfg.get("alerts", {})
        trig_cfg = cfg.get("triggers", {})

        drift_thr = trig_cfg.get("drift_threshold", 0.4)
        if trig_cfg.get("drift_spike") and drift is not None and drift > drift_thr:
            _record_alert(org_id, "drift_spike",
                          {"profile": profile_name, "drift": drift, "threshold": drift_thr},
                          alerts_cfg)

        if will_decision != "approve" or score is None:
            return
        window = alerts_cfg.get("alignment_window_turns", 20)
        avg_thr = alerts_cfg.get("alignment_avg_threshold", 6)
        scores = db.recent_org_profile_scores(org_id, profile_name, window)
        if len(scores) >= window:
            observed = sum(scores) / len(scores)
            if observed < avg_thr:
                _record_alert(org_id, "alignment_degradation",
                              {"profile": profile_name, "observed": round(observed, 2),
                               "threshold": avg_thr, "window_turns": window},
                              alerts_cfg)
    except Exception:
        log.exception("Alert evaluation failed — turn unaffected.")


def check_queue_backlog(org_id):
    try:
        cfg = db.get_org_review_config(org_id)
        if not cfg.get("enabled"):
            return
        alerts_cfg = cfg.get("alerts", {})
        max_days = alerts_cfg.get("backlog_max_age_days", 14)
        oldest = db.oldest_pending_review_age_days(org_id)
        if oldest is not None and oldest > max_days:
            _record_alert(org_id, "queue_backlog",
                          {"profile": None, "oldest_days": int(oldest), "max_age_days": max_days},
                          alerts_cfg)
    except Exception:
        log.exception("Queue backlog check failed for org %s.", org_id)


def _record_alert(org_id, alert_type, detail, alerts_cfg):
    profile = detail.get("profile")
    if db.recent_alert_exists(org_id, alert_type, profile, ALERT_COOLDOWN_HOURS):
        return None
    url = (alerts_cfg or {}).get("webhook_url")
    if url:
        delivered = _dispatch_webhook(org_id, alert_type, detail, url)
    else:
        delivered = {"webhook": "unconfigured"}
    if db.recent_alert_exists(org_id, alert_type, profile, ALERT_COOLDOWN_HOURS):
        return None
    alert_id = db.insert_review_alert(org_id, alert_type, detail, delivered)
    log.warning("Review alert [%s] org=%s detail=%s delivered=%s",
                alert_type, org_id, detail, delivered)
    return alert_id


def _dispatch_webhook(org_id, alert_type, detail, url):
    body = json.dumps({
        "source": "safi.review_alerts",
        "alert_type": alert_type,
        "org_id": org_id,
        "detail": detail,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, sort_keys=True)
    headers = {"Content-Type": "application/json"}
    secret = os.environ.get("SAFI_WEBHOOK_SECRET")
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["X-SAFi-Signature"] = f"sha256={sig}"
    outcome = "failed:unknown"
    for _attempt in range(2):
        try:
            resp = requests.post(url, data=body.encode("utf-8"), headers=headers,
                                 timeout=WEBHOOK_TIMEOUT_SECONDS)
            if 200 <= resp.status_code < 300:
                outcome = "ok"
                break
            outcome = f"failed:{resp.status_code}"
        except requests.RequestException as e:
            outcome = f"failed:{type(e).__name__}"
    return {"webhook": outcome, "signed": bool(secret)}
