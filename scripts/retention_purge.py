#!/usr/bin/env python3
"""Data-retention purge engine (SEA 17a-4 / Advisers Act 204-2).

Destroys records whose org-configured retention period has ended. This is the
one deletion path that must NOT snapshot content into the audit trail — the
retention period is over, destruction is the point — so it uses raw SQL and
never the journaling delete helpers. Every run is evidenced in
org_compliance_log as counts and the frozen cutoff, never content.

Per org (skipping demo orgs and any org under legal hold, re-checked before
every batch):
  Phase A  conversations whose newest message is older than cutoff
           (empty ones by created_at). Trail org_id is stamped BEFORE the
           delete so the purge never manufactures unattributable chains.
  Phase B  orphaned audit-trail chains: whole chains only, and only when the
           chain's newest entry is itself past cutoff — a message created and
           deleted yesterday inside an 8-year-old conversation is 1 day into
           its OWN retention period and must survive.
  Phase C  saved_content / prompt_usage / audit_snapshots by age.
  Phase D  (global) JSONL log files older than SAFI_LOG_RETENTION_DAYS by
           filename date; skipped entirely while ANY org holds a legal hold
           (files mix orgs).

Idempotent: selection is a pure function of the frozen cutoff and current
data; a crashed run self-heals on the next run.

Usage:
  venv/bin/python scripts/retention_purge.py [--dry-run] [--org ID]
      [--batch-size 50] [--max-batches N] [--force]
      [--purge-unattributed --older-than-years N]
"""
import argparse
import json
import re
import sys
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.config import Config
from safi_app.persistence import database as db

ACTOR = "system:retention-purge"
BLAST_PCT = 0.25
BLAST_ROWS = 100_000
RETRYABLE = ("1205", "1213")  # lock wait timeout, deadlock


def get_conn():
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SET time_zone = '+00:00'")
    cur.close()
    return conn


def acquire_lock(conn):
    cur = conn.cursor()
    cur.execute("SELECT GET_LOCK('safi_retention_purge', 0)")
    got = cur.fetchone()[0] == 1
    cur.close()
    return got


def release_lock(conn):
    cur = conn.cursor()
    cur.execute("SELECT RELEASE_LOCK('safi_retention_purge')")
    cur.fetchone()
    cur.close()


def frozen_cutoff(conn, years):
    cur = conn.cursor()
    cur.execute("SELECT UTC_TIMESTAMP() - INTERVAL %s YEAR", (years,))
    cutoff = cur.fetchone()[0]
    cur.close()
    return cutoff


def legal_hold_active(org_id):
    return db.get_org_retention_config(org_id)["legal_hold"]["active"]


def any_legal_hold(orgs):
    return any(db.get_org_retention_config(o["id"])["legal_hold"]["active"] for o in orgs)


def backfill_trail_org_ids(conn):
    """Incremental attribution of trail entries to orgs. Pass 1 is exact (via
    live conversations); pass 2 approximates via the acting user for chains
    whose conversation is already gone."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE chat_audit_trail t "
        "JOIN conversations c ON c.id = t.conversation_id "
        "JOIN users u ON u.id = c.user_id "
        "SET t.org_id = u.org_id WHERE t.org_id IS NULL AND u.org_id IS NOT NULL"
    )
    pass1 = cur.rowcount
    cur.execute(
        "UPDATE chat_audit_trail t "
        "JOIN users u ON u.id = SUBSTRING(t.actor, 6) "
        "SET t.org_id = u.org_id "
        "WHERE t.org_id IS NULL AND t.actor LIKE 'user:%' AND u.org_id IS NOT NULL"
    )
    pass2 = cur.rowcount
    conn.commit()
    cur.close()
    if pass1 or pass2:
        print(f"  trail org_id backfill: {pass1} via conversations, {pass2} via actors")


def select_conversation_batch(cur, org_id, cutoff, batch_size):
    cur.execute(
        "SELECT c.id FROM conversations c "
        "JOIN users u ON u.id = c.user_id "
        "LEFT JOIN chat_history ch ON ch.conversation_id = c.id "
        "WHERE u.org_id = %s AND u.id NOT LIKE 'demo\\_%' "
        "GROUP BY c.id, c.created_at "
        "HAVING COALESCE(MAX(ch.timestamp), c.created_at) < %s "
        "LIMIT %s",
        (org_id, cutoff, batch_size),
    )
    return [r[0] for r in cur.fetchall()]


def count_org_conversations(cur, org_id):
    cur.execute(
        "SELECT COUNT(*) FROM conversations c JOIN users u ON u.id = c.user_id "
        "WHERE u.org_id = %s AND u.id NOT LIKE 'demo\\_%'", (org_id,),
    )
    return cur.fetchone()[0]


def dry_run_counts(conn, org_id, cutoff):
    """Read-only preview of exactly what a real run would destroy."""
    cur = conn.cursor()
    counts = {}
    cur.execute(
        "SELECT COUNT(DISTINCT c.id), COUNT(ch.id) FROM conversations c "
        "JOIN users u ON u.id = c.user_id "
        "LEFT JOIN chat_history ch ON ch.conversation_id = c.id "
        "WHERE u.org_id = %s AND u.id NOT LIKE 'demo\\_%' "
        "AND c.id IN ("
        "  SELECT id FROM (SELECT c2.id FROM conversations c2 "
        "  JOIN users u2 ON u2.id = c2.user_id "
        "  LEFT JOIN chat_history ch2 ON ch2.conversation_id = c2.id "
        "  WHERE u2.org_id = %s AND u2.id NOT LIKE 'demo\\_%' "
        "  GROUP BY c2.id, c2.created_at "
        "  HAVING COALESCE(MAX(ch2.timestamp), c2.created_at) < %s) x)",
        (org_id, org_id, cutoff),
    )
    counts["conversations"], counts["chat_history"] = cur.fetchone()
    # Trail chains purgeable now (orphans past cutoff) — post-A numbers will
    # be higher; this is the pre-run floor, flagged as such in output.
    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(cnt), 0) FROM ("
        "  SELECT t.message_pk, COUNT(*) AS cnt FROM chat_audit_trail t "
        "  LEFT JOIN chat_history ch ON ch.id = t.message_pk "
        "  WHERE t.org_id = %s GROUP BY t.message_pk "
        "  HAVING MAX(t.created_at) < %s AND MAX(ch.id IS NOT NULL) = 0 "
        "  AND COUNT(DISTINCT t.conversation_id) = 1) x",
        (org_id, cutoff),
    )
    counts["trail_chains_orphaned_now"], counts["trail_rows_orphaned_now"] = [int(v) for v in cur.fetchone()]
    # governance_records cascade with chat_history via FK — previewed here so
    # the dry run shows the encrypted captures a real run would reclaim.
    cur.execute(
        "SELECT COUNT(*) FROM governance_records g WHERE g.conversation_id IN ("
        "  SELECT id FROM (SELECT c2.id FROM conversations c2 "
        "  JOIN users u2 ON u2.id = c2.user_id "
        "  LEFT JOIN chat_history ch2 ON ch2.conversation_id = c2.id "
        "  WHERE u2.org_id = %s AND u2.id NOT LIKE 'demo\\_%' "
        "  GROUP BY c2.id, c2.created_at "
        "  HAVING COALESCE(MAX(ch2.timestamp), c2.created_at) < %s) x)",
        (org_id, cutoff),
    )
    counts["governance_records"] = cur.fetchone()[0]
    for table, ts_col, key in (("saved_content", "created_at", "saved_content"),
                               ("prompt_usage", "timestamp", "prompt_usage"),
                               ("audit_snapshots", "created_at", "audit_snapshots")):
        cur.execute(
            f"SELECT COUNT(*) FROM {table} s JOIN users u ON u.id = s.user_id "
            f"WHERE u.org_id = %s AND u.id NOT LIKE 'demo\\_%' AND s.{ts_col} < %s",
            (org_id, cutoff),
        )
        counts[key] = cur.fetchone()[0]
    cur.close()
    return counts


def run_batch_with_retry(conn, fn, *args):
    for attempt in range(3):
        try:
            return fn(conn, *args)
        except Exception as e:
            conn.rollback()
            if any(code in str(e) for code in RETRYABLE) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise


def purge_conversation_batch(conn, org_id, ids):
    """One transaction: stamp trail attribution, count evidence, delete."""
    cur = conn.cursor()
    placeholders = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"UPDATE chat_audit_trail SET org_id = %s "
        f"WHERE conversation_id IN ({placeholders}) AND org_id IS NULL",
        (org_id, *ids),
    )
    cur.execute(f"SELECT COUNT(*) FROM chat_history WHERE conversation_id IN ({placeholders})", tuple(ids))
    ch_rows = cur.fetchone()[0]
    # governance_records cascade with chat_history (FK); counted here so the
    # completion evidence shows how many encrypted captures were reclaimed.
    cur.execute(f"SELECT COUNT(*) FROM governance_records WHERE conversation_id IN ({placeholders})", tuple(ids))
    gov_rows = cur.fetchone()[0]
    cur.execute(f"DELETE FROM conversations WHERE id IN ({placeholders})", tuple(ids))
    conn.commit()
    cur.close()
    return ch_rows, gov_rows


def purge_trail_chains(conn, org_id, cutoff, batch_size, max_batches):
    """Phase B: whole-chain deletion of orphaned, out-of-retention chains."""
    chains = rows = skipped_recent = skipped_mixed = batches = 0
    cur = conn.cursor()
    # Anomaly counts (logged, never purged): chains mixing conversations
    # (message_pk reuse) and chains still inside their retention window.
    cur.execute(
        "SELECT COUNT(*) FROM (SELECT t.message_pk FROM chat_audit_trail t "
        "LEFT JOIN chat_history ch ON ch.id = t.message_pk WHERE t.org_id = %s "
        "GROUP BY t.message_pk HAVING MAX(ch.id IS NOT NULL) = 0 "
        "AND COUNT(DISTINCT t.conversation_id) > 1) x", (org_id,),
    )
    skipped_mixed = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM (SELECT t.message_pk FROM chat_audit_trail t "
        "LEFT JOIN chat_history ch ON ch.id = t.message_pk WHERE t.org_id = %s "
        "GROUP BY t.message_pk HAVING MAX(ch.id IS NOT NULL) = 0 "
        "AND MAX(t.created_at) >= %s) x", (org_id, cutoff),
    )
    skipped_recent = cur.fetchone()[0]
    while max_batches is None or batches < max_batches:
        cur.execute(
            "SELECT t.message_pk FROM chat_audit_trail t "
            "LEFT JOIN chat_history ch ON ch.id = t.message_pk "
            "WHERE t.org_id = %s GROUP BY t.message_pk "
            "HAVING MAX(t.created_at) < %s AND MAX(ch.id IS NOT NULL) = 0 "
            "AND COUNT(DISTINCT t.conversation_id) = 1 LIMIT %s",
            (org_id, cutoff, batch_size),
        )
        pks = [r[0] for r in cur.fetchall()]
        if not pks:
            break
        placeholders = ", ".join(["%s"] * len(pks))
        cur.execute(f"DELETE FROM chat_audit_trail WHERE message_pk IN ({placeholders})", tuple(pks))
        rows += cur.rowcount
        chains += len(pks)
        conn.commit()
        batches += 1
    cur.close()
    return chains, rows, skipped_recent, skipped_mixed


def purge_aged_table(conn, org_id, cutoff, table, ts_col, batch_size, pk="id"):
    total = 0
    cur = conn.cursor()
    while True:
        cur.execute(
            f"SELECT s.{pk} FROM {table} s JOIN users u ON u.id = s.user_id "
            f"WHERE u.org_id = %s AND u.id NOT LIKE 'demo\\_%' AND s.{ts_col} < %s LIMIT %s",
            (org_id, cutoff, batch_size * 10),
        )
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            break
        placeholders = ", ".join(["%s"] * len(ids))
        cur.execute(f"DELETE FROM {table} WHERE {pk} IN ({placeholders})", tuple(ids))
        total += cur.rowcount
        conn.commit()
    cur.close()
    return total


def purge_org(conn, org, args):
    org_id = org["id"]
    cfg = db.get_org_retention_config(org_id)
    if not cfg["valid"]:
        db.append_compliance_log(org_id, "purge_failed", ACTOR,
                                 {"error": "config_invalid", "raw": org.get("settings")})
        print(f"org {org_id}: INVALID retention config — skipped and logged")
        return
    years = cfg["retention_years"]
    if years is None:
        return  # keep forever
    if years < 1:
        print(f"org {org_id}: retention_years {years} below floor — skipped")
        return
    if cfg["legal_hold"]["active"]:
        print(f"org {org_id}: legal hold active — skipped")
        return

    cutoff = frozen_cutoff(conn, years)
    cutoff_iso = cutoff.replace(tzinfo=timezone.utc).isoformat()
    counts = dry_run_counts(conn, org_id, cutoff)

    print(f"org {org_id} \"{org.get('name', '')}\"  retention={years}y  cutoff={cutoff_iso}")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    if args.dry_run:
        return

    cur = conn.cursor()
    total_convs = count_org_conversations(cur, org_id)
    cur.close()
    est_rows = counts["chat_history"] + counts["trail_rows_orphaned_now"]
    if not args.force and total_convs and (
        counts["conversations"] / total_convs > BLAST_PCT or est_rows > BLAST_ROWS
    ):
        print(f"  REFUSED: blast radius ({counts['conversations']}/{total_convs} conversations, "
              f"~{est_rows} rows) exceeds guard — re-run with --force after reviewing the dry-run numbers")
        sys.exit(2)

    run_id = str(uuid.uuid4())
    started = time.time()
    db.append_compliance_log(org_id, "purge_started", ACTOR,
                             {"run_id": run_id, "cutoff_utc": cutoff_iso, "retention_years": years})

    done = {"conversations": 0, "chat_history": 0, "governance_records": 0}
    batches = 0
    try:
        # Phase A
        while args.max_batches is None or batches < args.max_batches:
            if legal_hold_active(org_id):
                print("  legal hold set mid-run — stopping this org")
                break
            cur = conn.cursor()
            ids = select_conversation_batch(cur, org_id, cutoff, args.batch_size)
            cur.close()
            if not ids:
                break
            ch_rows, gov_rows = run_batch_with_retry(conn, purge_conversation_batch, org_id, ids)
            done["conversations"] += len(ids)
            done["chat_history"] += ch_rows
            done["governance_records"] += gov_rows
            batches += 1

        # Phase B
        chains, trail_rows, skip_recent, skip_mixed = purge_trail_chains(
            conn, org_id, cutoff, 500, args.max_batches)

        # Phase C
        done["saved_content"] = purge_aged_table(conn, org_id, cutoff, "saved_content", "created_at", args.batch_size)
        done["prompt_usage"] = purge_aged_table(conn, org_id, cutoff, "prompt_usage", "timestamp", args.batch_size)
        done["audit_snapshots"] = purge_aged_table(conn, org_id, cutoff, "audit_snapshots", "created_at", args.batch_size, pk="hash")

        # Review-queue sweep: PENDING rows whose message this run (or an
        # earlier one) destroyed — nothing left to review. Reviewed rows are
        # deliberately kept: once the chain and its 'review' entries are
        # purged, the queue row is the disposition's last remnant, and the
        # coverage report counts it as purged.
        done["review_queue_orphans"] = db.sweep_orphaned_pending_reviews(org_id)

        db.append_compliance_log(org_id, "purge_completed", ACTOR, {
            "run_id": run_id, "cutoff_utc": cutoff_iso, "retention_years": years,
            "batches": batches, "duration_seconds": round(time.time() - started, 1),
            "counts": {**done, "chat_audit_trail_chains": chains, "chat_audit_trail_rows": trail_rows},
            "skipped": {"trail_chains_in_window": skip_recent, "trail_chains_mixed_pk": skip_mixed},
        })
        print(f"  purged: {done} + {chains} trail chains ({trail_rows} rows); "
              f"skipped recent={skip_recent} mixed={skip_mixed}")
    except Exception as e:
        db.append_compliance_log(org_id, "purge_failed", ACTOR, {
            "run_id": run_id, "cutoff_utc": cutoff_iso, "error": str(e)[:500],
            "partial_counts": done,
        })
        raise


def check_review_backlogs(args):
    """Daily queue_backlog sweep (Art. 72): every org with a review config
    gets its oldest-pending-item age checked; overdue queues journal an
    alert (and fire the org's webhook, if configured). Runs on this timer —
    not per-turn — plus opportunistically on queue reads in the API."""
    if args.dry_run:
        return
    from safi_app.core.services import review_alerts
    for org_id in db.list_orgs_with_review_enabled():
        review_alerts.check_queue_backlog(org_id)


def purge_log_files(args, orgs):
    """Phase D: global JSONL file purge by filename date."""
    days = Config.LOG_RETENTION_DAYS
    if not days:
        return
    if any_legal_hold(orgs):
        print("log files: skipped — an org has an active legal hold (files mix orgs)")
        return
    log_dir = Path(__file__).resolve().parent.parent / Config.LOG_DIR
    if not log_dir.is_dir():
        return
    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    victims = []
    for f in log_dir.glob("*.jsonl"):
        m = re.search(r"-(\d{4}-\d{2}-\d{2})\.jsonl$", f.name)
        if not m:
            continue
        try:
            fdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate < threshold:
            victims.append((f, fdate))
    if not victims:
        return
    dates = sorted(d for _, d in victims)
    if args.dry_run:
        print(f"log files: would delete {len(victims)} files ({dates[0]} .. {dates[-1]})")
        return
    for f, _ in victims:
        f.unlink()
    db.append_compliance_log(None, "log_files_purged", ACTOR, {
        "files": len(victims), "oldest": str(dates[0]), "newest": str(dates[-1]),
        "retention_days": days,
    })
    print(f"log files: deleted {len(victims)} ({dates[0]} .. {dates[-1]})")


def purge_unattributed(conn, args, orgs):
    """Manual-only sweep of pre-feature orphan chains with no derivable org.
    Refuses unless every org has finite retention, N covers the longest one,
    and no legal hold exists anywhere."""
    n = args.older_than_years
    configured = [db.get_org_retention_config(o["id"])["retention_years"] for o in orgs]
    cur0 = conn.cursor()
    # Demo sandboxes are transient (24h cleanup) and owned by demo_* users;
    # they don't count toward the every-org-has-finite-retention precondition.
    cur0.execute("SELECT COUNT(*) FROM organizations WHERE owner_id IS NULL OR owner_id NOT LIKE 'demo\\_%'")
    total_orgs = cur0.fetchone()[0]
    cur0.close()
    if len(orgs) < total_orgs or any(y is None for y in configured):
        print("REFUSED: some orgs have no (finite) retention config — unattributable chains "
              "may belong to a keep-forever org")
        sys.exit(2)
    floor = max([7] + [y for y in configured if y])
    if n < floor:
        print(f"REFUSED: --older-than-years must be >= {floor} (max configured retention, floor 7)")
        sys.exit(2)
    if any_legal_hold(orgs):
        print("REFUSED: an org has an active legal hold")
        sys.exit(2)
    cutoff = frozen_cutoff(conn, n)
    cur = conn.cursor()
    chains = rows = 0
    while True:
        cur.execute(
            "SELECT t.message_pk FROM chat_audit_trail t "
            "LEFT JOIN chat_history ch ON ch.id = t.message_pk "
            "WHERE t.org_id IS NULL GROUP BY t.message_pk "
            "HAVING MAX(t.created_at) < %s AND MAX(ch.id IS NOT NULL) = 0 "
            "AND COUNT(DISTINCT t.conversation_id) = 1 LIMIT 500",
            (cutoff,),
        )
        pks = [r[0] for r in cur.fetchall()]
        if not pks:
            break
        if args.dry_run:
            chains += len(pks)
            print(f"unattributed: would purge {chains}+ chains (dry-run stops at first batch)")
            return
        placeholders = ", ".join(["%s"] * len(pks))
        cur.execute(f"DELETE FROM chat_audit_trail WHERE message_pk IN ({placeholders})", tuple(pks))
        rows += cur.rowcount
        chains += len(pks)
        conn.commit()
    cur.close()
    if chains:
        db.append_compliance_log(None, "unattributed_purge", ACTOR, {
            "older_than_years": n, "chains": chains, "rows": rows,
        })
    print(f"unattributed: purged {chains} chains ({rows} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--org", help="restrict to one org id")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--max-batches", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="override the blast-radius guard")
    ap.add_argument("--purge-unattributed", action="store_true")
    ap.add_argument("--older-than-years", type=int, default=0)
    args = ap.parse_args()

    conn = get_conn()
    if not acquire_lock(conn):
        print("another purge run holds the lock — exiting")
        return
    try:
        orgs = db.list_orgs_with_retention()
        if args.org:
            orgs = [o for o in orgs if o["id"] == args.org]
            if not orgs:
                print(f"org {args.org} has no retention config — nothing to do")
                return
        if args.purge_unattributed:
            if not args.older_than_years:
                print("--purge-unattributed requires --older-than-years N")
                sys.exit(2)
            purge_unattributed(conn, args, orgs)
            return
        if not args.dry_run:
            backfill_trail_org_ids(conn)
        for org in orgs:
            purge_org(conn, org, args)
        if not args.org:
            purge_log_files(args, orgs)
            check_review_backlogs(args)
    finally:
        release_lock(conn)
        conn.close()


if __name__ == "__main__":
    main()
