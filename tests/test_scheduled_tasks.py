"""
Scheduled Updates (backlog 54): the table, the ownership rules, and the
due-ness semantics the runner lives by.

The runner's promise: a schedule fires once per task-local day, on its own
weekdays, within a grace window after its local time — so a runner restart
at 06:03 still delivers the 06:00 digest, and neither DST nor timezones can
double- or zero-fire a task. task_is_due is a pure function precisely so
this file can pin that.

Needs the disposable stack (writes scheduled_tasks rows):
    docker compose -f docker-compose.test.yml run --rm tests -k scheduled
"""
import importlib.util
import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "safi_sched_runner", REPO_ROOT / "scripts" / "scheduled_tasks_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _task(**kw):
    base = {"time_of_day": "06:00", "days": "0,1,2,3,4", "timezone": "America/New_York",
            "last_run_date": None}
    base.update(kw)
    return base


def _utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class DueSemantics(unittest.TestCase):
    # 2026-08-17 is a Monday. 06:00 America/New_York = 10:00 UTC (EDT).

    def test_fires_at_the_scheduled_local_minute(self):
        self.assertTrue(runner.task_is_due(_task(), _utc("2026-08-17T10:00:30")))

    def test_fires_within_the_grace_window(self):
        self.assertTrue(runner.task_is_due(_task(), _utc("2026-08-17T10:29:00")))

    def test_not_before_time(self):
        self.assertFalse(runner.task_is_due(_task(), _utc("2026-08-17T09:59:00")))

    def test_not_after_the_grace_window(self):
        """Beyond the window it stays quiet until tomorrow — better a missed
        digest than one arriving hours late as if it were fresh."""
        self.assertFalse(runner.task_is_due(_task(), _utc("2026-08-17T10:31:00")))

    def test_once_per_local_day(self):
        t = _task(last_run_date="2026-08-17")
        self.assertFalse(runner.task_is_due(t, _utc("2026-08-17T10:05:00")))

    def test_respects_the_weekday_set(self):
        # 2026-08-16 was a Sunday; weekday-only task must not fire.
        self.assertFalse(runner.task_is_due(_task(), _utc("2026-08-16T10:05:00")))

    def test_weekday_is_evaluated_in_the_task_timezone(self):
        """Sunday 21:00 in Tokyo is Monday 06:00+ nowhere — but Monday 06:00
        Tokyo is still Sunday 21:00 UTC. The weekday must come from the task's
        clock, not the server's."""
        t = _task(timezone="Asia/Tokyo")  # Mon 06:00 JST = Sun 21:00 UTC
        self.assertTrue(runner.task_is_due(t, _utc("2026-08-16T21:10:00")))

    def test_garbage_timezone_and_time_fail_closed(self):
        self.assertFalse(runner.task_is_due(_task(time_of_day="nonsense"),
                                            _utc("2026-08-17T10:00:00")))
        # An unknown timezone falls back to UTC rather than crashing the loop.
        t = _task(timezone="Not/AZone", time_of_day="10:00", days="0")
        self.assertTrue(runner.task_is_due(t, _utc("2026-08-17T10:05:00")))


class TableAndOwnership(unittest.TestCase):

    def setUp(self):
        from safi_app.persistence import database as db
        self.db = db
        self.user = f"test_user_{uuid.uuid4().hex[:8]}"
        # scheduled_tasks has an FK to users; seed a real row.
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, email, name) VALUES (%s, %s, %s)",
                    (self.user, f"{self.user}@example.org", "Sched Test"))
        conn.commit(); cur.close(); conn.close()
        self.created = self.db.create_scheduled_task(
            self.user, "tutor", "Daily study plan", "06:00", "0,1,2,3,4",
            "America/New_York")

    def tearDown(self):
        conn = self.db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (self.user,))  # cascades
        conn.commit(); cur.close(); conn.close()

    def test_roundtrip(self):
        rows = self.db.fetch_scheduled_tasks(self.user)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent_key"], "tutor")
        self.assertEqual(rows[0]["time_of_day"], "06:00")

    def test_update_is_owner_scoped_and_column_limited(self):
        ok = self.db.update_scheduled_task(self.created["id"], self.user,
                                           {"enabled": 0, "last_status": "forged"})
        self.assertTrue(ok)
        row = self.db.fetch_scheduled_tasks(self.user)[0]
        self.assertEqual(int(row["enabled"]), 0)
        self.assertEqual(row["last_status"], "",
                         "runner bookkeeping columns must not be settable via update")
        self.assertFalse(self.db.update_scheduled_task(
            self.created["id"], "someone_else", {"enabled": 1}))

    def test_delete_is_owner_scoped(self):
        self.assertFalse(self.db.delete_scheduled_task(self.created["id"], "someone_else"))
        self.assertTrue(self.db.delete_scheduled_task(self.created["id"], self.user))

    def test_time_change_rearms_the_daily_guard(self):
        """Moving a schedule's time means 'fire at the new time', including
        today. Without the re-arm, editing the time after a run silently does
        nothing until tomorrow — the exact confusion this fixes."""
        self.db.mark_scheduled_task_run(self.created["id"], "2026-08-17", "sent (approve)")
        self.db.update_scheduled_task(self.created["id"], self.user,
                                      {"time_of_day": "18:00"})
        row = self.db.fetch_scheduled_tasks(self.user)[0]
        self.assertIsNone(row["last_run_date"])
        # A prompt-only edit must NOT re-arm: content changed, not the appointment.
        self.db.mark_scheduled_task_run(self.created["id"], "2026-08-17", "sent (approve)")
        self.db.update_scheduled_task(self.created["id"], self.user,
                                      {"prompt": "new prompt"})
        row = self.db.fetch_scheduled_tasks(self.user)[0]
        self.assertEqual(row["last_run_date"], "2026-08-17")

    def test_run_bookkeeping(self):
        self.db.mark_scheduled_task_run(self.created["id"], "2026-08-17",
                                        "sent (approve)", conversation_id=None)
        row = self.db.fetch_scheduled_tasks(self.user)[0]
        self.assertEqual(row["last_run_date"], "2026-08-17")
        self.assertEqual(row["last_status"], "sent (approve)")


class DeliveryIsNotAgentControlled(unittest.TestCase):
    """The governance boundary, pinned structurally: the runner resolves the
    recipient from the owner's account row at send time. No recipient column
    exists, and the model's output is body text only."""

    def test_no_recipient_column(self):
        src = (REPO_ROOT / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
        ddl_at = src.index("CREATE TABLE IF NOT EXISTS scheduled_tasks")
        ddl = src[ddl_at:src.index("''')", ddl_at)]
        self.assertNotIn("email", ddl.lower(),
                         "scheduled_tasks must not store a recipient; delivery "
                         "goes to the owner's account email, resolved at send time")

    def test_runner_resolves_owner_email_at_send_time(self):
        src = (REPO_ROOT / "scripts" / "scheduled_tasks_runner.py").read_text(encoding="utf-8")
        self.assertIn('get_user_details(task["user_id"])', src)
        self.assertIn("smtp_configured", src)


class BrandedEmailTemplate(unittest.TestCase):
    """The HTML alternative: brand palette, and above all the escape rule —
    the agent writes text, never markup, so injected HTML must arrive as
    visible characters rather than rendering in the reader's mail client."""

    def test_model_output_is_escaped(self):
        html = runner.build_email_html(
            "IT Director <b>", 'Hello <script>alert(1)</script>\n\n"quotes" & ampersands',
            "Monday, August 17, 2026")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("IT Director &lt;b&gt;", html)

    def test_brand_palette_only(self):
        html = runner.build_email_html("Agent", "Body text.", "Today")
        self.assertIn("#16a34a", html)   # the one green accent
        self.assertIn("#f9f9f9", html)   # the canvas
        for banned in ("#2563eb", "#7e22ce", "indigo", "purple"):
            self.assertNotIn(banned, html)

    def test_markdown_renders_simply(self):
        md = ("## Morning briefing\n\n"
              "**Two** items today:\n"
              "- First `code` item\n"
              "- Second item\n\n"
              "1. Step one\n"
              "2. Step two\n\n---\nDone.")
        html = runner.md_to_email_html(md)
        self.assertIn(">Morning briefing</div>", html)
        self.assertIn("<strong>Two</strong>", html)
        self.assertEqual(html.count("<li"), 4)
        self.assertIn("<ul", html)
        self.assertIn("<ol", html)
        self.assertIn("<hr", html)

    def test_markdown_rendering_still_escapes_first(self):
        """The escape-first order is the whole defense: markdown transforms
        run on escaped text, so injected tags stay visible characters even
        inside bullets and headings."""
        html = runner.md_to_email_html("## <script>x</script>\n- **<img src=x>**")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<img", html)
        self.assertIn("<strong>&lt;img src=x&gt;</strong>", html)

    def test_plain_text_stays_the_fallback(self):
        """set_content(plain) before add_alternative(html): text-only clients
        must still get the digest."""
        src = (REPO_ROOT / "scripts" / "scheduled_tasks_runner.py").read_text(encoding="utf-8")
        self.assertLess(src.index("msg.set_content(body)"),
                        src.index("msg.add_alternative"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
