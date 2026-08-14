"""
Helpers shared by the operator CLI and by discovery (backlog 48, reduced by 48d).

This module used to carry the policy for installing servers from a browser:
install modes, endpoint validation, approval, the sole-reviewer rule. All of it
went when installation moved to the CLI, because none of it had a caller left.
A server now arrives one way, from the operator's file, and the only questions
remaining are what to call it and whether its own description of itself is safe
to put in front of a model.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ..tool_connectors import CONNECTOR_TOOLS

log = logging.getLogger(__name__)

_KEY_SAFE = re.compile(r"[^a-z0-9_]+")

# Labels that identify no one. Stripped so a policy author is not asked to
# authorize a connector called "mcp" or "api".
_HOST_NOISE = ("mcp", "api", "www", "server", "servers", "app", "co")


def connector_key_for_url(url: str) -> str:
    """Derive a connector key from an endpoint.

    `https://mcp.deepwiki.com/mcp` becomes `deepwiki`, `https://tandem.ac/mcp`
    becomes `tandem`. The last label is always a TLD and carries no meaning, so
    it goes first; generic service prefixes go next; what is left is the name a
    person would use for the thing.
    """
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    labels = [p for p in host.split(".") if p]
    if len(labels) > 1:
        labels = labels[:-1]
    meaningful = [p for p in labels if p not in _HOST_NOISE]
    candidate = (meaningful or labels or [""])[-1]
    return _KEY_SAFE.sub("_", candidate).strip("_") or "mcp_server"


def scan_tool_descriptions(tools: Dict[str, Dict[str, Any]], server: str) -> List[str]:
    """Deterministic scan of third-party tool text before it reaches a model.

    Tool names and descriptions are advertised by the server and enter the
    Intellect's context as instructions. The operator chose the server, so this
    is not a gate; it is a report, run once at discovery, using the signature
    list Phase Zero already owns. No model call and no judgement: a hit is
    printed, and a person decides what it means.
    """
    from ..threat_intel import EMBEDDED_INSTRUCTION_MARKERS, INJECTION_SIGNATURES

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
    """A connector key nothing else has claimed."""
    candidate = base
    suffix = 2
    while candidate in CONNECTOR_TOOLS or candidate in taken:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
