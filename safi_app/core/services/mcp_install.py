"""
GUI installation of MCP servers: the policy, in one place (backlog 48).

Everything here is a fixed rule. No model, no judgement, and every rule fails
closed, because the whole feature is "let an admin add a tool from a browser"
and the reason that is normally a bad idea is that the browser is not the
operator's console.

THE THREE MODES
---------------
SAFI_MCP_INSTALL_MODE decides what a browser may install:

  off     Nothing. Servers come from the operator's file only (47b behaviour).
  remote  Hosted endpoints only. Default. Installing one runs no third-party
          code on this host, so an admin pressing the button cannot get shell.
  all     Also package/stdio servers. This is `npx -y something` at boot:
          arbitrary code execution on the host plus a supply-chain fetch. It is
          correct ONLY where the admins and the operator are the same people,
          which is the single-tenant self-hosted case. Stage 2, not built.

WHAT INSTALLING DOES AND DOES NOT DO
------------------------------------
It adds a connector. It grants nothing. The organization must still allow the
connector, a policy must still list it, an agent must still enable it, and the
Will still authorizes every individual call by exact name. That chain is why
making installation easy does not make anything permissive, and it is the first
thing the docs should say.

APPROVAL
--------
An install is pending until a second admin approves it, reusing the knowledge
base rule (item 21) including the sole-administrator exception from 084c1b4: a
lone admin may approve their own install, and it is recorded as a
non-independent review rather than silently treated as one.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ...persistence import database as db
from ...persistence import mcp_store
from ..tool_connectors import CONNECTOR_TOOLS
from . import mcp_registry

log = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_REMOTE = "remote"
MODE_ALL = "all"

_KEY_SAFE = re.compile(r"[^a-z0-9_]+")


def install_mode(config: Any) -> str:
    mode = (getattr(config, "MCP_INSTALL_MODE", "") or MODE_REMOTE).strip().lower()
    return mode if mode in (MODE_OFF, MODE_REMOTE, MODE_ALL) else MODE_REMOTE


def gui_install_enabled(config: Any) -> bool:
    return install_mode(config) != MODE_OFF


def connector_key_for(registry_name: str) -> str:
    """Derive a connector key from a registry name.

    `io.github.someone/weather-mcp` becomes `weather_mcp`. The key becomes a
    string in agents' tools_json, so it has to be short, stable and unique
    across the deployment. Uniqueness is enforced by the caller against both the
    built-in table and the installed rows; this only proposes.
    """
    tail = (registry_name or "").strip().lower().rsplit("/", 1)[-1]
    key = _KEY_SAFE.sub("_", tail).strip("_")
    return key or "mcp_server"


def available_key(registry_name: str) -> str:
    """A connector key nothing else has claimed."""
    base = connector_key_for(registry_name)
    candidate = base
    suffix = 2
    while candidate in CONNECTOR_TOOLS or mcp_store.connector_key_taken(candidate):
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def validate_installable(entry: Dict[str, Any], config: Any) -> Tuple[bool, str, Optional[Dict[str, str]]]:
    """Decide whether this registry entry may be installed from a browser.

    Returns (ok, reason, remote). `reason` is written for an admin to read: a
    refusal that does not say what to do instead just produces a support ticket.
    """
    mode = install_mode(config)
    if mode == MODE_OFF:
        return False, (
            "Installing tool servers from the browser is turned off on this deployment. "
            "An operator can add the server to the file MCP_SERVERS_JSON names."
        ), None

    if not entry.get("has_remote"):
        return False, (
            "This server runs as a local package rather than a hosted endpoint, so it "
            "cannot be installed from here: starting it would run its code on the SAFi "
            "host. An operator can install it in the file MCP_SERVERS_JSON names, where "
            "that decision belongs."
        ), None

    remote = None
    for candidate in entry.get("remotes") or []:
        ok, _ = mcp_registry.validate_remote_url(candidate.get("url", ""))
        if ok:
            remote = candidate
            break
    if remote is None:
        first = (entry.get("remotes") or [{}])[0]
        _, why = mcp_registry.validate_remote_url(first.get("url", ""))
        return False, f"This server's endpoint was refused: {why}", None

    return True, "", remote


def scan_tool_descriptions(tools: Dict[str, Dict[str, Any]], server: str) -> List[str]:
    """Deterministic scan of third-party tool text before it reaches a model.

    Tool names and descriptions are advertised by the server and go into the
    Intellect's context as instructions. For a server an operator chose by hand
    that is a known, accepted risk; for one pulled from a public registry the
    text is reachable by whoever published it, so it gets the same signature
    list Phase Zero already owns. No model call, no judgement: a hit is
    reported, and the caller decides.
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


def runtime_params(row: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a stored row into the shape mcp_runtime.add_server expects."""
    return {
        "label": row.get("title") or row["connector_key"],
        "transport": row.get("transport") or "http",
        "url": row["url"],
    }


def desired_runtime_servers() -> Dict[str, Dict[str, Any]]:
    return {
        row["connector_key"]: runtime_params(row)
        for row in mcp_store.list_active_everywhere()
    }


def can_review_own_install(org_id: str, user_id: str) -> bool:
    """True when this admin is the org's only eligible reviewer.

    Same helper the knowledge base flow uses, so the two features cannot drift
    into different answers about who may sign off alone.
    """
    if not org_id:
        return False
    try:
        return db.count_other_eligible_reviewers(org_id, user_id) == 0
    except Exception as e:
        log.warning("reviewer count failed, treating as not sole reviewer: %s", e)
        return False
