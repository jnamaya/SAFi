"""Client-side context management: tool_result truncation and ID tagging.

Mirrors the server's bounding idioms (core/orchestrator.py _bound_result):
shrink *result bodies only*, never drop entries, so server-side task-state
counts and reconciliation stay structurally intact. Older results get a
75/25 head+tail window; the newest results are preserved verbatim.
"""

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("safi.context")

DEFAULT_MAX_CHARS = int(os.environ.get("SAFI_CLI_RESULT_MAX_CHARS", "8000"))
DEFAULT_NEW_KEPT = int(os.environ.get("SAFI_CLI_RESULT_NEW_KEPT", "3"))
DEFAULT_TOTAL_CAP = int(os.environ.get("SAFI_CLI_RESULT_TOTAL_CAP", "60"))

TRUNC_MARKER = "\n... [result truncated; showing first {head} and last {tail} of {total} chars]"


def _bound_result(body: str, max_chars: int) -> str:
    """Return body bounded to max_chars using a 75/25 head+tail window."""
    if len(body) <= max_chars:
        return body
    head = int(max_chars * 0.75)
    tail = max_chars - head
    marker = TRUNC_MARKER.format(head=head, tail=tail, total=len(body))
    return body[:head] + marker + "\n" + body[len(body) - tail:]


def truncate_tool_results(
    tool_results: List[Dict[str, Any]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    new_kept: int = DEFAULT_NEW_KEPT,
    total_cap: int = DEFAULT_TOTAL_CAP,
) -> List[Dict[str, Any]]:
    """Return a bounded copy of tool_results.

    - The newest `new_kept` entries keep full result bodies.
    - Older entries get result bodies bounded via _bound_result.
    - Entries beyond `total_cap` oldest are dropped and summarized in a
      harness_note so the server knows history was windowed client-side.
    - Every entry carries a stable `result_id` for ID-based reconciliation.
    """
    if not tool_results:
        return []

    bounded: List[Dict[str, Any]] = []
    dropped = 0
    overflow = max(0, len(tool_results) - total_cap)
    start = overflow
    if overflow:
        dropped = overflow

    for idx, tr in enumerate(tool_results[start:], start=start):
        if not isinstance(tr, dict):
            continue
        entry = dict(tr)
        if "result_id" not in entry:
            entry["result_id"] = f"tr-{idx}"
        result = entry.get("result")
        if isinstance(result, str):
            if idx >= len(tool_results) - new_kept:
                entry["result"] = result
            else:
                entry["result"] = _bound_result(result, max_chars)
        else:
            entry["result"] = str(result) if result is not None else ""
            if idx < len(tool_results) - new_kept:
                entry["result"] = _bound_result(entry["result"], max_chars)
        bounded.append(entry)

    if dropped:
        bounded.insert(0, {
            "tool_name": "harness_note",
            "arguments": {},
            "result": (
                f"[Harness] Context windowing: {dropped} oldest tool results "
                "were dropped client-side to bound context. Reference them "
                "again if needed rather than assuming their contents."
            ),
        })
    return bounded
