"""Deterministic detectors for sensitive personal and financial identifiers.

No model is called here. A regular expression finds the shape of an identifier,
and a checksum or a set of allocation rules confirms it.

Lives outside `faculties/` for the same reason `threat_intel.py` does: this is
data and pure functions, so adding a detector does not mean editing a faculty.

Detectors are inert unless a caller passes an enabled set. `scan` reports
matches, `redact` replaces them, `normalize` filters a caller's list down to
known keys, and `catalogue` describes the available checks for a settings UI.

Precision differs per identifier, and `catalogue` reports it so a UI can show
it before a check is enabled:

  credit_card  Luhn (mod 10)
  iban         mod-97 == 1        effectively no false positives
  aba          weighted mod-10    the loosest here: roughly 1 in 10 random
                                  9-digit runs pass by chance
  ssn          no checksum        formatted ddd-dd-dddd only, plus the SSA
                                  allocation rules. A bare 9-digit run is not
                                  matched, because it collides with order
                                  numbers, part numbers and phone digits.

Only keys present in the catalogue are accepted. `normalize` silently drops
anything else, so a caller cannot introduce a new pattern through this module.
"""
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Sequence


class Finding(NamedTuple):
    key: str            # validator key, e.g. "credit_card"
    label: str          # human label for the audit reason
    start: int
    end: int


# ── checksums ────────────────────────────────────────────────────────────────

def _luhn_ok(digits: str) -> bool:
    """Mod-10. The standard check on card PANs."""
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _iban_ok(value: str) -> bool:
    """ISO 13616: move the first four characters to the end, map letters to
    numbers (A=10), and the whole thing mod 97 must equal 1."""
    v = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if not 15 <= len(v) <= 34:
        return False
    rearranged = v[4:] + v[:4]
    try:
        numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _aba_ok(digits: str) -> bool:
    """ABA routing transit number: 3-7-1 weighting, sum mod 10 == 0."""
    if len(digits) != 9:
        return False
    w = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    return sum(int(d) * k for d, k in zip(digits, w)) % 10 == 0


def _ssn_ok(match: "re.Match[str]") -> bool:
    """No checksum exists. Apply the SSA allocation rules instead: the area may
    not be 000, 666 or 900-999; the group may not be 00; the serial may not be
    0000. These remove the placeholder values that make up most false hits."""
    area, group, serial = match.group(1), match.group(2), match.group(3)
    if area in ("000", "666") or area[0] == "9":
        return False
    return group != "00" and serial != "0000"


# ── the catalogue ────────────────────────────────────────────────────────────
#
# `digits_only` strips separators before the checksum runs, so a card written
# with spaces or hyphens still validates. `verify` receives the raw match for
# ssn (it needs the groups) and the cleaned digits for the rest.

_CATALOGUE = {
    "ssn": {
        "label": "US Social Security number",
        "pattern": re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b"),
        "verify": _ssn_ok,
        "raw_match": True,
        "note": "formatted ddd-dd-dddd only; bare 9-digit runs are not matched",
    },
    "credit_card": {
        "label": "payment card number",
        "pattern": re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
        "verify": lambda d: 13 <= len(d) <= 19 and _luhn_ok(d),
        "raw_match": False,
        "note": "Luhn-validated",
    },
    "iban": {
        "label": "IBAN",
        "pattern": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
        "verify": _iban_ok,
        "raw_match": False,
        "keep_alpha": True,
        "note": "mod-97 validated",
    },
    "aba": {
        "label": "bank routing number",
        "pattern": re.compile(r"\b\d{9}\b"),
        "verify": _aba_ok,
        "raw_match": False,
        "note": "checksum validated; the loosest detector here, ~1 in 10 random "
                "9-digit runs pass the checksum",
    },
}

VALIDATOR_KEYS = tuple(_CATALOGUE.keys())


def catalogue() -> List[Dict[str, str]]:
    """What the settings UI renders. Keys, labels and the honest note about
    each detector's precision, so an admin ticking a box can see what they are
    turning on."""
    return [{"key": k, "label": v["label"], "note": v["note"]} for k, v in _CATALOGUE.items()]


def normalize(keys: Optional[Sequence[str]]) -> List[str]:
    """Accept only known validator keys, in catalogue order.

    The settings surface offers a fixed menu, so anything else is a bug or an
    attempt to smuggle in a pattern. Dropped silently rather than raising: an
    unknown key must never be able to disable the ones that ARE valid.
    """
    if not keys:
        return []
    given = {str(k).strip().lower() for k in keys}
    return [k for k in VALIDATOR_KEYS if k in given]


def scan(text: str, enabled: Optional[Sequence[str]]) -> List[Finding]:
    """Every match of every enabled validator, in document order.

    Returns [] when nothing is enabled, which is the default state, so a
    deployment that never opens the settings tab pays one empty-list check.
    """
    keys = normalize(enabled)
    if not keys or not text:
        return []
    out: List[Finding] = []
    for key in keys:
        spec = _CATALOGUE[key]
        for m in spec["pattern"].finditer(text):
            raw = m.group(0)
            if spec["raw_match"]:
                ok = spec["verify"](m)
            elif spec.get("keep_alpha"):
                ok = spec["verify"](raw)
            else:
                ok = spec["verify"](re.sub(r"\D", "", raw))
            if ok:
                out.append(Finding(key, spec["label"], m.start(), m.end()))
    out.sort(key=lambda f: f.start)
    return out


def redact(text: str, enabled: Optional[Sequence[str]]) -> str:
    """Replace every hit with `[REDACTED:key]`.

    Full replacement, NOT masking to the last four. A governance record is
    retained for years under the retention rules, and a partial identifier is
    still an identifier. The validator key survives so the record still explains
    WHY the turn was blocked, which is the part an examiner needs.
    """
    findings = scan(text, enabled)
    if not findings:
        return text
    out, cursor = [], 0
    for f in findings:
        if f.start < cursor:        # overlapping matches: keep the first
            continue
        out.append(text[cursor:f.start])
        out.append("[REDACTED:%s]" % f.key)
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def summarize(findings: Sequence[Finding]) -> str:
    """A stable reason string for the audit record. Counts only, never values."""
    if not findings:
        return ""
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f.label] = counts.get(f.label, 0) + 1
    return ", ".join("%s x%d" % (lbl, n) for lbl, n in sorted(counts.items()))
