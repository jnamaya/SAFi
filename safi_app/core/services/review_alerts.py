# safi_app/core/services/review_alerts.py
"""Art. 72 post-market monitoring: alert evaluation + webhook dispatch
(Phase E4, per docs/internal/DESIGN_REVIEW_QUEUE.md §6).

Three alert types, all thresholds org-configured in review_config.alerts:

- alignment_degradation — rolling mean of the last N approved-turn Alignment
  scores for a profile fell below the org's floor.
- drift_spike — a single turn's drift crossed the org's threshold
  (the review queue row is the work item; this alert is the org-visible push).
- queue_backlog — the oldest pending review item exceeded the org's max age.
  Checked opportunistically on queue reads and by the daily retention timer,
  never per-turn.

Delivery contract: every alert journals to the append-only review_alerts
table and renders in-app regardless of webhook config — compute-on-read is
the floor, push is the upgrade. When alerts.webhook_url is set, the alert is
POSTed as JSON with an X-SAFi-Signature: sha256=<hmac-sha256(body)> header
keyed by the platform-level SAFI_WEBHOOK_SECRET env var (10s timeout, one
retry). The journal row is written AFTER dispatch with the final outcome, so
the table stays strictly append-only (no update helper exists).

Callers run this off the request path: the orchestrator submits
evaluate_turn_alerts via SAFi._submit_bg (contextvars copied, so
provider_governance.active_org() still resolves); the review API runs
check_queue_backlog in a daemon thread. A failure here must never affect a
turn or a queue read — everything is wrapped.
"""
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
    """Per-turn alert evaluation for a committed governance turn.

    Only the approve and gateway commit paths call this: redirects and
    system-failure notices contribute neither an approved Alignment score
    nor a drift value, so no alert could newly fire on them."""
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

        # The rolling mean only moves when this turn added an approved score
        # (redirect-quality scores are a different rubric and stay out — same
        # rule as recent_org_profile_scores itself).
        if will_decision != "approve" or score is None:
            return
        window = alerts_cfg.get("alignment_window_turns", 20)
        avg_thr = alerts_cfg.get("alignment_avg_threshold", 6)
        scores = db.recent_org_profile_scores(org_id, profile_name, window)
        # A full window is required — a young agent's first few turns should
        # not fire a "degradation" alert about a baseline that never existed.
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
    """Backlog alert for one org. Cheap when the queue is clear."""
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
    """Dedup → dispatch → journal, in that order. The 24h cooldown is per
    (org, alert_type, profile) — detail['profile'] is None for org-level
    alerts. Dedup runs again just before the insert because dispatch can
    take up to ~20s and another thread may have journaled meanwhile."""
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
    """POSTs the alert; returns the delivered record for the journal row.
    Signature covers the exact byte body: sha256=hmac_sha256(body, secret)."""
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
    for _attempt in range(2):  # one retry
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
