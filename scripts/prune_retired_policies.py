#!/usr/bin/env python3
"""Delete retired built-in policy rows (and their agents) from the live DB.

Run AFTER scripts/rename_policy_ids.py --apply and BEFORE restarting the app
with the 2026-11 policy reduction (only Software / Security / Sysadmin remain).

Deletes, in FK-safe order:
  1. agents rows bound to retired policy IDs
  2. policy_versions history for retired policies
  3. policies rows with retired IDs

Dry-run by default; pass --apply to execute.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safi_app.persistence import database as db  # noqa: E402

# Everything that is not one of the three retained built-ins.
RETAINED = {
    "prod_agentic_coding_policy",
    "prod_security_engineer_policy",
    "prod_systems_admin_policy",
}
RETIRED = [
    "prod_financial_advisory_policy",
    "prod_religious_studies_policy",
    "prod_patient_navigation_policy",
    "prod_academic_tutoring_policy",
    "prod_product_guidance_policy",
    # legacy demo_* forms, in case rename script was not run
    "demo_financial_advisory_policy",
    "demo_religious_studies_policy",
    "demo_patient_navigation_policy",
    "demo_academic_tutoring_policy",
    "demo_product_guidance_policy",
    # legacy demo_* rows of the three RETAINED policies: bootstrap already
    # seeded fresh prod_* copies, so the old rows are now redundant duplicates
    "demo_agentic_coding_policy",
    "demo_security_engineer_policy",
    "demo_systems_admin_policy",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="execute (default: dry run)")
    args = ap.parse_args()

    conn = db.get_db_connection()
    cursor = conn.cursor()
    try:
        for pid in RETIRED:
            cursor.execute(
                "SELECT COUNT(*) FROM agents WHERE policy_id = %s", (pid,))
            n_agents = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM policy_versions WHERE policy_id = %s", (pid,))
            n_versions = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM policies WHERE id = %s", (pid,))
            n_rows = cursor.fetchone()[0]
            if not (n_agents or n_versions or n_rows):
                print(f"skip {pid}: not present")
                continue
            print(f"{pid}: {n_rows} policy row(s), {n_versions} version(s), "
                  f"{n_agents} agent binding(s)")
            if args.apply:
                cursor.execute(
                    "UPDATE agents SET policy_id = NULL WHERE policy_id = %s", (pid,))
                cursor.execute(
                    "DELETE FROM policy_versions WHERE policy_id = %s", (pid,))
                cursor.execute("DELETE FROM policies WHERE id = %s", (pid,))
        if args.apply:
            conn.commit()
            print("Applied.")
        else:
            print("Dry run only; re-run with --apply to delete.")
    finally:
        cursor.close()
        conn.close()
    # Sanity: report what remains among the retained set.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
