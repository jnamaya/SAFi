from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ..tool_connectors import CONNECTOR_TOOLS

log = logging.getLogger(__name__)

_KEY_SAFE = re.compile(r"[^a-z0-9_]+")

_HOST_NOISE = ("mcp", "api", "www", "server", "servers", "app", "co")


def connector_key_for_url(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    labels = [p for p in host.split(".") if p]
    if len(labels) > 1:
        labels = labels[:-1]
    meaningful = [p for p in labels if p not in _HOST_NOISE]
    candidate = (meaningful or labels or [""])[-1]
    return _KEY_SAFE.sub("_", candidate).strip("_") or "mcp_server"


def scan_tool_descriptions(tools: Dict[str, Dict[str, Any]], server: str) -> List[str]:
    from ...security_policy import EMBEDDED_INSTRUCTION_MARKERS, INJECTION_SIGNATURES

    findings: List[str] = []
    for name, spec in tools.items():
        if spec.get("server") != server:
            continue
        haystack = f"{name} {spec.get('description', '')}".lower()
        for category, phrases in INJECTION_SIGNATURES.items():
            for phrase in phrases:
                if phrase.lower() in haystack:
                    findings.append(f"{name}: {category} ({phrase!r})")
        for marker in EMBEDDED_INSTRUCTION_MARKERS:
            if marker.lower() in haystack:
                findings.append(f"{name}: embedded instruction marker ({marker!r})")
    return findings


def available_key(base: str, taken=()) -> str:
    candidate = base
    suffix = 2
    while candidate in CONNECTOR_TOOLS or candidate in taken:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
