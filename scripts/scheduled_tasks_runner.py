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


def _md_inline(escaped: str) -> str:
    """Bold and inline code only, applied to ALREADY-ESCAPED text."""
    import re as _re
    escaped = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = _re.sub(
        r"`([^`]+)`",
        r'<code style="background-color:#f5f5f5;padding:1px 4px;border-radius:3px;font-size:13px;">\1</code>',
        escaped)
    return escaped


def md_to_email_html(body: str) -> str:
    """Minimal markdown for mail clients: headings, bullets, numbered lists,
    bold, inline code, horizontal rules. Line-based and deliberately dumb —
    anything unrecognized is a paragraph. SAFETY ORDER: the raw text is
    HTML-escaped FIRST and the transforms run on escaped text, so the only
    tags in the output are the ones this function writes; a prompt-injected
    <script> arrives as visible characters."""
    import html as _html
    import re as _re

    lines = _html.escape(body).split("\n")
    out, para, bullets, numbers = [], [], [], []

    def flush_para():
        if para:
            out.append(f'<p style="margin:0 0 12px 0;">{_md_inline("<br>".join(para))}</p>')
            para.clear()

    def flush_lists():
        if bullets:
            items = "".join(f'<li style="margin:0 0 6px 0;">{_md_inline(b)}</li>' for b in bullets)
            out.append(f'<ul style="margin:0 0 12px 0;padding-left:22px;">{items}</ul>')
            bullets.clear()
        if numbers:
            items = "".join(f'<li style="margin:0 0 6px 0;">{_md_inline(n)}</li>' for n in numbers)
            out.append(f'<ol style="margin:0 0 12px 0;padding-left:22px;">{items}</ol>')
            numbers.clear()

    for raw in lines:
        line = raw.strip()
        h = _re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            flush_para(); flush_lists()
            size = {1: 20, 2: 18, 3: 16, 4: 14}[len(h.group(1))]
            out.append(f'<div style="font-size:{size}px;font-weight:bold;margin:16px 0 8px 0;">{_md_inline(h.group(2))}</div>')
        elif _re.match(r"^[-*]\s+", line):
            flush_para()
            if numbers: flush_lists()
            bullets.append(_re.sub(r"^[-*]\s+", "", line))
        elif _re.match(r"^\d+[.)]\s+", line):
            flush_para()
            if bullets: flush_lists()
            numbers.append(_re.sub(r"^\d+[.)]\s+", "", line))
        elif _re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
            flush_para(); flush_lists()
            out.append('<hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0;">')
        elif not line:
            flush_para(); flush_lists()
        else:
            flush_lists()
            para.append(line)
    flush_para(); flush_lists()
    return "".join(out)


def build_email_html(agent_name: str, body: str, date_label: str) -> str:
    """Simple branded HTML for the digest. Inline styles only (email clients
    ignore stylesheets), the official palette only (green #16a34a accent on
    the #f9f9f9 canvas). Markdown is rendered by md_to_email_html, whose
    escape-first order is the injection defense."""
    import html as _html
    paragraphs = md_to_email_html(body)
    safe_agent = _html.escape(agent_name)
    return f"""\
<html><body style="margin:0;padding:0;background-color:#f9f9f9;">
  <div style="max-width:640px;margin:0 auto;padding:24px 16px;font-family:Arial,Helvetica,sans-serif;color:#171717;">
    <div style="background-color:#16a34a;border-radius:8px 8px 0 0;padding:14px 20px;">
      <span style="color:#ffffff;font-size:16px;font-weight:bold;">SAFi</span>
      <span style="color:#dcfce7;font-size:13px;"> &nbsp;·&nbsp; Scheduled update</span>
    </div>
    <div style="background-color:#ffffff;border:1px solid #e5e5e5;border-top:none;border-radius:0 0 8px 8px;padding:20px;">
      <div style="font-size:14px;font-weight:bold;color:#15803d;margin-bottom:2px;">{safe_agent}</div>
      <div style="font-size:12px;color:#737373;margin-bottom:16px;">{_html.escape(date_label)}</div>
      <div style="font-size:14px;line-height:1.6;">{paragraphs}</div>
    </div>
    <p style="font-size:11px;color:#a3a3a3;margin:12px 4px 0;">
      Produced as a governed turn. The full audit record and this conversation
      are available in your SAFi workspace.
    </p>
  </div>
</body></html>"""


def send_email(config, to_addr: str, subject: str, body: str,
               agent_name: str = "", date_label: str = "") -> None:
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)  # plain-text part stays the canonical fallback
    msg.add_alternative(build_email_html(agent_name or "SAFi agent", body,
                                         date_label), subtype="html")
    # Port decides the transport: 465 is implicit TLS from the first byte
    # (SMTP_SSL); anything else is plaintext upgraded via STARTTLS. Gmail
    # serves both; the demo host's proven credentials use 465.
    if int(config.SMTP_PORT) == 465:
        ctx = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
    else:
        ctx = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
    with ctx as s:
        if int(config.SMTP_PORT) != 465:
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
    date_label = datetime.now(_tz.utc).astimezone(tz).strftime("%A, %B %d, %Y")
    try:
        send_email(Config, to_addr, f"[SAFi] {agent_name} — scheduled update",
                   output, agent_name=agent_name, date_label=date_label)
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
