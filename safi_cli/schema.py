"""Typed schema contract for the /api/agentic/process_prompt response.

Turns silent ``KeyError``/``dict.get`` drift in main.py into a single,
fail-loud normalization point: ``normalize_turn_response`` validates the
server payload once and returns a well-formed dict every consumer can trust.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("safi.schema")

# The server may omit "type" for final text-only turns; a payload with
# neither "type" nor "finalOutput" is treated as malformed below.
REQUIRED_KEYS: tuple = ()


class SchemaError(ValueError):
    """Raised when the server response violates the client's contract."""


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalize_tool_proposal(prop: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce one tool proposal into canonical client-side shape."""
    out = dict(prop)
    name = _as_str(prop.get("tool_name") or prop.get("name") or prop.get("tool"))
    args = (
        prop.get("parameters")
        if isinstance(prop.get("parameters"), dict)
        else (
            prop.get("params")
            if isinstance(prop.get("params"), dict)
            else (
                prop.get("arguments")
                if isinstance(prop.get("arguments"), dict)
                else {}
            )
        )
    )
    out["tool_name"] = name
    out["parameters"] = args
    out["params"] = args
    out["arguments"] = args
    out["result"] = prop.get("result")
    out["executed_by"] = _as_str(prop.get("executed_by"))
    return out


def normalize_turn_response(data: Any) -> Dict[str, Any]:
    """Validate and normalize a process_prompt response payload.

    Raises SchemaError when the payload is not a dict or lacks required keys,
    so callers fail loudly instead of silently mis-rendering a turn.
    """
    if not isinstance(data, dict):
        raise SchemaError(f"process_prompt response is {type(data).__name__}, expected object")
    if "type" not in data and "finalOutput" not in data:
        # Legacy/simple payloads like {"ok": true} are treated as empty finals.
        if not data.get("ok"):
            raise SchemaError("process_prompt response has neither 'type' nor 'finalOutput'")

    out = dict(data)
    resp_type = _as_str(data.get("type"), "final")
    calls: List[Dict[str, Any]] = []
    if resp_type == "tool_call":
        batch = data.get("tool_calls")
        if isinstance(batch, list) and batch:
            calls = [normalize_tool_proposal(p) for p in batch if isinstance(p, dict)]
        else:
            calls = [normalize_tool_proposal(data)]

    executed: List[Dict[str, Any]] = _as_list(data.get("toolCalls"))
    if not executed:
        executed = _as_list(data.get("tool_calls")) if resp_type != "tool_call" else []

    out["type"] = resp_type
    out["finalOutput"] = _as_str(data.get("finalOutput"))
    out["willDecision"] = _as_str(data.get("willDecision"), "approve")
    out["tool_calls"] = calls
    out["toolCalls"] = executed
    out["messageId"] = _as_str(data.get("messageId") or data.get("message_id"))
    out["usage"] = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    out["raw"] = data
    return out
