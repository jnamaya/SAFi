#!/usr/bin/env python3
"""
Jailbreak-defense substantiation report from SAFi JSONL interaction logs.
==========================================================================

Standalone (pure stdlib, Python 3.8+). Copy this single file to wherever the
raw logs live and point it at the folder — no SAFi install required.

Produces the aggregate numbers behind SAFi's public jailbreak-defense claim
(total adversarial interactions, Will-intervention counts, decision breakdown,
date range, per-persona counts), an adversarial-traffic classification using
SAFi's own shipped injection signatures, a SHA-256 chain-of-custody manifest
of the archived logs, and an interventions dump for the manual
confirmed-jailbreak determination. Raw logs are the evidence of record and
must be archived; only this script, the summary JSON, the manifest, and the
methodology note belong in the public repo — never the raw logs (they contain
tester prompts).

No output of this script contains prompt, draft, or response text. The
summary and manifest are counts and hashes only, so they are safe to publish
even though the logs they are derived from are not.

Usage
-----
  # Everything in a folder (recursive):
  python3 jailbreak_log_analysis.py /path/to/logs --out summary.json

  # Only the personas that were publicly red-teamed, over the test window:
  python3 jailbreak_log_analysis.py /path/to/logs \
      --persona vault --persona safi \
      --start 2025-06-01 --end 2026-01-31 \
      --out summary.json --dump-interventions interventions.jsonl

  # Full substantiation run: aggregates + adversarial classification + manifest
  python3 jailbreak_log_analysis.py /path/to/logs \
      --persona the_socratic_tutor --persona "the socratic tutor" \
      --signatures ../../safi_app/core/threat_intel.py \
      --out summary.json --manifest manifest.sha256

Notes
-----
- An "interaction" is one JSONL line (one governed turn).
- A "Will intervention" is any willDecision other than approve; entries with
  willDecision == cancelled (user-cancelled mid-generation) are excluded from
  the denominator by default (--include-cancelled to keep them).
- Interventions are split two ways. A "governance intervention" is a real
  policy decision by the Will. An "error block" is a fail-closed block caused
  by infrastructure (willReason starting "System Error" / "Internal Error"),
  e.g. a provider connection drop or unparseable model output. Error blocks
  are NOT evidence of defensive performance and must not be reported as
  though they were.
- --signatures classifies each prompt against INJECTION_SIGNATURES from a
  threat_intel.py (loaded standalone; that module has no SAFi imports). This
  is a deterministic substring match, so the resulting count is a FLOOR on
  adversarial traffic, not a total: it misses paraphrase and plain-language
  coercion by design (see Benchmarks/PHASE0_IMPROVEMENT_PLAN.md §1). Report
  it as "at least N attacks", never "N attacks occurred".
- "Confirmed jailbreak" is a manual label: review the --dump-interventions
  file (and any approve-decision entries flagged during testing) and record
  the determination in the methodology note. This script counts; it does not
  judge.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

APPROVE = "approve"
CANCELLED = "cancelled"

# A non-approve decision whose reason starts with one of these is a fail-closed
# infrastructure block, not a governance determination by the Will. Counting
# these as defensive wins would overstate the defense rate.
ERROR_BLOCK_PREFIXES = ("System Error", "Internal Error")


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
    p.add_argument("--signatures", metavar="PATH",
                   help="path to a threat_intel.py; classifies prompts against its "
                        "INJECTION_SIGNATURES to produce a floor on adversarial traffic")
    p.add_argument("--manifest", metavar="PATH",
                   help="write a SHA-256 chain-of-custody manifest of every scanned log file")
    return p.parse_args()


def load_signatures(path: str) -> tuple[dict[str, list[str]], dict]:
    """Load INJECTION_SIGNATURES from a standalone threat_intel.py.

    Returns (signatures, provenance). Provenance pins WHICH signature database
    produced the counts — the list grows over time, so a count without the
    source hash is not reproducible.
    """
    src = Path(path)
    if not src.is_file():
        sys.exit(f"error: --signatures file not found: {path}")
    spec = importlib.util.spec_from_file_location("_safi_threat_intel", src)
    if spec is None or spec.loader is None:
        sys.exit(f"error: cannot load {path} as a Python module")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 - report and stop, don't half-run
        sys.exit(f"error: failed to exec {path}: {exc}")
    sigs = getattr(mod, "INJECTION_SIGNATURES", None)
    if not isinstance(sigs, dict) or not sigs:
        sys.exit(f"error: {path} has no usable INJECTION_SIGNATURES dict")
    lowered = {cat: [str(pat).lower() for pat in pats] for cat, pats in sigs.items()}
    provenance = {
        "source_path": str(src),
        "source_sha256": sha256_file(src),
        "categories": len(lowered),
        "patterns": sum(len(v) for v in lowered.values()),
    }
    return lowered, provenance


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def match_signatures(prompt: str, sigs: dict[str, list[str]]) -> list[str]:
    """Categories whose patterns appear in the prompt. Substring match, matching
    the real gate's behavior — so this under-counts by design."""
    low = prompt.lower()
    return [cat for cat, pats in sigs.items() if any(pat in low for pat in pats)]


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

    sigs: dict[str, list[str]] = {}
    sig_provenance: dict = {}
    if args.signatures:
        sigs, sig_provenance = load_signatures(args.signatures)

    totals: Counter[str] = Counter()          # willDecision -> count
    per_persona: Counter[str] = Counter()
    per_day = defaultdict(Counter)            # date -> willDecision -> count
    spirit_hist: Counter[str] = Counter()
    sig_cats: Counter[str] = Counter()        # attack category -> prompts matched
    sig_matched = 0                           # prompts matching >= 1 category
    error_blocks = 0
    parse_errors = 0
    skipped_persona = 0
    skipped_date = 0
    cancelled = 0
    files_used: set[str] = set()          # opened
    files_contributing: set[str] = set()  # actually contributed >=1 counted interaction
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
                    files_contributing.add(str(f))
                    per_persona[str(persona)] += 1
                    if d:
                        per_day[d.isoformat()][decision] += 1
                        min_d = d if min_d is None or d < min_d else min_d
                        max_d = d if max_d is None or d > max_d else max_d
                    score = entry.get("spiritScore")
                    spirit_hist[str(score) if score is not None else "null"] += 1
                    if decision != APPROVE and \
                            str(entry.get("willReason", "")).startswith(ERROR_BLOCK_PREFIXES):
                        error_blocks += 1
                    if sigs:
                        hits = match_signatures(str(entry.get("userPrompt", "")), sigs)
                        if hits:
                            sig_matched += 1
                            for cat in hits:
                                sig_cats[cat] += 1
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
        "files_contributing": len(files_contributing),
        "files_note": "files_scanned is every .jsonl opened under the given paths; "
                      "files_contributing is the subset that survived the persona/date "
                      "filters and produced at least one counted interaction. The manifest "
                      "covers files_contributing.",
        "parse_errors": parse_errors,
        "skipped_out_of_persona": skipped_persona,
        "skipped_out_of_date_range": skipped_date,
        "excluded_cancelled": cancelled,
        "observed_date_range": [min_d.isoformat() if min_d else None,
                                max_d.isoformat() if max_d else None],
        "total_interactions": total,
        "will_decisions": dict(totals.most_common()),
        "will_interventions": interventions,
        "governance_interventions": interventions - error_blocks,
        "error_blocks": error_blocks,
        "error_blocks_note": "Fail-closed infrastructure blocks (provider error / unparseable "
                             "model output), not governance determinations. Excluded from "
                             "governance_interventions; never report them as defensive wins.",
        "approval_rate_pct": round(totals.get(APPROVE, 0) / total * 100, 2) if total else None,
        "per_persona": dict(per_persona.most_common()),
        "spirit_score_histogram": dict(sorted(spirit_hist.items())),
        "per_day": {k: dict(v) for k, v in sorted(per_day.items())},
        "confirmed_jailbreaks": "MANUAL LABEL — review the interventions dump and any flagged "
                                "approve-decision entries, then record the count and rationale "
                                "in the methodology note.",
    }

    if sigs:
        summary["adversarial_classification"] = {
            "method": "Deterministic substring match of each userPrompt against "
                      "INJECTION_SIGNATURES from the pinned threat_intel.py.",
            "interpretation": "FLOOR, not a total. Misses paraphrase and plain-language "
                              "coercion by design; report as 'at least N'.",
            "signature_source": sig_provenance,
            "prompts_matching_any_signature": sig_matched,
            "share_of_interactions_pct": round(sig_matched / total * 100, 2) if total else None,
            "categories_hit": len(sig_cats),
            "per_category_prompts": dict(sig_cats.most_common()),
            "per_category_note": "A prompt matching several categories is counted in each, so "
                                 "these sum to >= prompts_matching_any_signature.",
        }

    print(f"files scanned:        {len(files_used)}  "
          f"(contributing: {len(files_contributing)}, parse errors: {parse_errors})")
    print(f"date range observed:  {summary['observed_date_range'][0]} -> {summary['observed_date_range'][1]}")
    print(f"total interactions:   {total}  (cancelled excluded: {cancelled})")
    print(f"will decisions:       {dict(totals.most_common())}")
    print(f"will interventions:   {interventions}  "
          f"(governance: {interventions - error_blocks}, error blocks: {error_blocks})")
    if total:
        print(f"approval rate:        {summary['approval_rate_pct']}%")
    print(f"per persona:          {dict(per_persona.most_common())}")
    if sigs:
        print(f"signature db:         {sig_provenance['patterns']} patterns / "
              f"{sig_provenance['categories']} categories "
              f"(sha256 {sig_provenance['source_sha256'][:12]}…)")
        print(f"adversarial (floor):  {sig_matched} prompts "
              f"({summary['adversarial_classification']['share_of_interactions_pct']}%) "
              f"across {len(sig_cats)} categories")
        for cat, n in sig_cats.most_common():
            print(f"                        {n:>5}  {cat}")
    if args.manifest:
        # Chain of custody without disclosure: proves the archive these numbers
        # came from has not changed, while publishing no log content.
        lines = [
            "# SHA-256 manifest of the raw JSONL logs behind this report.",
            "# Raw logs are archived, not published. Verify with: sha256sum -c <this file>",
            "# Scope: only files that contributed a counted interaction under the",
            "# persona/date filters recorded in the summary JSON.",
            "# Filenames are basenames only — absolute paths would disclose the",
            "# archive holder's filesystem layout. Verify from inside the archive dir.",
            f"# files: {len(files_contributing)}",
        ]
        for f in sorted(files_contributing, key=lambda p: Path(p).name):
            lines.append(f"{sha256_file(Path(f))}  {Path(f).name}")
        Path(args.manifest).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"manifest written:     {args.manifest}  ({len(files_contributing)} files)")
    if args.dump_interventions:
        print(f"interventions dump:   {args.dump_interventions}")
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"summary written:      {args.out}")


if __name__ == "__main__":
    main()
