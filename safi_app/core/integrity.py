"""
Runtime TCB attestation — measured boot for SAFi (backlog 39).

TCB = Trusted Computing Base, the security-engineering term of art for what
the integrity manifest covers: the set of components a governance claim
depends on — a defect inside it can violate the policy, a defect outside it
cannot (TCSEC, 1983). "Core Loop" is the same set's name in the License &
Governance Agreement; kernel/userland is the informal teaching analogy and
carries a footnote this term does not need: TCB claims trust dependency,
never memory isolation.

Three jobs, all built on the canonical checker in scripts/verify_integrity.py
(loaded by file path and reused, never reimplemented — two hash implementations
would eventually disagree, and the one an auditor runs by hand must be the one
the app ran at boot):

  1. BOOT VERIFICATION. create_app() calls enforce_at_boot(): the Core Loop is
     hashed against the release manifest once, and the result is logged loudly —
     the fingerprint when intact, every modified file when not. Like a Linux
     TAINT FLAG, a mismatch does not stop the app by default: AGPL grants forks
     the right to RUN modified code — only the NAME is conditional (agreement
     §IV) — so taint is about representation and evidence, not permission.

  2. STRICT MODE. SAFI_ENFORCE_INTEGRITY=strict refuses to start on anything
     but a verified-intact tree ("unverifiable" included: a deployment that
     cannot attest is not intact for a deployment that demanded attestation).
     Regulated deployments opt in; forks and development trees never trip it
     by default.

  3. THE STAMP. tcb_stamp() is folded into every governance record
     (database._insert_governance_record), so each audit record names the
     TCB that produced it — fingerprint and intact/tainted — the way a kernel
     oops report carries taint flags (the analogy, not the term). Evidence
     per record, not per deployment claim.

The status is computed ONCE and cached: these are the files the running
process imported at startup, and re-hashing per record would measure the disk,
not the process. On-disk drift after boot is the next row of the table
(backlog 39 lists it as deliberately not built).

This module is itself in the Core Loop manifest: a fork that no-ops the stamp
would mint records claiming an intact TCB, which is precisely the lie the
stamp exists to make impossible.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_CHECKER = _ROOT / "scripts" / "verify_integrity.py"

_status: Optional[Dict[str, Any]] = None


def _load_checker():
    spec = importlib.util.spec_from_file_location("safi_integrity_checker", _CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compute(root: Path) -> Dict[str, Any]:
    """Mirror of the checker's verify branch, minus printing. Any failure to
    even run the check is 'unverifiable' — a distinct third answer, because
    'could not check' must never be reported as either intact or tainted."""
    try:
        chk = _load_checker()
        import json as _json
        manifest_path = root / "scripts" / chk.MANIFEST_NAME
        recorded = _json.loads(manifest_path.read_text(encoding="utf-8"))["files"]

        current, missing = {}, []
        for rel in chk.CORE_FILES:
            f = root / rel
            if f.exists():
                current[rel] = chk._hash_file(f)
            else:
                missing.append(rel)

        modified = sorted(p for p in recorded if p in current and current[p] != recorded[p])
        absent = sorted(set(list(recorded) + missing) - set(current))
        findings = chk._structural_findings(root)
        intact = not modified and not absent and not findings
        return {
            "state": "intact" if intact else "modified",
            "intact": intact,
            "fingerprint": chk._root_fingerprint(current),
            "expected_fingerprint": chk._root_fingerprint(recorded),
            "modified": modified,
            "missing": absent,
            "findings": findings,
        }
    except Exception as e:
        return {
            "state": "unverifiable",
            "intact": False,
            "fingerprint": None,
            "expected_fingerprint": None,
            "modified": [],
            "missing": [],
            "findings": [f"integrity check could not run: {e}"],
        }


def get_status(root: Optional[Path] = None, refresh: bool = False) -> Dict[str, Any]:
    """The boot-time verification result. Cached after the first call; `root`
    and `refresh` exist for tests, which verify copies of the tree."""
    global _status
    if root is not None:
        return _compute(Path(root))
    if _status is None or refresh:
        _status = _compute(_ROOT)
    return _status


def tcb_stamp() -> Dict[str, Any]:
    """The per-record attestation folded into every governance capture."""
    s = get_status()
    return {
        "fingerprint": s["fingerprint"],
        "intact": s["intact"],
        "state": s["state"],
    }


def enforce_at_boot(app_logger=None, status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Log the verification result; refuse to start in strict mode unless
    verified intact. `status` is injectable for tests.

    SAFI_EXPECTED_FINGERPRINT is the operator's pin: the fingerprint copied
    from an official release's published `Fingerprint:` line at install time.
    The manifest ships INSIDE the tree it guards, so a local tamper can also
    regenerate it; the pin lives in the operator's config, provisioned apart
    from the code, and holds the deployment to the value a human verified
    out of band. It protects honest deployments from drift and tampering; it
    does nothing against a fork that simply does not set it, and claims
    nothing about authenticity — that comparison stays with the human at pin
    time.
    """
    logger = app_logger or log
    s = status if status is not None else get_status()
    mode = os.environ.get("SAFI_ENFORCE_INTEGRITY", "").strip().lower()
    pin = os.environ.get("SAFI_EXPECTED_FINGERPRINT", "").strip().lower()

    pin_mismatch = bool(pin) and s["fingerprint"] is not None and pin != s["fingerprint"]
    if pin and not pin_mismatch and s["fingerprint"] is not None:
        logger.info(f"TCB fingerprint matches the operator's pinned value ({pin[:16]}…).")
    elif pin_mismatch:
        logger.error(
            f"TCB FINGERPRINT PIN MISMATCH — the operator pinned "
            f"{pin} (SAFI_EXPECTED_FINGERPRINT) but this tree measures "
            f"{s['fingerprint']}. If this is a deliberate upgrade, update the pin "
            f"from the new release's published Fingerprint line; otherwise treat "
            f"the deployment as tampered."
        )

    if s["state"] == "intact":
        logger.info(f"Core Loop verified INTACT — TCB fingerprint {s['fingerprint']}")
    else:
        logger.error(
            f"Core Loop {s['state'].upper()} — this deployment is running a TCB that "
            f"does not match its release manifest. Every governance record it produces "
            f"will carry state='{s['state']}'."
        )
        for rel in s["modified"]:
            logger.error(f"  modified: {rel}")
        for rel in s["missing"]:
            logger.error(f"  missing:  {rel}")
        for x in s["findings"]:
            logger.error(f"  finding:  {x}")
        logger.error(
            "Running modified Core Loop code is permitted (AGPL); representing the "
            "deployment as SAFi is what requires an intact TCB or upstream review "
            "— see Section IV of the License & Governance Agreement."
        )

    if mode == "strict" and s["state"] != "intact":
        raise RuntimeError(
            f"SAFI_ENFORCE_INTEGRITY=strict and the Core Loop is {s['state']} — refusing "
            f"to start. Restore the shipped files (or regenerate the manifest upstream "
            f"via scripts/verify_integrity.py --update), or unset strict mode to run "
            f"tainted with every governance record saying so."
        )
    if mode == "strict" and pin_mismatch:
        raise RuntimeError(
            "SAFI_ENFORCE_INTEGRITY=strict and the TCB fingerprint does not match "
            "SAFI_EXPECTED_FINGERPRINT — refusing to start. Update the pin from the "
            "release's published Fingerprint line if this is a deliberate upgrade."
        )
    return s
