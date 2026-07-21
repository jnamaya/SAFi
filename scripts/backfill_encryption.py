#!/usr/bin/env python3
"""One-time backfill: encrypt historical plaintext rows at rest.

Encrypts the sensitive columns of rows written before SAFI_ENCRYPTION_KEY was
enabled. Idempotent — already-encrypted values are skipped, so the script is
safe to re-run after a crash or partial run. Batched with row locks so it can
run against the live service.

chat_history rows also receive one chat_audit_trail entry (actor
'system:encryption-backfill') recording WHICH fields were transformed but NOT
the plaintext prior value: the transformation is content-preserving and
invertible (prior value = decrypt of the written value under the same key),
so journaling plaintext would add nothing recoverable while permanently
embedding unencrypted content in the append-only journal.

Usage:
    venv/bin/python scripts/backfill_encryption.py [--dry-run] [--table NAME]
                                                   [--batch-size N] [--verify]
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.persistence import database as db
from safi_app.persistence import crypto

# (table, pk_cols, columns, journaled)
MANIFEST = [
    ("oauth_tokens", ("user_id", "provider"), ("access_token", "refresh_token"), False),
    ("conversations", ("id",), ("memory_summary", "title"), False),
    ("user_profiles", ("user_id",), ("profile_json",), False),
    ("agent_context_memory", ("user_id", "agent_id"), ("context_json",), False),
    ("saved_content", ("id",), ("content", "conscience_ledger"), False),
    ("chat_history", ("id",), ("content", "spirit_note", "conscience_ledger", "reasoning_log",
                               "suggested_prompts"), True),
]


def needs_encryption(value):
    return isinstance(value, str) and value != "" and not crypto.is_token(value)


# suggested_prompts is a JSON column: legacy plaintext is a JSON array,
# encrypted form is a JSON *string* wrapping the Fernet token (see
# db._encode_suggested_prompts). The generic string path would write a bare
# token, which MySQL's JSON validation rejects — so it gets its own codec.
def _sp_needs(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        return isinstance(json.loads(value), list)
    except (ValueError, TypeError):
        return False


def _sp_transform(value):
    return db._encode_suggested_prompts(json.loads(value))


def _sp_verify_ok(value):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return False
    return parsed is None or (isinstance(parsed, str) and crypto.is_token(parsed))


SPECIAL = {("chat_history", "suggested_prompts"): (_sp_needs, _sp_transform)}


def count_candidates(table, columns):
    conn = db.get_db_connection()
    cur = conn.cursor()
    try:
        counts = {}
        for col in columns:
            if (table, col) in SPECIAL:
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL "
                    f"AND JSON_TYPE({col}) = 'ARRAY'"
                )
            else:
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} != '' "
                    f"AND {col} NOT LIKE 'gAAAA%'"
                )
            counts[col] = cur.fetchone()[0]
        return counts
    finally:
        cur.close()
        conn.close()


def backfill_table(table, pk_cols, columns, journaled, batch_size):
    """Encrypts one table in batches. Returns rows updated."""
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    updated = 0
    pk_list = ", ".join(pk_cols)
    col_list = ", ".join(columns)
    # chat_history trail entries need conversation_id/message_id for the journal
    extra = ", conversation_id, message_id" if journaled else ""
    last_pk = None
    try:
        while True:
            if len(pk_cols) == 1:
                where = f"WHERE {pk_cols[0]} > %s" if last_pk is not None else "WHERE 1=1"
                params = (last_pk, batch_size) if last_pk is not None else (batch_size,)
                cur.execute(
                    f"SELECT {pk_list}, {col_list}{extra} FROM {table} {where} "
                    f"ORDER BY {pk_cols[0]} LIMIT %s FOR UPDATE",
                    params,
                )
            else:
                # Composite-PK tables are small (tokens, profiles): single pass.
                cur.execute(f"SELECT {pk_list}, {col_list}{extra} FROM {table} ORDER BY {pk_list} FOR UPDATE")
            rows = cur.fetchall()
            if not rows:
                conn.commit()
                break
            for row in rows:
                changed = {}
                for c in columns:
                    special = SPECIAL.get((table, c))
                    if special:
                        needs, transform = special
                        if needs(row[c]):
                            changed[c] = transform(row[c])
                    elif needs_encryption(row[c]):
                        changed[c] = crypto.encrypt_value(row[c])
                if changed:
                    set_sql = ", ".join(f"{c}=%s" for c in changed)
                    where_sql = " AND ".join(f"{p}=%s" for p in pk_cols)
                    cur.execute(
                        f"UPDATE {table} SET {set_sql} WHERE {where_sql}",
                        tuple(changed.values()) + tuple(row[p] for p in pk_cols),
                    )
                    if journaled:
                        db._chat_trail_append(
                            cur, row["id"], row["message_id"], row["conversation_id"],
                            "update", "system:encryption-backfill",
                            {"transform": "fernet-encrypt", "fields": sorted(changed),
                             "note": "content-preserving; prior value = Fernet-decrypt of the value written by this update"},
                        )
                    updated += 1
            conn.commit()
            print(f"  {table}: batch done ({updated} rows updated so far)")
            if len(pk_cols) != 1:
                break
            last_pk = rows[-1][pk_cols[0]]
    finally:
        cur.close()
        conn.close()
    return updated


def verify_table(table, pk_cols, columns, journaled, sample=25):
    """Samples rows: stored values must be tokens that decrypt round-trip."""
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    problems = 0
    try:
        cur.execute(f"SELECT {', '.join(pk_cols)}, {', '.join(columns)} FROM {table} "
                    f"ORDER BY {pk_cols[0]} DESC LIMIT %s", (sample,))
        for row in cur.fetchall():
            for c in columns:
                v = row[c]
                if v is None or v == "":
                    continue
                if (table, c) in SPECIAL:
                    if not _sp_verify_ok(v):
                        print(f"  VERIFY FAIL {table}.{c} pk={row[pk_cols[0]]}: not a wrapped token")
                        problems += 1
                    continue
                if not crypto.is_token(v):
                    print(f"  VERIFY FAIL {table}.{c} pk={row[pk_cols[0]]}: not encrypted")
                    problems += 1
                elif crypto.decrypt_value(v) == v:
                    print(f"  VERIFY FAIL {table}.{c} pk={row[pk_cols[0]]}: does not decrypt")
                    problems += 1
        if journaled:
            cur.execute(f"SELECT id FROM {table} ORDER BY id DESC LIMIT 5")
            for row in cur.fetchall():
                res = db.verify_message_audit_trail(row["id"])
                if not res["valid"]:
                    print(f"  VERIFY FAIL audit trail for {table}.id={row['id']}: {res}")
                    problems += 1
    finally:
        cur.close()
        conn.close()
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count candidate rows, change nothing")
    ap.add_argument("--table", help="restrict to one table")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--verify", action="store_true", help="sample-verify encrypted state and trail chains")
    args = ap.parse_args()

    if not crypto.is_enabled():
        print("SAFI_ENCRYPTION_KEY is not set — nothing to do. Aborting.")
        sys.exit(2)

    manifest = [m for m in MANIFEST if not args.table or m[0] == args.table]
    if not manifest:
        print(f"Unknown table {args.table!r}. Tables: {', '.join(m[0] for m in MANIFEST)}")
        sys.exit(2)

    if args.dry_run:
        for table, _, columns, _ in manifest:
            print(f"{table}: {json.dumps(count_candidates(table, columns))}")
        return

    if args.verify:
        total = sum(verify_table(*m) for m in manifest)
        print(f"Verification {'PASSED' if total == 0 else f'FAILED ({total} problems)'}")
        sys.exit(1 if total else 0)

    grand = 0
    for m in manifest:
        print(f"Backfilling {m[0]} ...")
        grand += backfill_table(*m, batch_size=args.batch_size)
    print(f"Done. {grand} rows encrypted.")


if __name__ == "__main__":
    main()
