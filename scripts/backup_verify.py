#!/usr/bin/env python3
"""Weekly restore-verification of SAFi MySQL backups (SEA 17a-4 evidence).

A backup nobody has restored is a hope, not a backup. This script proves the
latest nightly dump from scripts/mysql_backup.sh is actually restorable and
that the restored data preserves the properties the compliance posture rests
on:

  1. The newest dump exists and is younger than MAX_DUMP_AGE_HOURS (an old
     dump means safi-backup.timer is silently broken).
  2. It restores cleanly into the scratch schema `safi_verify`.
  3. Every base table in the live database exists in the restore.
  4. Key tables are non-empty and their row counts are within tolerance of
     live (catches dumps that silently skipped rows).
  5. The chat_audit_trail hash chains verify inside the RESTORED copy —
     every entry_hash recomputes from its payload and every chain links
     prev_hash -> entry_hash with a NULL-rooted head. This is what makes the
     run compliance evidence: the backup provably preserves tamper-evidence.

The verdict is journaled to backup_verify_log in the LIVE database (append
only), so "how do you know your backups work" is answerable with dated rows.
On failure the scratch schema is kept for forensics (the next run drops it)
and the exit code is non-zero so safi-backup-verify.service lands failed.

Usage: venv/bin/python scripts/backup_verify.py [--backup-dir DIR] [--keep]
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.config import Config

import mysql.connector

SCRATCH_DB = "safi_verify"
MAX_DUMP_AGE_HOURS = 48
# Non-empty in any real deployment; counts compared against live within
# tolerance (live keeps moving between dump time and verify time).
KEY_TABLES = ["users", "organizations", "conversations", "chat_history", "chat_audit_trail"]
COUNT_TOLERANCE_PCT = 0.20
COUNT_TOLERANCE_ABS = 200

# Fields covered by entry_hash, exactly as _chat_trail_append writes them.
# org_id and created_at are deliberately outside the hash.
_HASHED_FIELDS = ("message_pk", "message_id", "conversation_id", "action",
                  "actor", "state", "event_at", "prev_hash")


def connect(database=None):
    return mysql.connector.connect(
        host=Config.DB_HOST, user=Config.DB_USER,
        password=Config.DB_PASSWORD, database=database,
    )


def newest_dump(backup_dir):
    dumps = sorted(glob.glob(os.path.join(backup_dir, "safi-*.sql.gz")))
    return dumps[-1] if dumps else None


def restore_into_scratch(dump_path):
    """gunzip -c dump | mysql safi_verify, without a shell in between."""
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as cnf:
        os.chmod(cnf.name, 0o600)
        cnf.write(f'[client]\nuser={Config.DB_USER}\npassword="{Config.DB_PASSWORD}"\n'
                  f'host={Config.DB_HOST}\n')
    try:
        gunzip = subprocess.Popen(["gunzip", "-c", dump_path], stdout=subprocess.PIPE)
        restore = subprocess.run(
            ["mysql", f"--defaults-extra-file={cnf.name}", SCRATCH_DB],
            stdin=gunzip.stdout, capture_output=True, text=True,
        )
        gunzip.stdout.close()
        if gunzip.wait() != 0:
            raise RuntimeError(f"gunzip failed on {dump_path}")
        if restore.returncode != 0:
            raise RuntimeError(f"mysql restore failed: {restore.stderr.strip()[:500]}")
    finally:
        os.unlink(cnf.name)


def base_tables(cursor, schema):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE'", (schema,))
    return {r[0] for r in cursor.fetchall()}


def row_count(cursor, schema, table):
    cursor.execute(f"SELECT COUNT(*) FROM `{schema}`.`{table}`")
    return cursor.fetchone()[0]


def verify_audit_chains(cursor):
    """Recompute every entry_hash and every prev_hash link in the restored
    chat_audit_trail. Returns (chains, entries); raises on the first break."""
    cursor.execute(
        "SELECT message_pk, message_id, conversation_id, action, actor, state, "
        "event_at, prev_hash, entry_hash, id FROM `%s`.chat_audit_trail "
        "ORDER BY message_pk, id" % SCRATCH_DB)
    chains, entries, tip = 0, 0, {}
    for row in cursor.fetchall():
        (message_pk, message_id, conversation_id, action, actor, state,
         event_at, prev_hash, entry_hash, entry_id) = row
        payload = json.dumps({
            "message_pk": message_pk, "message_id": message_id,
            "conversation_id": conversation_id, "action": action,
            "actor": actor, "state": state, "event_at": event_at,
            "prev_hash": prev_hash,
        }, sort_keys=True)
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != entry_hash:
            raise RuntimeError(f"audit trail entry id={entry_id}: entry_hash does not recompute")
        expected_prev = tip.get(message_pk)
        if prev_hash != expected_prev:
            raise RuntimeError(
                f"audit trail entry id={entry_id}: chain break "
                f"(prev_hash={prev_hash!r}, expected {expected_prev!r})")
        if message_pk not in tip:
            chains += 1
        tip[message_pk] = entry_hash
        entries += 1
    return chains, entries


def journal_result(status, detail):
    conn = connect(Config.DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS backup_verify_log (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            verified_at VARCHAR(40) NOT NULL,
            dump_file VARCHAR(255),
            status VARCHAR(8) NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    cur.execute(
        "INSERT INTO backup_verify_log (verified_at, dump_file, status, detail) "
        "VALUES (%s, %s, %s, %s)",
        (datetime.now(timezone.utc).isoformat(), detail.get("dump_file"),
         status, json.dumps(detail)))
    conn.commit()
    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup-dir", default="/var/backups/safi")
    ap.add_argument("--keep", action="store_true",
                    help="keep the safi_verify schema after a passing run")
    args = ap.parse_args()

    detail = {}
    try:
        dump = newest_dump(args.backup_dir)
        if not dump:
            raise RuntimeError(f"no safi-*.sql.gz dumps in {args.backup_dir}")
        age_h = (time.time() - os.path.getmtime(dump)) / 3600
        detail["dump_file"] = os.path.basename(dump)
        detail["dump_bytes"] = os.path.getsize(dump)
        detail["dump_age_hours"] = round(age_h, 1)
        if age_h > MAX_DUMP_AGE_HOURS:
            raise RuntimeError(
                f"newest dump is {age_h:.0f}h old (max {MAX_DUMP_AGE_HOURS}) — "
                "safi-backup.timer is not producing backups")
        subprocess.run(["gzip", "-t", dump], check=True)

        admin = connect()
        cur = admin.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{SCRATCH_DB}`")
        cur.execute(f"CREATE DATABASE `{SCRATCH_DB}` CHARACTER SET utf8mb4")
        admin.commit()

        restore_into_scratch(dump)

        live = base_tables(cur, Config.DB_NAME)
        restored = base_tables(cur, SCRATCH_DB)
        # backup_verify_log is written by this script after the dump was taken,
        # so its absence from an older dump is expected, not a failure.
        missing = live - restored - {"backup_verify_log"}
        if missing:
            raise RuntimeError(f"tables missing from restore: {sorted(missing)}")
        detail["tables_restored"] = len(restored)

        counts = {}
        for table in KEY_TABLES:
            live_n = row_count(cur, Config.DB_NAME, table)
            rest_n = row_count(cur, SCRATCH_DB, table)
            counts[table] = {"live": live_n, "restored": rest_n}
            if rest_n == 0 and live_n > 0:
                raise RuntimeError(f"{table}: restored copy is empty (live has {live_n})")
            tolerance = max(COUNT_TOLERANCE_ABS, int(live_n * COUNT_TOLERANCE_PCT))
            if abs(live_n - rest_n) > tolerance:
                raise RuntimeError(
                    f"{table}: restored count {rest_n} vs live {live_n} "
                    f"exceeds tolerance {tolerance}")
        detail["row_counts"] = counts

        chains, entries = verify_audit_chains(cur)
        detail["audit_chains_verified"] = chains
        detail["audit_entries_verified"] = entries

        if not args.keep:
            cur.execute(f"DROP DATABASE `{SCRATCH_DB}`")
            admin.commit()
        cur.close()
        admin.close()

        journal_result("pass", detail)
        print(f"PASS: {detail['dump_file']} restored; {len(restored)} tables, "
              f"{entries} audit entries across {chains} chains verified")
        return 0
    except Exception as exc:
        detail["error"] = str(exc)
        try:
            journal_result("fail", detail)
        except Exception as journal_exc:
            print(f"ERROR: could not journal failure: {journal_exc}", file=sys.stderr)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
