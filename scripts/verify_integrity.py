#!/usr/bin/env python3
"""
Core-loop integrity check — the verification step named in Section IV of
docs/"SAFi License & Governance Agreement.md".

WHAT THIS IS. The trademark policy lets an organization modify SAFi and still
call its deployment SAFi only if the Core Loop (Section II of the agreement) is
either unmodified or its modifications were submitted and accepted upstream.
This script is how both sides check that claim: it recomputes a SHA-256 hash of
every Core Loop file and compares it against the manifest shipped with the
release, then runs the structural invariants that give a *reason* when a hash
mismatch matters.

Two layers, on purpose:

  1. The HASH MANIFEST is the compliance verdict. Byte-identical or not — no
     judgment involved, reproducible by anyone from the same tree. The manifest
     also carries a single root fingerprint so a deployment can cite one hash
     ("core loop fingerprint a1b2…") in an audit or a procurement answer.

  2. The STRUCTURAL INVARIANTS are the diagnosis. A fork whose hashes fail is
     told WHICH architectural commitment the edit touched, if any. A hash
     mismatch with every invariant intact is ordinary drift from upstream; a
     mismatch that puts a model call inside the Will is the thing the agreement
     exists to prevent. The invariants are the load-bearing rule of this
     codebase: enforcement is deterministic — Phase Zero, the Will, the Spirit,
     Synderesis and the coaching builder never call a model; only the Intellect
     and the Conscience do.

Stdlib only, no imports from safi_app, so it runs on a bare checkout, inside
the Docker image (scripts/ is copied in), or against any tree via --root.

Usage:
    python scripts/verify_integrity.py               # verify, human-readable
    python scripts/verify_integrity.py --json        # verify, machine-readable
    python scripts/verify_integrity.py --root /app   # verify another tree
    python scripts/verify_integrity.py --update      # regenerate the manifest
                                                     # (maintainers, at release)

Exit codes: 0 = intact; 1 = modified/missing files or a broken invariant;
2 = the manifest itself is missing or unreadable.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

MANIFEST_NAME = "core_integrity_manifest.json"

# The Core Loop, as declared in Section II of the agreement, mapped to files.
# The orchestrator's mixins are included because part of its routing logic
# lives there. The Spirit->Intellect coaching note (the Coach) lives inside
# spirit.py — merged from a standalone feedback.py on 2026-08-13 — so covering
# the faculty covers the whole closed loop.
CORE_FILES = [
    "safi_app/core/orchestrator.py",
    "safi_app/core/orchestrator_mixins/tasks.py",
    "safi_app/core/orchestrator_mixins/tts.py",
    "safi_app/core/faculties/__init__.py",
    "safi_app/core/faculties/phase_zero.py",
    "safi_app/core/faculties/synderesis.py",
    "safi_app/core/faculties/intellect.py",
    "safi_app/core/faculties/will.py",
    "safi_app/core/faculties/conscience.py",
    "safi_app/core/faculties/spirit.py",
    "safi_app/core/faculties/utils.py",
    # The Core Database Schema: the hash-chained audit ledgers and temporal
    # logs are created here. Modifying how the system records its actions is a
    # Core Loop change even though the *content* of the database belongs to
    # the organization (Section III).
    "safi_app/persistence/database.py",
    # Enforcement CONTENT that feeds the deterministic gates and the model
    # faculties — added 2026-08-13 (backlog 34b, decided). Without these two, a
    # fork could gut Phase Zero's injection signatures or rewrite the
    # Conscience's audit prompt and still verify INTACT:
    #   threat_intel.py     — the global signature and marker lists Phase Zero
    #                         scans. Per-agent additions remain a Section III
    #                         variable (early_prompt_blacklist on the profile);
    #                         the shipped floor is what this covers.
    #   system_prompts.json — the faculty prompt templates, including the
    #                         Conscience's audit instructions and the coaching
    #                         note wrapper. Org worldviews/policies layer ON
    #                         TOP of these (Section III); the templates
    #                         themselves define how every deployment audits.
    "safi_app/core/threat_intel.py",
    "safi_app/core/system_prompts.json",
    # The plugin registry is the MECHANISM behind agreement §III's plugin
    # freedom (added 2026-08-13, backlog 37): organizations register plugins
    # without touching the orchestrator. The registry itself must be covered
    # or a fork could alter HOW dispatch works and still verify INTACT; what
    # organizations register through it is their own content and is not.
    "safi_app/core/plugins/registry.py",
    # The human-side Will (added 2026-08-13, backlog 38): the role ladder and
    # the separation-of-duties rules — editors may not sign off on content
    # they authored — are enforcement semantics, and role ASSIGNMENT is data
    # in the database, so no organization ever needs to edit this file. A fork
    # that does is weakening who may approve what, and must not verify INTACT.
    #
    # Ruled OPEN at the same time, deliberately:
    #   api/auth.py       — integration plumbing (OAuth, MFA, sessions).
    #                       Agreement §III explicitly grants authentication
    #                       infrastructure freedom, and custom IdP/SSO wiring
    #                       is a legitimate code-level need until SAML ships.
    #                       What a session may DO is enforced by rbac.py.
    #   api/review_api.py — oversight mechanism, but coverage waits until its
    #                       sampling knobs are extracted to config; covering
    #                       it now would lock tuning behind Section IV.
    "safi_app/core/rbac.py",
    # Runtime attestation (added 2026-08-13, backlog 39): computes the boot
    # verification and stamps the kernel fingerprint into every governance
    # record. A fork that no-ops the stamp would mint records claiming an
    # intact kernel — the exact lie the stamp exists to make impossible.
    "safi_app/core/integrity.py",
]

# Deterministic components: no provider imports, no model calls, ever.
# will.py holds an UNUSED llm_provider attribute for interface symmetry, which
# is why the check targets calls and imports rather than the identifier itself.
DETERMINISTIC = [
    "safi_app/core/faculties/phase_zero.py",
    "safi_app/core/faculties/synderesis.py",
    "safi_app/core/faculties/spirit.py",
    "safi_app/core/faculties/will.py",
]
_PROVIDER_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:openai|anthropic|groq|google|mistral|httpx|requests)\b",
    re.M,
)
_PROVIDER_CALL = re.compile(r"\bself\.llm_provider\s*\.\s*\w+\s*\(")


def _hash_file(path: Path) -> str:
    # \r stripped so a CRLF checkout (Windows git autocrlf) hashes the same
    # tree as the LF original — the bytes that matter are the code.
    return hashlib.sha256(path.read_bytes().replace(b"\r", b"")).hexdigest()


def _root_fingerprint(hashes: dict) -> str:
    lines = "".join(f"{p}:{h}\n" for p, h in sorted(hashes.items()))
    return hashlib.sha256(lines.encode()).hexdigest()


def _structural_findings(root: Path) -> list:
    """Invariant diagnostics. Empty list = every invariant intact."""
    findings = []
    for rel in DETERMINISTIC:
        f = root / rel
        if not f.exists():
            continue  # the hash layer already reports it as missing
        src = f.read_text(encoding="utf-8", errors="replace")
        if _PROVIDER_IMPORT.search(src):
            findings.append(
                f"{rel}: imports a model-provider or HTTP client. This faculty is "
                "deterministic by architectural commitment — it must never reach a model."
            )
        if _PROVIDER_CALL.search(src):
            findings.append(
                f"{rel}: calls self.llm_provider. The Will may HOLD the reference "
                "(interface symmetry) but must never invoke it."
            )

    orch = root / "safi_app/core/orchestrator.py"
    if orch.exists():
        src = orch.read_text(encoding="utf-8", errors="replace")
        # Whole-file position is NOT execution order: _finalize_draft (Phases
        # 3-5) is defined before process_prompt (Phases 0-2), and asserting a
        # global ordering flagged a pristine tree. Each check is therefore
        # scoped to the function whose body actually runs those phases.
        def _in_order(func_name, markers):
            at = src.find(f"def {func_name}")
            if at == -1:
                findings.append(
                    f"orchestrator.py: {func_name}() not found. The staged pipeline "
                    "appears to have been restructured."
                )
                return
            body = src[at:]
            positions = [body.find(m) for m in markers]
            if -1 in positions:
                missing = [m for m, p in zip(markers, positions) if p == -1]
                findings.append(
                    f"orchestrator.py: governance markers missing from {func_name}(): "
                    f"{missing}. The staged sequence appears to have been removed or renamed."
                )
            elif positions != sorted(positions):
                findings.append(
                    f"orchestrator.py: governance phases out of order in {func_name}(). "
                    "Phase 0 -> Intellect and Will -> Conscience -> Hard Gate -> Spirit "
                    "is the agency architecture the agreement protects."
                )
        _in_order("process_prompt", ["Phase 0", "Phase 2 | Intellect"])
        _in_order("_finalize_draft", ["Phase 3 | Will", "Phase 4 | Conscience",
                                      "Phase 4.5", "Phase 5 | Spirit"])
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the SAFi Core Loop against the release manifest.")
    ap.add_argument("--root", type=Path, default=None,
                    help="Tree to verify (default: the repo this script lives in).")
    ap.add_argument("--update", action="store_true",
                    help="Regenerate the manifest from the current tree (maintainers, at release).")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = ap.parse_args()

    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    manifest_path = root / "scripts" / MANIFEST_NAME

    current, missing = {}, []
    for rel in CORE_FILES:
        f = root / rel
        if f.exists():
            current[rel] = _hash_file(f)
        else:
            missing.append(rel)

    if args.update:
        if missing:
            print(f"refusing to write a manifest with missing core files: {missing}")
            return 1
        manifest = {
            "comment": "SAFi Core Loop integrity manifest. Generated by scripts/verify_integrity.py "
                       "--update at release. See Section IV of docs/'SAFi License & Governance Agreement.md'.",
            "root_fingerprint": _root_fingerprint(current),
            "files": current,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"manifest written: {manifest_path}")
        print(f"core loop fingerprint: {manifest['root_fingerprint']}")
        return 0

    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    except Exception as e:
        print(f"manifest unreadable: {e}", file=sys.stderr)
        return 2

    modified = sorted(p for p in recorded if p in current and current[p] != recorded[p])
    absent = sorted(set(list(recorded) + missing) - set(current))
    unlisted = sorted(p for p in current if p not in recorded)
    findings = _structural_findings(root)
    intact = not modified and not absent and not findings

    if args.json:
        print(json.dumps({
            "intact": intact,
            "root_fingerprint_expected": _root_fingerprint(recorded),
            "root_fingerprint_actual": _root_fingerprint(current),
            "modified": modified, "missing": absent, "unlisted": unlisted,
            "structural_findings": findings,
        }, indent=2))
        return 0 if intact else 1

    print("SAFi Core Loop integrity check")
    print(f"  tree:     {root}")
    print(f"  expected: {_root_fingerprint(recorded)}")
    print(f"  actual:   {_root_fingerprint(current)}")
    for p in sorted(recorded):
        state = "MISSING" if p in absent else ("MODIFIED" if p in modified else "ok")
        print(f"  [{state:8}] {p}")
    for p in unlisted:
        print(f"  [UNLISTED] {p} (present but not in the manifest)")
    if findings:
        print("\nstructural invariants:")
        for x in findings:
            print(f"  BROKEN: {x}")
    elif modified or absent:
        print("\nstructural invariants: all intact — the modifications do not appear to "
              "collapse the faculty separation, but per Section IV they must still be "
              "submitted for review to retain the SAFi name.")

    print("\nRESULT:", "INTACT — this deployment may represent itself as SAFi (Section IV)."
          if intact else
          "MODIFIED — per Section IV, submit the changes for review or rebrand the deployment.")
    return 0 if intact else 1


if __name__ == "__main__":
    sys.exit(main())
