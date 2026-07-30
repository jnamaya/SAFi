#!/usr/bin/env python3
"""
Report — and optionally attribute — governance records with org_id = NULL.

WHY THIS IS A SCRIPT AND NOT A UI.

`org_id = NULL` matches nothing in SQL, so an unattributed record is invisible to
every Audit Hub read and to both exports. The obvious fix is a scope in the Audit
Hub, and it is the wrong one: a record with no org belongs to no tenant, so
showing it in one org's Audit Hub would show that org's admin turns that are not
theirs (public-bot conversations from anyone). Every role in `rbac.ROLES` is
org-scoped and there is no platform superuser to gate such a view behind, so the
cross-tenant exposure would be unavoidable — a worse defect than the
invisibility. Hence: operator tooling, run deliberately, from a shell.

The real fix is upstream — set SAFI_PUBLIC_ORG_ID so public turns are attributed
when they are written. This script exists for records created before that.

    # report only (default; touches nothing)
    python scripts/audit_unattributed.py

    # attribute them to an org, deliberately
    python scripts/audit_unattributed.py --assign-org <org-uuid>

--assign-org rewrites history: it asserts these turns belonged to an org they
were not recorded against. Only use it when that is true (e.g. the public bot
was in fact your org's bot all along). It never deletes anything, and it prints
what it changed.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.persistence import database as db


def report(cursor):
    cursor.execute("SELECT COUNT(*) AS n FROM governance_records WHERE org_id IS NULL")
    total = cursor.fetchone()["n"]
    print(f"governance_records with org_id NULL: {total}")
    if not total:
        print("  nothing unattributed — every governed turn is reachable from an Audit Hub.")
        return total

    cursor.execute(
        "SELECT profile_key, policy_id, policy_version, COUNT(*) n, "
        "COUNT(DISTINCT user_id) users, MIN(created_at) first_seen, MAX(created_at) last_seen "
        "FROM governance_records WHERE org_id IS NULL "
        "GROUP BY profile_key, policy_id, policy_version ORDER BY n DESC")
    print(f"\n  {'agent':26} {'policy':38} {'v':>3} {'n':>5} {'users':>6}  window")
    for r in cursor.fetchall():
        print(f"  {str(r['profile_key'])[:26]:26} {str(r['policy_id'])[:38]:38} "
              f"{str(r['policy_version']):>3} {r['n']:5} {r['users']:6}  "
              f"{r['first_seen']} .. {r['last_seen']}")

    # If a record's policy belongs to an org, that is the defensible attribution
    # — the same fallback /bot/process_prompt already applies at write time.
    cursor.execute(
        "SELECT g.policy_id, p.org_id, COUNT(*) n "
        "FROM governance_records g LEFT JOIN policies p ON p.id = g.policy_id "
        "WHERE g.org_id IS NULL GROUP BY g.policy_id, p.org_id")
    rows = cursor.fetchall()
    suggestable = [r for r in rows if r["org_id"]]
    if suggestable:
        print("\n  their governing policy DOES belong to an org — a defensible attribution:")
        for r in suggestable:
            print(f"    policy {r['policy_id']} -> org {r['org_id']}  ({r['n']} records)")
    else:
        print("\n  none of their governing policies belongs to an org either, so there is no"
              "\n  attribution to infer. Decide deliberately, or leave them unattributed.")
    return total


def assign(cursor, conn, org_id):
    cursor.execute("SELECT id, name FROM organizations WHERE id=%s", (org_id,))
    org = cursor.fetchone()
    if not org:
        print(f"REFUSED: no organization {org_id}. Attributing records to a "
              f"non-existent org would hide them just as thoroughly.")
        return 1
    cursor.execute("SELECT COUNT(*) AS n FROM governance_records WHERE org_id IS NULL")
    n = cursor.fetchone()["n"]
    if not n:
        print("nothing to assign.")
        return 0
    cursor.execute("UPDATE governance_records SET org_id=%s WHERE org_id IS NULL", (org_id,))
    changed = cursor.rowcount
    conn.commit()
    print(f"attributed {changed} record(s) to {org['name']} ({org_id}).")
    print("They are now visible in that org's Audit Hub. This is a history rewrite;"
          "\nmake sure it reflects what actually happened.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assign-org", metavar="ORG_ID",
                    help="attribute every unattributed record to this org (rewrites history)")
    args = ap.parse_args()

    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        total = report(cursor)
        if args.assign_org:
            print()
            return assign(cursor, conn, args.assign_org)
        if total:
            print("\n  report only — nothing changed. Re-run with --assign-org <uuid> to attribute,"
                  "\n  and set SAFI_PUBLIC_ORG_ID so new public turns do not land here.")
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
