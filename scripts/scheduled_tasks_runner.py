#!/usr/bin/env python3
"""
Scheduled Updates runner (backlog 54): the USB-side scheduler that replaced
the /opt systemd timers.

Every minute it loads the enabled schedules, computes which are due in each
task's OWN timezone, and executes each due task as a FULL governed turn
through the orchestrator — Phase Zero, tools under the agent's policy, the
Conscience, the Will, a complete governance record in the Audit Hub — then
emails the APPROVED output to the task owner's account address.

Two boundaries hold this honest:

  * The email is USB delivery of an approved response, exactly like the
    Teams/Telegram bots delivering to a channel — never an agent tool call.
    The model cannot address, trigger, or suppress the send.
  * Recipients are not configurable: mail goes to the owner's own account
    email, resolved at send time. Broadening delivery is a governance
    decision recorded in the backlog, not a field to edit here.

Failure posture: a failed run records last_status on the task and the loop
continues. A governed VIOLATION is not a failure — the redirect the
governance produced is what gets delivered, because that is what the user
would have seen in chat.

Run modes:
    python scripts/scheduled_tasks_runner.py --loop     # the service (compose)
    python scripts/scheduled_tasks_runner.py --once     # one pass, for testing
"""
from __future__ import annotations

import argparse
import asyncio
import smtplib
import sys
import time
from datetime import datetime, timezone as _tz
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A due task fires when local time is within this many minutes AFTER the
# scheduled time (the once-per-day guard prevents doubles). The window is
# what makes a runner restart at 06:03 still deliver the 06:00 digest.
GRACE_MINUTES = 30


def task_is_due(task: dict, now_utc: datetime) -> bool:
    """Pure function so the test suite can pin the semantics.

    Due = enabled task whose local weekday is in `days`, whose local clock is
    within [time_of_day, time_of_day + GRACE_MINUTES), and which has not
    already run today (task-local today, so DST and timezones cannot double-
    or zero-fire a schedule)."""
    try:
        tz = ZoneInfo(str(task.get("timezone") or "UTC"))
    except Exception:
        tz = ZoneInfo("UTC")
    local = now_utc.astimezone(tz)

    days = {int(d) for d in str(task.get("days") or "").split(",") if d.strip().isdigit()}
    if local.weekday() not in days:
        return False

    if task.get("last_run_date") == local.strftime("%Y-%m-%d"):
        return False

    try:
        hh, mm = str(task["time_of_day"]).split(":")
        target = local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except Exception:
        return False
    delta = (local - target).total_seconds() / 60.0
    return 0 <= delta < GRACE_MINUTES


def send_email(config, to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        s.starttls()
        if config.SMTP_USERNAME:
            s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        s.send_message(msg)


def run_task(task: dict) -> None:
    from safi_app.config import Config
    from safi_app.persistence import database as db
    from safi_app.core.faculties.synderesis import get_profile
    from safi_app.core.orchestrator import SAFi
    from safi_app.core.services.provider_governance import activate_org

    tz = ZoneInfo(str(task.get("timezone") or "UTC"))
    run_date = datetime.now(_tz.utc).astimezone(tz).strftime("%Y-%m-%d")

    owner = db.get_user_details(task["user_id"]) or {}
    to_addr = (owner.get("email") or "").strip()

    try:
        prof = get_profile(task["agent_key"])
    except Exception as e:
        db.mark_scheduled_task_run(task["id"], run_date, f"error: unknown agent ({e})")
        return

    org_id = prof.get("org_id") or owner.get("org_id")
    activate_org(org_id)  # provider allow-list applies to scheduled turns too

    conversation_id = task.get("conversation_id")
    if not conversation_id:
        convo = db.create_conversation(task["user_id"])
        conversation_id = convo["id"] if isinstance(convo, dict) else convo

    saf = SAFi(
        config=Config,
        value_profile_or_list=prof,
        intellect_model=prof.get("intellect_model") or Config.INTELLECT_MODEL,
        will_model=None,
        conscience_model=prof.get("conscience_model") or Config.CONSCIENCE_MODEL,
        spirit_beta=float(prof.get("spirit_beta", 0.90)),
    )
    try:
        result = asyncio.run(saf.process_prompt(
            task["prompt"],
            task["user_id"],
            conversation_id,
            user_name=owner.get("name") or "Scheduled task",
            org_id=org_id,
            user_timezone=str(task.get("timezone") or "UTC"),
        ))
    except Exception as e:
        db.mark_scheduled_task_run(task["id"], run_date, f"error: turn failed ({e})",
                                   conversation_id=conversation_id)
        return

    output = (result or {}).get("finalOutput") or ""
    decision = (result or {}).get("willDecision") or "unknown"

    if not output:
        db.mark_scheduled_task_run(task["id"], run_date, "error: empty output",
                                   conversation_id=conversation_id)
        return

    if not Config.smtp_configured():
        db.mark_scheduled_task_run(task["id"], run_date,
                                   f"ran ({decision}); email not configured",
                                   conversation_id=conversation_id)
        return
    if not to_addr:
        db.mark_scheduled_task_run(task["id"], run_date,
                                   f"ran ({decision}); owner has no email",
                                   conversation_id=conversation_id)
        return

    agent_name = prof.get("name") or task["agent_key"]
    try:
        send_email(Config, to_addr, f"[SAFi] {agent_name} — scheduled update",
                   output)
        db.mark_scheduled_task_run(task["id"], run_date, f"sent ({decision})",
                                   conversation_id=conversation_id)
    except Exception as e:
        db.mark_scheduled_task_run(task["id"], run_date, f"error: email failed ({e})",
                                   conversation_id=conversation_id)


def one_pass() -> int:
    from safi_app.persistence import database as db
    now = datetime.now(_tz.utc)
    due = [t for t in db.fetch_enabled_scheduled_tasks() if task_is_due(t, now)]
    for task in due:
        print(f"running scheduled task {task['id']} (agent {task['agent_key']})")
        run_task(task)
    return len(due)


def main() -> None:
    ap = argparse.ArgumentParser(description="SAFi Scheduled Updates runner")
    ap.add_argument("--loop", action="store_true", help="run forever (the service mode)")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    args = ap.parse_args()

    if args.loop:
        while True:
            try:
                one_pass()
            except Exception as e:
                print(f"scheduler pass failed: {e}", file=sys.stderr)
            time.sleep(60)
    else:
        n = one_pass()
        print(f"{n} task(s) were due")


if __name__ == "__main__":
    main()
