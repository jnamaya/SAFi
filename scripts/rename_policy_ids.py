#!/usr/bin/env python3
"""
Rename built-in policy IDs in the live database: demo_*_policy -> prod_*_policy.

WHY THIS IS NEEDED. The seed policy IDs historically carried a "demo_" prefix
even though these are production policies. The source of truth in
safi_app/core/policies/demo/ now uses prod_*_policy IDs, so the DB must follow
or bootstrap will treat the old rows as retired and re-seed duplicates under
the new IDs — orphaning API-key bindings, agent profiles, and chat history.

WHAT IT DOES. For each mapping below, updates the policies row and every
policy-referencing column the schema declares (policy_versions, api_keys,
agents, chat_history, organizations.global_policy_id, ...). Children are
updated before the parent, and FOREIGN_KEY_CHECKS is disabled for the
transaction, because most FKs are ON DELETE CASCADE only (no ON UPDATE).

SAFETY. Dry run by default; pass --apply to write. Only rows whose id matches
a mapping are touched; version history is preserved (policy_versions rows move
with the new id, so old versions stay auditable).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.persistence import database as db

RENAME_MAP = {
    "demo_agentic_coding_policy": "prod_agentic_coding_policy",
    "demo_financial_advisory_policy": "prod_financial_advisory_policy",
    "demo_security_engineer_policy": "prod_security_engineer_policy",
    "demo_systems_admin_policy": "prod_systems_admin_policy",
    "demo_runsafi_guidance_policy": "prod_runsafi_guidance_policy",
    "demo_religious_studies_policy": "prod_religious_studies_policy",
    "demo_patient_navigation_policy": "prod_patient_navigation_policy",
    "demo_academic_tutoring_policy": "prod_academic_tutoring_policy",
    "demo_product_guidance_policy": "prod_product_guidance_policy",
}

# Tables/columns known to reference policy ids. Discovered via
# information_schema at runtime as well, but listed explicitly so a missing
# FK never silently skips a table.
KNOWN_REFS = [
    ("policy_versions", "policy_id"),
    ("agents", "policy_id"),
    ("api_keys", "policy_id"),
    ("chat_history", "policy_id"),
    ("organizations", "global_policy_id"),
]


def _discover_policy_columns(cur):
    cur.execute(
        """SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND COLUMN_NAME IN ('policy_id', 'global_policy_id')"""
    )
    return {(r["TABLE_NAME"], r["COLUMN_NAME"]) for r in cur.fetchall()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    args = ap.parse_args()

    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        refs = _discover_policy_columns(cur) | set(KNOWN_REFS)
        cur.execute("SELECT id FROM policies")
        existing = {r["id"] for r in cur.fetchall()}

        plan = []
        for old, new in RENAME_MAP.items():
            if new in existing and old in existing:
                print(f"SKIP  {old} -> {new}: BOTH ids exist; resolve manually.")
                continue
            if old not in existing:
                print(f"SKIP  {old}: not present (already renamed or never seeded).")
                continue
            plan.append((old, new))

        if not plan:
            print("Nothing to do.")
            return

        for old, new in plan:
            verb = "RENAMING" if args.apply else "WOULD RENAME"
            print(f"\n{verb}  {old} -> {new}")
            for table, col in sorted(refs):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} = %s", (old,))
                n = cur.fetchone()["n"]
                if n:
                    print(f"   {table}.{col}: {n} row(s)")
                    if args.apply:
                        cur.execute(
                            f"UPDATE {table} SET {col} = %s WHERE {col} = %s", (new, old))
            if args.apply:
                cur.execute("SET FOREIGN_KEY_CHECKS=0")
                try:
                    cur.execute("UPDATE policies SET id = %s WHERE id = %s", (new, old))
                finally:
                    cur.execute("SET FOREIGN_KEY_CHECKS=1")

        if args.apply:
            conn.commit()
            print("\napplied: policy ids renamed; history moved with them.")
        else:
            print("\ndry run: nothing written. Re-run with --apply.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
