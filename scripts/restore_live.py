#!/usr/bin/env python3
"""Restore a SAFi backup INTO the live database (disaster recovery).

`safi backup verify` only proves a dump is restorable — into a scratch schema.
This is the operator's recovery path: it loads a chosen backup over the live
`safi` database, with three safeguards:

  1. The current live database is dumped first (safi-pre-restore-*.sql.gz), so
     a bad restore is reversible — restore that file with this same command.
  2. The chosen dump must first restore cleanly into the scratch schema and
     pass the same table-presence + audit-chain checks as a verify run;
     anything wrong aborts BEFORE the live schema is touched.
  3. The event is journaled to backup_verify_log like a verify run.

The script does its own work only: the safi CLI wraps it with
systemctl stop/start of safi + safi-kb-indexer, because loading over a live
schema under a running app is destructive. This script also runs as the `safi`
DB account, which holds per-schema privileges only.

Usage:
  venv/bin/python scripts/restore_live.py [SAFI-*.sql.gz]   (default: newest)
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backup_verify import (  # noqa: E402
    connect, base_tables, reset_scratch, row_count, verify_audit_chains,
    journal_result, restore_into_scratch, SCRATCH_DB, KEY_TABLES,
)

from safi_app.config import Config  # noqa: E402

BACKUP_DIR = "/var/backups/safi"


def _client_cnf():
    f = tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False)
    os.chmod(f.name, 0o600)
    f.write(f'[client]\nuser={Config.DB_USER}\npassword="{Config.DB_PASSWORD}"\n'
            f'host={Config.DB_HOST}\n')
    f.close()
    return f.name


def newest_dump():
    dumps = sorted(glob.glob(os.path.join(BACKUP_DIR, "safi-*.sql.gz")))
    return dumps[-1] if dumps else None


def resolve_dump(requested=""):
    if requested:
        cands = [requested,
                 os.path.join(BACKUP_DIR, requested),
                 os.path.join(BACKUP_DIR, requested + ".sql.gz")]
        for c in cands:
            if os.path.isfile(c) and c.endswith(".sql.gz"):
                return c
        raise RuntimeError(f"no such backup: {requested}")
    d = newest_dump()
    if not d:
        raise RuntimeError(f"no safi-*.sql.gz backups in {BACKUP_DIR}")
    return d


def _safety_dump(cnf):
    """Snapshot the current live database before any destructive work."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = os.path.join(BACKUP_DIR, f"safi-pre-restore-{stamp}.sql.gz")
    gtid = []
    if "set-gtid-purged" in subprocess.run(["mysqldump", "--help"],
                                           capture_output=True, text=True).stdout:
        gtid = ["--set-gtid-purged=OFF"]
    with open(out, "wb") as fh:
        subprocess.run(
            ["mysqldump", f"--defaults-extra-file={cnf}", "--single-transaction",
             "--quick", "--triggers", "--no-tablespaces", *gtid, Config.DB_NAME],
            stdout=fh, check=True)
    subprocess.run(["gzip", "-t", out], check=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", default="",
                    help="backup file (basename or path; defaults to newest)")
    args = ap.parse_args()

    dump = None
    cnf = _client_cnf()
    detail = {}
    try:
        dump = resolve_dump(args.file)
        detail["dump_file"] = os.path.basename(dump)
        subprocess.run(["gzip", "-t", dump], check=True)

        safety = _safety_dump(cnf)
        detail["safety_dump"] = os.path.basename(safety)
        print(f"safety copy of current live database: {os.path.basename(safety)}")

        admin = connect()
        cur = admin.cursor()

        # Restore into scratch first and require it to be sound before
        # touching live. Anything here fails with live untouched.
        reset_scratch(cur, SCRATCH_DB)
        admin.commit()
        restore_into_scratch(dump, SCRATCH_DB)
        scratch_tables = base_tables(cur, SCRATCH_DB)
        if not scratch_tables:
            raise RuntimeError("scratch restore produced no tables — aborting before live")
        verify_audit_chains(cur, SCRATCH_DB)

        # Now swap it into the live schema.
        reset_scratch(cur, Config.DB_NAME)
        admin.commit()
        restore_into_scratch(dump, Config.DB_NAME)
        live_tables = base_tables(cur, Config.DB_NAME)
        chains, entries = verify_audit_chains(cur, Config.DB_NAME)
        detail["tables_restored_live"] = len(live_tables)
        detail["audit_chains_verified"] = chains
        detail["audit_entries_verified"] = entries
        detail["row_counts"] = {
            t: {"live": row_count(cur, Config.DB_NAME, t)} for t in KEY_TABLES
        }
        cur.close()
        admin.close()

        journal_result("restore", detail)
        print(f"RESTORED: {os.path.basename(dump)} -> live database {Config.DB_NAME} "
              f"({len(live_tables)} tables, {entries} audit entries across {chains} chains).")
        print(f"roll back with: restore {os.path.basename(safety)}")
        return 0
    except Exception as exc:
        detail["error"] = str(exc)
        try:
            journal_result("restore-fail", detail)
        except Exception as journal_exc:
            print(f"ERROR: could not journal failure: {journal_exc}", file=sys.stderr)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        os.unlink(cnf)


if __name__ == "__main__":
    sys.exit(main())