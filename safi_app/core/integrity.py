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
    global _status
    if root is not None:
        return _compute(Path(root))
    if _status is None or refresh:
        _status = _compute(_ROOT)
    return _status


def tcb_stamp() -> Dict[str, Any]:
    s = get_status()
    return {
        "fingerprint": s["fingerprint"],
        "intact": s["intact"],
        "state": s["state"],
    }


def enforce_at_boot(app_logger=None, status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
            f"from the new release's published TCB Fingerprint line; otherwise treat "
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
            "release's published TCB Fingerprint line if this is a deliberate upgrade."
        )
    return s
