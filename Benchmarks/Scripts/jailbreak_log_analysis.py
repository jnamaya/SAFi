#!/usr/bin/env python3
"""
Jailbreak-defense substantiation report from SAFi JSONL interaction logs.
==========================================================================

Standalone (pure stdlib, Python 3.8+). Copy this single file to wherever the
raw logs live and point it at the folder — no SAFi install required.

Produces the aggregate numbers behind SAFi's public jailbreak-defense claim
(total adversarial interactions, Will-intervention counts, decision breakdown,
date range, per-persona counts) plus an interventions dump for the manual
confirmed-jailbreak determination. Raw logs are the evidence of record and
must be archived; only this script, the summary JSON, and the methodology
note belong in the public repo — never the raw logs (they contain tester
prompts).

Usage
-----
  # Everything in a folder (recursive):
  python3 jailbreak_log_analysis.py /path/to/logs --out summary.json

  # Only the personas that were publicly red-teamed, over the test window:
  python3 jailbreak_log_analysis.py /path/to/logs \
      --persona vault --persona safi \
      --start 2025-06-01 --end 2026-01-31 \
      --out summary.json --dump-interventions interventions.jsonl

Notes
-----
- An "interaction" is one JSONL line (one governed turn).
- A "Will intervention" is any willDecision other than approve; entries with
  willDecision == cancelled (user-cancelled mid-generation) are excluded from
  the denominator by default (--include-cancelled to keep them).
- "Confirmed jailbreak" is a manual label: review the --dump-interventions
  file (and any approve-decision entries flagged during testing) and record
  the determination in the methodology note. This script counts; it does not
  judge.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

APPROVE = "approve"
CANCELLED = "cancelled"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("paths", nargs="+", help="log files or directories (searched recursively for *.jsonl)")
    p.add_argument("--persona", action="append", default=[],
                   help="only include this persona (filename prefix or agentName); repeatable")
    p.add_argument("--start", type=date.fromisoformat, help="inclusive start date (YYYY-MM-DD, UTC)")
    p.add_argument("--end", type=date.fromisoformat, help="inclusive end date (YYYY-MM-DD, UTC)")
    p.add_argument("--include-cancelled", action="store_true",
                   help="keep willDecision=cancelled entries in the denominator")
    p.add_argument("--out", help="write JSON summary here")
    p.add_argument("--dump-interventions", metavar="PATH",
                   help="write every non-approve entry (full record) here for manual review")
    return p.parse_args()


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.jsonl")))
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"error: no such file or directory: {raw}")
    if not files:
        sys.exit("error: no .jsonl files found under the given paths")
    return files


def persona_from_filename(path: Path) -> str:
    # LOG_FILE_TEMPLATE is "{profile}-%Y-%m-%d.jsonl"; profile itself may contain hyphens.
    stem = path.stem
    parts = stem.rsplit("-", 3)
    if len(parts) == 4 and all(x.isdigit() for x in parts[1:]):
        return parts[0]
    return stem


def entry_date(entry: dict) -> date | None:
    ts = entry.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def main() -> None:
    args = parse_args()
    personas = {x.lower() for x in args.persona}
    files = collect_files(args.paths)

    totals: Counter[str] = Counter()          # willDecision -> count
    per_persona: Counter[str] = Counter()
    per_day = defaultdict(Counter)            # date -> willDecision -> count
    spirit_hist: Counter[str] = Counter()
    parse_errors = 0
    skipped_persona = 0
    skipped_date = 0
    cancelled = 0
    files_used: set[str] = set()
    min_d: date | None = None
    max_d: date | None = None

    dump = open(args.dump_interventions, "w", encoding="utf-8") if args.dump_interventions else None
    try:
        for f in files:
            file_persona = persona_from_filename(f)
            if personas and file_persona.lower() not in personas:
                # filename says no, but agentName inside may still match — decide per line
                filename_match = False
            else:
                filename_match = True
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        continue
                    persona = entry.get("agentName") or file_persona
                    if personas and not filename_match and str(persona).lower() not in personas:
                        skipped_persona += 1
                        continue
                    d = entry_date(entry)
                    if (args.start and (d is None or d < args.start)) or \
                       (args.end and (d is None or d > args.end)):
                        skipped_date += 1
                        continue
                    decision = str(entry.get("willDecision", "missing"))
                    if decision == CANCELLED and not args.include_cancelled:
                        cancelled += 1
                        continue
                    totals[decision] += 1
                    per_persona[str(persona)] += 1
                    if d:
                        per_day[d.isoformat()][decision] += 1
                        min_d = d if min_d is None or d < min_d else min_d
                        max_d = d if max_d is None or d > max_d else max_d
                    score = entry.get("spiritScore")
                    spirit_hist[str(score) if score is not None else "null"] += 1
                    if dump and decision != APPROVE:
                        dump.write(json.dumps({"_file": str(f), **entry}, ensure_ascii=False) + "\n")
            files_used.add(str(f))
    finally:
        if dump:
            dump.close()

    total = sum(totals.values())
    interventions = total - totals.get(APPROVE, 0)
    summary = {
        "generated_note": "Aggregates computed by Benchmarks/Scripts/jailbreak_log_analysis.py; "
                          "raw JSONL logs are the evidence of record.",
        "filters": {
            "personas": sorted(personas) or "all",
            "start": args.start.isoformat() if args.start else None,
            "end": args.end.isoformat() if args.end else None,
            "cancelled_included": bool(args.include_cancelled),
        },
        "files_scanned": len(files_used),
        "parse_errors": parse_errors,
        "skipped_out_of_persona": skipped_persona,
        "skipped_out_of_date_range": skipped_date,
        "excluded_cancelled": cancelled,
        "observed_date_range": [min_d.isoformat() if min_d else None,
                                max_d.isoformat() if max_d else None],
        "total_interactions": total,
        "will_decisions": dict(totals.most_common()),
        "will_interventions": interventions,
        "approval_rate_pct": round(totals.get(APPROVE, 0) / total * 100, 2) if total else None,
        "per_persona": dict(per_persona.most_common()),
        "spirit_score_histogram": dict(sorted(spirit_hist.items())),
        "per_day": {k: dict(v) for k, v in sorted(per_day.items())},
        "confirmed_jailbreaks": "MANUAL LABEL — review the interventions dump and any flagged "
                                "approve-decision entries, then record the count and rationale "
                                "in the methodology note.",
    }

    print(f"files scanned:        {len(files_used)}  (parse errors: {parse_errors})")
    print(f"date range observed:  {summary['observed_date_range'][0]} -> {summary['observed_date_range'][1]}")
    print(f"total interactions:   {total}  (cancelled excluded: {cancelled})")
    print(f"will decisions:       {dict(totals.most_common())}")
    print(f"will interventions:   {interventions}")
    if total:
        print(f"approval rate:        {summary['approval_rate_pct']}%")
    print(f"per persona:          {dict(per_persona.most_common())}")
    if args.dump_interventions:
        print(f"interventions dump:   {args.dump_interventions}")
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"summary written:      {args.out}")


if __name__ == "__main__":
    main()
