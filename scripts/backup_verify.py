#!/usr/bin/env python3
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
KEY_TABLES = ["users", "organizations", "conversations", "chat_history", "chat_audit_trail"]
COUNT_TOLERANCE_PCT = 0.20
COUNT_TOLERANCE_ABS = 200

_HASHED_FIELDS = ("message_pk", "message_id", "conversation_id", "action",
                  "actor", "state", "event_at", "prev_hash")


def connect(database=None):
    return mysql.connector.connect(
        host=Config.DB_HOST, user=Config.DB_USER,
        password=Config.DB_PASSWORD, database=database,
    )


def newest_dump(backup_dir):
    dumps = sorted(glob.glob(os.path.join(backup_dir, "safi-*.sql.gz")))
    dumps = [d for d in dumps if not os.path.basename(d).startswith("safi-pre-restore-")]
    return dumps[-1] if dumps else None


def reset_scratch(cursor, schema=SCRATCH_DB):
    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
    for table in base_tables(cursor, schema):
        cursor.execute(f"DROP TABLE IF EXISTS `{schema}`.`{table}`")
    cursor.execute("SET FOREIGN_KEY_CHECKS=1")


def restore_into_scratch(dump_path, schema=SCRATCH_DB):
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as cnf:
        os.chmod(cnf.name, 0o600)
        cnf.write(f'[client]\nuser={Config.DB_USER}\npassword="{Config.DB_PASSWORD}"\n'
                  f'host={Config.DB_HOST}\n')
    try:
        gunzip = subprocess.Popen(["gunzip", "-c", dump_path], stdout=subprocess.PIPE)
        restore = subprocess.run(
            ["mysql", f"--defaults-extra-file={cnf.name}", schema],
            stdin=gunzip.stdout, capture_output=True, text=True,
        )
        gunzip.stdout.close()
        if restore.returncode != 0:
            raise RuntimeError(f"mysql restore failed: {restore.stderr.strip()[:500]}")
        gunzip_rc = gunzip.wait()
        if gunzip_rc != 0 and gunzip_rc not in (-13, 141):
            raise RuntimeError(f"gunzip failed on {dump_path} (exit {gunzip_rc})")
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


def verify_audit_chains(cursor, schema=SCRATCH_DB):
    cursor.execute(
        "SELECT message_pk, message_id, conversation_id, action, actor, state, "
        "event_at, prev_hash, entry_hash, id FROM `%s`.chat_audit_trail "
        "ORDER BY message_pk, id" % schema)
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
            status VARCHAR(16) NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    cur.execute("ALTER TABLE backup_verify_log MODIFY status VARCHAR(16) NOT NULL")
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
        reset_scratch(cur)
        admin.commit()

        restore_into_scratch(dump)

        live = base_tables(cur, Config.DB_NAME)
        restored = base_tables(cur, SCRATCH_DB)
        missing = live - restored - {"backup_verify_log"}
        if missing:
            raise RuntimeError(f"tables missing from restore: {sorted(missing)}")
        detail["tables_restored"] = len(restored)

        counts = {}
        for table in KEY_TABLES:
            live_n = row_count(cur, Config.DB_NAME, table)
            rest_n = row_count(cur, SCRATCH_DB, table)
            counts[table] = {"live": live_n, "restored": rest_n}
            if rest_n == 0 and live_n > COUNT_TOLERANCE_ABS:
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
            reset_scratch(cur)
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
