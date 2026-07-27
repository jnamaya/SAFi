#!/usr/bin/env python3
"""
Run the SAFi test suite, one file per process, and exit non-zero if any fail.

Why not `pytest tests/` or `unittest discover`?

Each file in tests/ is written to run standalone and owns its fixtures — and
several mutate global-ish state (provider_governance.activate_org, the identity
module's user cache, os.environ before importing safi_app). Collected into one
process they leak into each other; run separately they are independent. Process
isolation costs a few seconds and buys a suite whose failures mean what they say.

Exit code is the contract: 0 = everything passed. Per-file results come from
each subprocess's exit status, NOT from grepping output for "OK" — an earlier
version of this check did that and misreported test_retention_purge as failing
because it logs to stdout after unittest writes its summary to stderr.

Usage:
    python scripts/ci_run_tests.py [-k SUBSTRING] [--timeout SECONDS]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("-k", metavar="SUBSTRING",
                   help="only run test files whose name contains this")
    p.add_argument("--timeout", type=int, default=300,
                   help="per-file timeout in seconds (default 300)")
    p.add_argument("--quiet", action="store_true",
                   help="suppress output from passing files")
    p.add_argument("--no-bootstrap", action="store_true",
                   help="skip schema creation (the database already has one)")
    return p.parse_args()


def bootstrap_schema(env) -> int:
    """Create the schema once, before any test runs.

    A fresh database has no tables. Files that go through create_app() would
    build the schema themselves via init_db(), but several talk straight to the
    database in setUpClass and would hit "Table ... doesn't exist" depending on
    alphabetical order — a failure that looks like a broken test and is really
    an empty database. Doing it once up front also keeps ~30 redundant DDL
    passes out of every run.
    """
    print("bootstrapping schema ... ", end="", flush=True)
    proc = subprocess.run(
        [sys.executable, "-c",
         "from safi_app.persistence.database import init_db; init_db()"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    if proc.returncode != 0:
        print("FAILED")
        sys.stdout.write(_indent(proc.stderr.strip() or proc.stdout.strip()))
        sys.stdout.write("\n")
        return 2
    print("ok")
    return 0


def main() -> int:
    args = parse_args()
    if not TESTS_DIR.is_dir():
        print(f"error: no tests directory at {TESTS_DIR}", file=sys.stderr)
        return 2

    files = sorted(f for f in TESTS_DIR.glob("test_*.py"))
    if args.k:
        files = [f for f in files if args.k in f.name]
    if not files:
        print("error: no test files matched", file=sys.stderr)
        return 2

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    if not args.no_bootstrap:
        rc = bootstrap_schema(env)
        if rc != 0:
            return rc

    passed, failed, timed_out = [], [], []
    started = time.monotonic()

    for f in files:
        label = f.name
        print(f"  {label:<44} ", end="", flush=True)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, str(f)],
                capture_output=True, text=True, timeout=args.timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            timed_out.append(label)
            print(f"TIMEOUT after {args.timeout}s")
            continue
        elapsed = time.monotonic() - t0
        if proc.returncode == 0:
            passed.append(label)
            print(f"ok    ({elapsed:.1f}s)")
            if not args.quiet and proc.stderr.strip():
                pass  # unittest chatter on success is noise
        else:
            failed.append(label)
            print(f"FAIL  ({elapsed:.1f}s)")
            # unittest writes results to stderr; stdout carries app logging.
            sys.stdout.write(_indent(proc.stderr.strip() or proc.stdout.strip()))
            sys.stdout.write("\n")

    total = time.monotonic() - started
    print("-" * 62)
    print(f"{len(passed)} passed, {len(failed)} failed, "
          f"{len(timed_out)} timed out, in {total:.1f}s")
    for label in failed:
        print(f"  FAILED   {label}")
    for label in timed_out:
        print(f"  TIMEOUT  {label}")
    return 1 if (failed or timed_out) else 0


def _indent(text, prefix="      | "):
    return "\n".join(prefix + line for line in text.splitlines())


if __name__ == "__main__":
    sys.exit(main())
