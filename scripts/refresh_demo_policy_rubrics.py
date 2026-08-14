#!/usr/bin/env python3
"""
Re-seed the value rubrics of already-seeded DEMO policies from the agent
definitions in code.

WHY THIS IS NEEDED. `_ensure_demo_agent_policies_exist` (database.py) is
idempotent on purpose — `if get_policy(pid): continue` — so operator edits made
through the Governance tab survive restarts. Correct, but it means a code fix to
a agent's rubric never reaches a policy row that already exists. This script
closes that gap for demo policies only.

WHAT IT WILL NOT TOUCH. Only rows with `is_demo = TRUE` and an id present in
DEMO_AGENT_POLICIES. An operator-authored policy is never rewritten: silently
replacing a customer's governance rubric would be far worse than a stale demo.

The specific fix this was written for: both the Fiduciary's Transparency rubric
and the Health Navigator's Patient Safety rubric used to ask the Conscience to
judge whether the mandatory disclaimer was present. That is a substring check
the Will already performs deterministically, and the model got it wrong — the
same byte-identical disclaimer scored +1 on one turn and -1 at 0.95 confidence
on the next, reasoning "not verbatim". The rubrics no longer mention it; this
brings existing rows into line.

    # show what would change, touch nothing (default)
    python scripts/refresh_demo_policy_rubrics.py

    # apply
    python scripts/refresh_demo_policy_rubrics.py --apply

Bumps each refreshed policy's version so the change is visible in policy history
rather than mutating v1 underneath anyone.
"""
import argparse
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safi_app.persistence import database as db


def _values_of(pol):
    return pol.get("values") or pol.get("values_weights") or []


def _rubric_text(values):
    """Flatten the rubric prose so a diff shows what a reviewer actually cares
    about, rather than JSON churn from key ordering."""
    out = []
    for v in values:
        name = v.get("value") or v.get("name") or "?"
        r = v.get("rubric") or {}
        out.append(f"{name}: {r.get('description','')}")
        for g in r.get("scoring_guide") or []:
            out.append(f"  {g.get('score')}: {g.get('descriptor')}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    args = ap.parse_args()

    from safi_app.core.policies.demo.policies import DEMO_AGENT_POLICIES

    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, name, is_demo, values_weights, version FROM policies")
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    changed = skipped_operator = identical = 0
    for row in rows:
        pid = row["id"]
        if pid not in DEMO_AGENT_POLICIES:
            continue
        if not row["is_demo"]:
            # Same id as a demo policy but no longer flagged demo: someone has
            # adopted it. Leave it alone and say so.
            print(f"SKIP  {pid}: is_demo is false — treating as operator-owned.")
            skipped_operator += 1
            continue

        try:
            current = json.loads(row["values_weights"]) if isinstance(row["values_weights"], str) \
                else (row["values_weights"] or [])
        except (ValueError, TypeError):
            print(f"SKIP  {pid}: values_weights is not parseable JSON.")
            continue

        desired = _values_of(DEMO_AGENT_POLICIES[pid])
        before, after = _rubric_text(current), _rubric_text(desired)
        if before == after:
            identical += 1
            continue

        print(f"\n{'WOULD UPDATE' if not args.apply else 'UPDATING'}  {pid}  "
              f"({row['name']}, v{row['version']})")
        for line in difflib.unified_diff(before, after, lineterm="",
                                         fromfile="stored", tofile="code"):
            if line.startswith(("+++", "---", "@@")):
                continue
            print("   " + line)

        if args.apply:
            # update_policy bumps the version and writes a history row, so the
            # change is auditable instead of silently replacing v1.
            db.update_policy(pid, values=desired)
            print(f"   -> written; version bumped")
        changed += 1

    print(f"\n{'applied' if args.apply else 'dry run'}: "
          f"{changed} demo policy/policies {'updated' if args.apply else 'would change'}, "
          f"{identical} already current, {skipped_operator} operator-owned skipped.")
    if changed and not args.apply:
        print("re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
