"""Generic engine for caller-supplied sensitive-identifier validator data."""
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Mapping, Any
from functools import lru_cache


class Finding(NamedTuple):
    key: str
    label: str
    start: int
    end: int


@lru_cache(maxsize=128)
def _compile_pattern(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def catalogue(specs: Optional[Mapping[str, Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Render the supplied validator definitions for a configuration surface."""
    return [
        {"key": key, "label": spec.get("label", key), "note": spec.get("note", "")}
        for key, spec in (specs or {}).items()
    ]


def normalize(
    keys: Optional[Sequence[str]],
    specs: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Keep only identifiers declared in the caller-provided validator set."""
    if not keys or not specs:
        return []
    given = {str(key).strip().lower() for key in keys}
    return [key for key in specs if key.lower() in given]


def _normalized_value(raw: str, mode: Optional[str]) -> str:
    if mode == "digits":
        return re.sub(r"\D", "", raw)
    if mode == "alphanumeric_upper":
        return re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    return raw


def _luhn_ok(digits: str) -> bool:
    total, double = 0, False
    for char in reversed(digits):
        digit = ord(char) - 48
        if double:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double = not double
    return total % 10 == 0


def _mod97_ok(value: str) -> bool:
    if len(value) < 4:
        return False
    rearranged = value[4:] + value[:4]
    try:
        digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
        return int(digits) % 97 == 1
    except ValueError:
        return False


def _passes_validation(match, raw: str, spec: Dict[str, Any]) -> bool:
    rule = spec.get("validation") or {}
    kind = rule.get("type")
    value = _normalized_value(raw, spec.get("normalization"))
    if kind == "luhn":
        return (int(rule.get("minimum", 0)) <= len(value) <= int(rule.get("maximum", 10**9))
                and value.isdigit() and _luhn_ok(value))
    if kind == "mod97":
        return (int(rule.get("minimum", 0)) <= len(value) <= int(rule.get("maximum", 10**9))
                and _mod97_ok(value))
    if kind == "weighted_modulo":
        weights = rule.get("weights") or []
        if not value.isdigit() or len(value) != int(rule.get("length", -1)) or len(value) != len(weights):
            return False
        return sum(int(digit) * int(weight) for digit, weight in zip(value, weights)) % int(rule["modulus"]) == 0
    if kind == "excluded_groups":
        for group_rule in rule.get("groups") or []:
            try:
                part = match.group(int(group_rule["index"]))
            except (IndexError, KeyError, TypeError, ValueError):
                return False
            if part in (group_rule.get("values") or []):
                return False
            if any(part.startswith(prefix) for prefix in (group_rule.get("prefixes") or [])):
                return False
        return True
    return False


def scan(
    text: str,
    enabled: Optional[Sequence[str]],
    specs: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> List[Finding]:
    """Find and validate matches described by the supplied catalogue data."""
    catalog = specs or {}
    keys = normalize(enabled, catalog)
    if not keys or not text:
        return []
    findings: List[Finding] = []
    for key in keys:
        spec = catalog[key]
        pattern = spec.get("pattern")
        if isinstance(pattern, str):
            pattern = _compile_pattern(pattern)
        if not hasattr(pattern, "finditer"):
            raise ValueError(f"Validator '{key}' has no usable pattern")
        for match in pattern.finditer(text):
            raw = match.group(0)
            if _passes_validation(match, raw, spec):
                findings.append(Finding(key, str(spec.get("label") or key), match.start(), match.end()))
    findings.sort(key=lambda finding: finding.start)
    return findings


def redact(
    text: str,
    enabled: Optional[Sequence[str]],
    specs: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> str:
    findings = scan(text, enabled, specs)
    if not findings:
        return text
    out, cursor = [], 0
    for finding in findings:
        if finding.start < cursor:
            continue
        out.append(text[cursor:finding.start])
        out.append(f"[REDACTED:{finding.key}]")
        cursor = finding.end
    out.append(text[cursor:])
    return "".join(out)


def summarize(findings: Sequence[Finding]) -> str:
    """Summarize match counts without including the matched values."""
    counts: Dict[str, int] = {}
    for finding in findings or []:
        counts[finding.label] = counts.get(finding.label, 0) + 1
    return ", ".join(f"{label} x{count}" for label, count in sorted(counts.items()))
