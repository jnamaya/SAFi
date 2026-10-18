"""Terminal UI formatting and rich display for the SAFi CLI.

SAFi Color Palette Philosophy:
    - Primary Brand Accent: Green (#16a34a, #22c55e, #4ade80, #15803d)
    - Dark Canvas / Neutral Axis: (#09090b, #18181b, #27272a, #737373, #ffffff)
    - Semantic Colors: Red (error/blocked/concern), Amber/Yellow (warning/caution), Green (approved/aligned)
"""

from datetime import datetime
import difflib
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console, Group
from rich.control import Control
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.padding import Padding
from rich.text import Text
from rich import box


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse an environment flag accepting 0/false/no/off as falsy."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("", "0", "false", "no", "off")


CLI_MARGIN = int(os.environ.get("SAFI_CLI_MARGIN", "2"))


class MarginedConsole(Console):
    """Console wrapper that applies left and right margins so output doesn't touch the terminal edges."""

    def print(self, *objects, **kwargs):
        pad_margin = kwargs.pop("pad_margin", True)
        interactive = getattr(self, "is_terminal", False)
        if not interactive or CLI_MARGIN <= 0 or not pad_margin or not objects or kwargs.get("end") == "":
            return super().print(*objects, **kwargs)

        if any(isinstance(obj, Control) for obj in objects):
            return super().print(*objects, **kwargs)

        padded_objects = []
        for obj in objects:
            if isinstance(obj, str):
                if not obj:
                    padded_objects.append(obj)
                else:
                    try:
                        text_obj = Text.from_markup(obj) if "[" in obj else Text(obj)
                    except Exception:
                        text_obj = Text(obj)
                    padded_objects.append(Padding(text_obj, (0, CLI_MARGIN)))
            else:
                padded_objects.append(Padding(obj, (0, CLI_MARGIN)))
        return super().print(*padded_objects, **kwargs)


console = MarginedConsole()

# SAFi Brand Tokens
COLOR_BRAND_600 = "#16a34a"
COLOR_BRAND_500 = "#22c55e"
COLOR_BRAND_400 = "#4ade80"
COLOR_BRAND_700 = "#15803d"

# Semantic Verdicts & Scores
COLOR_PASS = "#22c55e"
COLOR_WARN = "#eab308"
COLOR_FAIL = "#ef4444"
COLOR_PENDING = "#a3a3a3"
COLOR_MUTED = "#737373"
COLOR_BORDER = "#27272a"

# User Prompt Theme Tokens
COLOR_USER_ACCENT = "#38bdf8"
COLOR_USER_BORDER = "#2563eb"
COLOR_USER_BG = os.environ.get("SAFI_CLI_USER_BG", "#1e293b")
COLOR_USER_BADGE_BG = "#1e3a5f"

SHOW_AUDIT_PANEL = _env_flag("SAFI_CLI_SHOW_AUDIT", True)


def set_show_audit_panel(flag: bool) -> None:
    """Toggle the compact governance audit footer attached to final responses."""
    global SHOW_AUDIT_PANEL
    SHOW_AUDIT_PANEL = bool(flag)


def get_show_audit_panel() -> bool:
    return SHOW_AUDIT_PANEL


PROGRESS_STAGES: tuple = (
    "checking_request",
    "analyzing",
    "checking_tool",
    "structure",
    "auditing",
    "alignment",
    "finalizing",
)
STAGE_LABELS: Dict[str, str] = {
    "checking_request": "Checking request safeguards",
    "analyzing": "Analyzing the request",
    "checking_tool": "Checking the proposed tool call",
    "structure": "Checking response structure",
    "auditing": "Auditing the response against policy",
    "alignment": "Checking governance alignment",
    "finalizing": "Finalizing the governed response",
}


def print_governance_step(step_text: str, elapsed: float) -> None:
    """Print a completed governance step inline as part of the live activity feed."""
    clean_step = step_text.rstrip(".…").strip()
    if not clean_step or clean_step.lower() in ("governing turn", "analyzing your request"):
        return
    step_line = Text("  ")
    step_line.append("✔ ", style=f"bold {COLOR_PASS}")
    step_line.append(clean_step, style="dim white")
    step_line.append(f" ({elapsed:.1f}s)", style="dim")
    console.print(step_line)


def build_progress_line(
    progress_codes: Optional[List[str]],
    latest_step: Optional[str],
    elapsed: float,
    model: Optional[str] = None,
) -> str:
    """Render a clean live progress line showing the current governance step and elapsed time."""
    codes = [c for c in dict.fromkeys(progress_codes or []) if c in PROGRESS_STAGES]

    step = (latest_step or "").rstrip(".…").strip()
    step_lower = step.lower()
    if step_lower.startswith("drafting"):
        label = f"Drafting response{f' with {model}' if model else ''}"
    elif step:
        label = step
    elif codes:
        label = STAGE_LABELS.get(codes[-1], codes[-1])
    else:
        label = f"Governing turn{f' with {model}' if model else ''}"

    text_width = max((console.width or 80) - 28, 12)
    if len(label) > text_width:
        label = label[: text_width - 1].rstrip() + "…"

    return (
        f"[bold {COLOR_BRAND_400}]SAFi[/] [dim]·[/] [white]{escape(label)}[/] "
        f"[dim]·[/] [dim]{elapsed:.1f}s[/]"
    )


def build_tool_status_line(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    elapsed: float,
) -> str:
    """Render a clean live progress line showing the active tool execution and elapsed time."""
    args = args or {}
    if tool_name == "bash":
        raw_cmd = (args.get("command") or "").strip()
        first_line = raw_cmd.splitlines()[0] if raw_cmd else ""
        if len(first_line) > 36:
            cmd_preview = first_line[:33].rstrip() + "…"
        else:
            cmd_preview = first_line
        label = f"Running bash: {cmd_preview}" if cmd_preview else "Running bash command"
    elif tool_name in ("read", "edit", "write"):
        path = args.get("path") or ""
        verb = "Reading" if tool_name == "read" else ("Editing" if tool_name == "edit" else "Writing")
        label = f"{verb} {path}" if path else f"Executing {tool_name}"
    elif tool_name == "grep":
        pat = args.get("pattern") or ""
        label = f"Searching for '{pat}'" if pat else "Searching with grep"
    elif tool_name == "glob":
        label = f"Finding files matching {args.get('pattern', '*')}"
    elif tool_name == "list":
        label = f"Listing {args.get('path', '.')}"
    elif tool_name in ("task", "delegate_subagent"):
        desc = args.get("description") or ""
        label = f"Subagent task: {desc}" if desc else "Executing subagent task"
    elif tool_name in ("git_status", "git_diff"):
        label = "Running git status" if tool_name == "git_status" else "Inspecting git diff"
    else:
        label = f"Executing {tool_name}"

    text_width = max((console.width or 80) - 28, 12)
    if len(label) > text_width:
        label = label[: text_width - 1].rstrip() + "…"

    return (
        f"[bold {COLOR_BRAND_400}]SAFi[/] [dim]·[/] [white]{escape(label)}[/] "
        f"[dim]·[/] [dim]{elapsed:.1f}s[/]"
    )


def clear_live_status_tail(last_status_markup: Optional[str] = None) -> None:
    """Erase any residual spinner/status lines from the terminal."""
    if not getattr(console, "is_terminal", False):
        return
    try:
        width = max(console.width or 80, 1)
        cells = (Text.from_markup(last_status_markup).cell_len + 4) if last_status_markup else 0
        rows = max(1, (cells + width - 1) // width) if cells else 1
        console.file.write("\r\x1b[2K")
        for _ in range(rows):
            console.file.write("\x1b[1A\r\x1b[2K")
        console.file.flush()
    except Exception:
        pass


def print_banner(
    workspace_root: str,
    agent: str,
    api_url: str,
    user_name: Optional[str] = None,
    intellect_model: Optional[str] = None,
):
    """Render the official SAFi governed workspace header banner."""
    header_text = Text()
    header_text.append("SAFi", style=f"bold {COLOR_BRAND_400}")
    header_text.append(" (The Self-alignment Framework Interface)\n", style="bold white")
    header_text.append("The governance engine for AI agents", style="dim")

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column("label", style="dim", justify="right")
    info_table.add_column("val", style="bold white")

    agent_title = agent.replace("_", " ").title()
    info_table.add_row("Agent Name:", f"{agent_title} ({agent})")
    if intellect_model:
        info_table.add_row("Model:", f"{intellect_model}")
    info_table.add_row("API Endpoint:", f"{api_url}")
    info_table.add_row("Workspace Root:", f"{workspace_root}")
    if user_name:
        info_table.add_row("Active User:", f"{user_name}")

    banner_content = Group(header_text, Text(""), info_table)
    console.print(
        Panel(
            banner_content,
            border_style=COLOR_BRAND_600,
            box=box.ROUNDED,
            expand=False,
            padding=(1, 2),
        )
    )


def render_menu(
    title: str,
    columns: List[Dict[str, Any]],
    rows: List[List[Any]],
    border_style: Optional[str] = None,
) -> Table:
    """Build and print a rounded SAFi-styled menu table from column specs and rows."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style=border_style or COLOR_BRAND_600,
    )
    for col in columns:
        col_opts = dict(col)
        name = col_opts.pop("name")
        table.add_column(name, **col_opts)
    for row in rows:
        table.add_row(*row)
    console.print(table)
    return table


def print_user_prompt(
    prompt: str,
    agent: Optional[str] = None,
    user_name: Optional[str] = None,
) -> None:
    """Render the user's prompt or question with a distinct background band."""
    if not prompt or not prompt.strip():
        return
    agent_label = agent or "software_engineer"
    table = Table.grid(expand=True)
    table.style = f"on {COLOR_USER_BG}"
    table.padding = (0, 1)

    row_text = Text()
    row_text.append("SAFi ", style=f"bold {COLOR_BRAND_400}")
    row_text.append(f"[{agent_label}] › ", style="white")
    row_text.append(prompt.strip(), style=f"bold {COLOR_USER_ACCENT}")

    table.add_row(row_text)
    console.print()
    console.print(table)


def get_input_prompt(agent: Optional[str] = None, user_name: Optional[str] = None) -> str:
    """Format the interactive prompt with SAFi brand label, margin spacing, and distinct style."""
    agent_label = agent or "software_engineer"
    margin = " " * CLI_MARGIN if CLI_MARGIN > 0 else ""
    return (
        f"\n{margin}\001\033[48;2;30;41;59m\033[38;2;74;222;128m\033[1m\002 SAFi \001\033[0m"
        f"\033[48;2;30;41;59m\033[38;2;255;255;255m\002[{agent_label}] › \001\033[0m\033[38;2;56;189;248m\033[1m\002 "
    )


_active_todos: List[Dict[str, Any]] = []


def get_active_todos() -> List[Dict[str, Any]]:
    """Return the currently tracked plan todos."""
    return list(_active_todos)


def set_active_todos(todos: List[Dict[str, Any]]) -> None:
    """Set active plan todos."""
    global _active_todos
    _active_todos = list(todos) if todos else []


def clear_active_todos() -> None:
    """Clear active plan todos."""
    global _active_todos
    _active_todos = []


def mark_active_todos_completed() -> None:
    """Mark all pending or in_progress tasks as completed upon successful final response."""
    global _active_todos
    if not _active_todos:
        return
    for item in _active_todos:
        status = (item.get("status") or "").lower()
        if status in ("pending", "in_progress", "running"):
            item["status"] = "completed"


def advance_active_todo(tool_name: str, args: Dict[str, Any], is_success: bool = True) -> None:
    """Advance the active plan checklist when a real action tool succeeds."""
    global _active_todos
    if not _active_todos or not is_success:
        return
    if tool_name not in ("write", "edit", "patch", "bash", "delete"):
        return

    in_prog_idx = None
    for idx, item in enumerate(_active_todos):
        st = (item.get("status") or "").lower()
        if st in ("in_progress", "running"):
            in_prog_idx = idx
            break

    if in_prog_idx is not None:
        _active_todos[in_prog_idx]["status"] = "completed"
        for next_idx in range(in_prog_idx + 1, len(_active_todos)):
            if (_active_todos[next_idx].get("status") or "").lower() in ("pending", "todo"):
                _active_todos[next_idx]["status"] = "in_progress"
                break
    else:
        for idx, item in enumerate(_active_todos):
            if (item.get("status") or "").lower() in ("pending", "todo"):
                item["status"] = "completed"
                for next_idx in range(idx + 1, len(_active_todos)):
                    if (_active_todos[next_idx].get("status") or "").lower() in ("pending", "todo"):
                        _active_todos[next_idx]["status"] = "in_progress"
                        break
                break


def clear_completed_todos() -> None:
    """Clear active todos if all tasks have been completed."""
    global _active_todos
    if _active_todos and all((t.get("status") or "").lower() in ("completed", "done") for t in _active_todos):
        _active_todos = []


PRICING_PER_1M = {
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-opus": (15.00, 75.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-haiku-5-5": (1.00, 5.00),
    "claude-haiku": (0.25, 1.25),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "deepseek": (0.28, 0.42),
    "llama": (0.59, 0.79),
}


def _estimate_cost(model_name: str, in_t: int, out_t: int) -> Optional[float]:
    if not model_name:
        return None
    model_lower = model_name.lower()
    for k, v in PRICING_PER_1M.items():
        if k in model_lower:
            return (in_t / 1_000_000) * v[0] + (out_t / 1_000_000) * v[1]
    return None


_session_intellect = {"in": 0, "out": 0, "cost": 0.0, "model": ""}
_session_conscience = {"in": 0, "out": 0, "cost": 0.0, "model": ""}
_session_compression = {
    "tokens_before": 0,
    "tokens_after": 0,
    "tokens_saved": 0,
    "reduction_pct": 0.0,
    "active_context": 0,
}
_session_active_context = 0


def reset_session_telemetry():
    """Reset all session telemetry counters for a fresh conversation session."""
    global _session_intellect, _session_conscience, _session_compression, _session_active_context, _active_todos
    _session_intellect = {"in": 0, "out": 0, "cost": 0.0, "model": ""}
    _session_conscience = {"in": 0, "out": 0, "cost": 0.0, "model": ""}
    _session_compression = {
        "tokens_before": 0,
        "tokens_after": 0,
        "tokens_saved": 0,
        "reduction_pct": 0.0,
        "active_context": 0,
    }
    _session_active_context = 0
    _active_todos = []


def record_compression_telemetry(
    tokens_before: int,
    tokens_after: int,
    tokens_saved: int,
    reduction_pct: float = 0.0,
    intellect_model: Optional[str] = None,
    conscience_model: Optional[str] = None,
):
    """Adjust session telemetry when conversational context is compacted."""
    global _session_intellect, _session_conscience, _session_compression, _session_active_context
    _session_compression["tokens_before"] = int(tokens_before or 0)
    _session_compression["tokens_after"] = int(tokens_after or 0)
    _session_compression["tokens_saved"] += max(0, int(tokens_saved or 0))
    _session_compression["reduction_pct"] = float(reduction_pct or 0.0)
    _session_compression["active_context"] = int(tokens_after or 0)
    _session_active_context = int(tokens_after or 0)

    if intellect_model:
        _session_intellect["model"] = intellect_model
    if conscience_model:
        _session_conscience["model"] = conscience_model

    saved = max(0, int(tokens_saved or 0))
    after = max(0, int(tokens_after or 0))
    if saved > 0:
        if _session_intellect["in"] > 0:
            _session_intellect["in"] = max(after, _session_intellect["in"] - saved)
        else:
            _session_intellect["in"] = after

        if _session_conscience["in"] > 0:
            _session_conscience["in"] = max(after, _session_conscience["in"] - saved)
    else:
        _session_intellect["in"] = max(after, _session_intellect["in"])


def record_compression_reset():
    """Clear compression state if memory summary is cleared."""
    global _session_compression
    _session_compression = {
        "tokens_before": 0,
        "tokens_after": 0,
        "tokens_saved": 0,
        "reduction_pct": 0.0,
        "active_context": 0,
    }


def _record_turn_telemetry(result: Dict[str, Any]):
    """Accumulate session token and cost counters across turns for each faculty."""
    global _session_intellect, _session_conscience, _session_active_context
    models_usage = result.get("models_usage")
    if models_usage and isinstance(models_usage, dict):
        intellect_data = models_usage.get("intellect") or {}
        in_t = int(intellect_data.get("prompt_tokens") or 0)
        out_t = int(intellect_data.get("completion_tokens") or 0)
        _session_intellect["in"] += in_t
        _session_intellect["out"] += out_t
        if in_t > 0:
            _session_active_context = in_t
        model_name = intellect_data.get("model") or ""
        if model_name:
            _session_intellect["model"] = model_name
        cost = _estimate_cost(model_name, in_t, out_t)
        if cost is not None:
            _session_intellect["cost"] += cost

        conscience_data = models_usage.get("conscience") or {}
        c_in = int(conscience_data.get("prompt_tokens") or 0)
        c_out = int(conscience_data.get("completion_tokens") or 0)
        _session_conscience["in"] += c_in
        _session_conscience["out"] += c_out
        c_model = conscience_data.get("model") or ""
        if c_model:
            _session_conscience["model"] = c_model
        c_cost = _estimate_cost(c_model, c_in, c_out)
        if c_cost is not None:
            _session_conscience["cost"] += c_cost
    else:
        token_usage = result.get("token_usage")
        ai_prov = result.get("aiProvenance")
        if token_usage and isinstance(token_usage, dict):
            in_t = int(token_usage.get("prompt_tokens") or 0)
            out_t = int(token_usage.get("completion_tokens") or 0)
            _session_intellect["in"] += in_t
            _session_intellect["out"] += out_t
            if in_t > 0:
                _session_active_context = in_t
            if ai_prov and isinstance(ai_prov, dict) and ai_prov.get("model"):
                model_name = ai_prov.get("model")
                _session_intellect["model"] = model_name
                cost = _estimate_cost(model_name, in_t, out_t)
                if cost is not None:
                    _session_intellect["cost"] += cost


def build_telemetry_panel(
    intellect_model: Optional[str] = None,
    conscience_model: Optional[str] = None,
    in_t: int = 0,
    out_t: int = 0,
    c_in: int = 0,
    c_out: int = 0,
) -> Panel:
    """Build the standalone or embedded FACULTY TELEMETRY panel."""
    stats_content = []

    effective_i_model = (
        intellect_model
        or _session_intellect.get("model")
        or "Unknown"
    )
    cost = _estimate_cost(effective_i_model, in_t, out_t) if (in_t or out_t) else None
    cost_str = f" (${cost:.4f})" if cost and cost >= 0.0001 else (" (<$0.0001)" if cost and cost > 0 else "")
    sess_cost = _session_intellect["cost"]
    sess_cost_str = f" (${sess_cost:.4f})" if sess_cost >= 0.0001 else (" (<$0.0001)" if sess_cost > 0 else "")

    t_intellect = Text("Model: ", style="bold white")
    t_intellect.append(str(effective_i_model), style="dim")
    stats_content.append(t_intellect)

    active_ctx = in_t or _session_active_context or _session_compression.get("active_context", 0)
    if active_ctx:
        comp_tag = " [bold green](compacted)[/]" if _session_compression.get("tokens_saved", 0) > 0 else ""
        stats_content.append(Text.from_markup(f"  Active Context: [bold cyan]~{active_ctx:,}[/] tokens{comp_tag}"))

    saved_tokens = _session_compression.get("tokens_saved", 0)
    saved_note = f" [bold green](compacted -{saved_tokens:,})[/]" if saved_tokens > 0 else ""

    if in_t or out_t or _session_intellect["in"]:
        stats_content.append(Text(f"  Turn: {in_t:,} in | {out_t:,} out{cost_str}", style="dim"))
        stats_content.append(Text.from_markup(f"  Session: [bold white]{_session_intellect['in']:,}[/] in | {_session_intellect['out']:,} out{sess_cost_str}{saved_note}"))
    else:
        stats_content.append(Text("  Turn: - | Session: -", style="dim"))

    effective_c_model = (
        conscience_model
        or _session_conscience.get("model")
        or "systemone (Jev)"
    )
    c_cost = _estimate_cost(effective_c_model, c_in, c_out) if (c_in or c_out) else None
    c_cost_str = f" (${c_cost:.4f})" if c_cost and c_cost >= 0.0001 else (" (<$0.0001)" if c_cost and c_cost > 0 else "")
    c_sess_cost = _session_conscience["cost"]
    c_sess_cost_str = f" (${c_sess_cost:.4f})" if c_sess_cost >= 0.0001 else (" (<$0.0001)" if c_sess_cost > 0 else "")

    t_conscience = Text("Auditor: ", style="bold white")
    t_conscience.append(str(effective_c_model), style="dim")
    stats_content.append(t_conscience)
    if c_in or c_out or _session_conscience["in"]:
        stats_content.append(Text(f"  Turn: {c_in:,} in | {c_out:,} out{c_cost_str}", style="dim"))
        stats_content.append(Text.from_markup(f"  Session: [bold white]{_session_conscience['in']:,}[/] in | {_session_conscience['out']:,} out{c_sess_cost_str}"))
    else:
        stats_content.append(Text("  Audit: Deterministic rules (zero token cost)", style="dim italic"))

    total_sess_cost = _session_intellect["cost"] + _session_conscience["cost"]
    if total_sess_cost > 0:
        stats_content.append(Text.from_markup(f"[dim]Total Cost:[/] [bold {COLOR_BRAND_400}]${total_sess_cost:.4f}[/]"))

    return Panel(
        Group(*stats_content),
        title="[bold #4ade80]FACULTY TELEMETRY[/]",
        border_style=COLOR_BRAND_700,
        box=box.ROUNDED,
    )


def build_audit_footer(result: Dict[str, Any]) -> Optional[Text]:
    """Compact one-line governance verdict rendered beneath a governed response."""
    raw_spirit = result.get("spirit_score") or result.get("spiritScore")
    ledger = result.get("conscienceLedger") or []

    passes = cautions = violations = 0
    for entry in ledger:
        s_val = _safe_float(entry.get("score"))
        if s_val is None:
            continue
        if s_val >= 0.7:
            passes += 1
        elif s_val >= 0.0:
            cautions += 1
        else:
            violations += 1

    tier_label = None
    tier_color = COLOR_PASS
    tier_icon = "●"
    score_str = None
    s_val = _safe_float(raw_spirit)
    if s_val is not None:
        score_str = f"{s_val:.1f}/10"
        if s_val >= 7.0:
            tier_label, tier_color, tier_icon = "Aligned", COLOR_PASS, "●"
        elif s_val >= 4.0:
            tier_label, tier_color, tier_icon = "Caution", COLOR_WARN, "▲"
        else:
            tier_label, tier_color, tier_icon = "Concern", COLOR_FAIL, "■"

    if score_str is None and not (passes or cautions or violations):
        return None

    line = Text("  ")
    line.append(f"{tier_icon} ", style=f"bold {tier_color}")
    line.append("Audit ", style="dim")
    if score_str:
        line.append(score_str, style="bold white")
        if tier_label:
            line.append(f" · {tier_label}", style=f"bold {tier_color}")
    tally = []
    if passes:
        tally.append(f"{passes} ✓")
    if cautions:
        tally.append(f"{cautions} ⚠")
    if violations:
        tally.append(f"{violations} ✗")
    if tally:
        prefix = " · rubrics: " if score_str else "rubrics: "
        line.append(f"{prefix}{' '.join(tally)}", style="dim")
    line.append(" · for full audit type ", style="dim")
    line.append("/audit", style=f"bold {COLOR_BRAND_400}")
    return line


def build_session_usage_panel() -> Panel:
    """Standalone session-wide token, cost, and compaction summary for /usage."""
    i = _session_intellect
    c = _session_conscience
    comp = _session_compression
    total_cost = i["cost"] + c["cost"]

    rows = [
        ("Model", i.get("model") or "Unknown"),
        ("Model tokens", f"{i['in']:,} in / {i['out']:,} out"),
        ("Auditor model", c.get("model") or "systemone (Jev)"),
        ("Auditor tokens", f"{c['in']:,} in / {c['out']:,} out"),
    ]
    if comp.get("tokens_saved", 0) > 0:
        rows.append((
            "Compaction",
            f"-{comp['tokens_saved']:,} tokens ({comp.get('reduction_pct', 0.0)}% reduction)",
        ))
        rows.append(("Active context", f"~{comp.get('active_context', 0):,} tokens"))

    body = Table.grid(padding=(0, 2))
    body.add_column("label", style="dim", justify="right")
    body.add_column("val", style="bold white")
    for label, val in rows:
        body.add_row(label + ":", val)
    body.add_row(
        "Total Cost:",
        Text(f"${total_cost:.4f}", style=f"bold {COLOR_BRAND_400}"),
    )

    return Panel(
        body,
        title=f"[bold {COLOR_BRAND_400}]Session Usage[/]",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _detect_lexer(path: str) -> str:
    """Infer syntax highlighting lexer from file extension."""
    ext = Path(path).suffix.lower() if path else ""
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".json": "json",
        ".html": "html",
        ".css": "css",
        ".sh": "bash",
        ".bash": "bash",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".md": "markdown",
        ".sql": "sql",
        ".go": "go",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".diff": "diff",
        ".patch": "diff",
    }
    return mapping.get(ext, "python" if not ext else "text")


MAX_PREVIEW_LINES = 40
_EXIT_CODE_RE = re.compile(r"^exit code (-?\d+)", re.IGNORECASE)
_ERROR_PREFIXES = (
    "error:", "tool execution error", "unknown tool", "rejected:",
    "the will gatekeeper rejected", "the security gate rejected",
    "security gate rejected", "policy gate rejected",
)


def _safe_float(value: Any) -> Optional[float]:
    """Parse a rubric score; malformed values are skipped instead of crashing the render."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result_is_error(result: str) -> bool:
    """Classify a tool result as a failure from its structure."""
    text = (result or "").strip()
    m = _EXIT_CODE_RE.match(text)
    if m:
        return m.group(1) != "0"
    return text.lower().startswith(_ERROR_PREFIXES)


def _fit(text: str, width: int) -> str:
    """Collapse to a single line and truncate to `width` visible characters."""
    flat = " ".join((text or "").split())
    width = max(8, width)
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _cap_lines(text: str, limit: int = MAX_PREVIEW_LINES) -> str:
    lines = (text or "").splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n… {len(lines) - limit} more lines"


def _summarize_args(tool_name: str, args: Dict[str, Any]) -> str:
    """Human-oriented one-line summary of the arguments for a tool call."""
    if tool_name in ("read", "write", "edit", "delete", "remove", "list"):
        path = args.get("path") or args.get("filePath") or args.get("file_path") or "."
        extra = ""
        start = args.get("offset") or args.get("start_line") or args.get("line_start")
        end = args.get("end_line") or args.get("line_end")
        if start or end:
            extra = f"  L{start or 1}-{end or '…'}"
        return f"{path}{extra}"
    if tool_name == "grep":
        where = args.get("path") or "."
        inc = f" ({args['include']})" if args.get("include") else ""
        return f"/{args.get('pattern', '')}/ in {where}{inc}"
    if tool_name == "glob":
        return f"{args.get('pattern', '*')} in {args.get('path') or '.'}"
    if tool_name == "bash":
        return args.get("command") or ""
    if tool_name == "git_diff":
        return ("--staged " if args.get("staged") else "") + (args.get("path") or "")
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _rubric_tags(ledger: List[Dict[str, Any]]) -> Optional[Text]:
    """Inline preflight rubric badges (escaped, crash-safe)."""
    line = Text("  ")
    found = False
    for entry in ledger or []:
        s_val = _safe_float(entry.get("score"))
        if s_val is None:
            continue
        val = str(entry.get("value") or "Standard")
        if s_val >= 0.7:
            line.append(f"✓ {val}  ", style=COLOR_PASS)
        elif s_val >= 0.0:
            line.append(f"⚠ {val}  ", style=COLOR_WARN)
        else:
            line.append(f"✗ {val}  ", style=COLOR_FAIL)
        found = True
    return line if found else None


def _add_diff_stats_line(items: List[Any], adds: int, dels: int) -> None:
    """Append a colored '+N -M' delta line describing an edit proposal."""
    line = Text("  Diff: ", style="dim")
    line.append(f"+{adds}", style=f"bold {COLOR_PASS}")
    line.append(" ", style="dim")
    line.append(f"-{dels}", style=f"bold {COLOR_FAIL}")
    items.append(line)


def print_tool_proposal(name: str, args: Dict[str, Any], res: Dict[str, Any]):
    """Render a clean tool proposal inside the Workspace."""
    _record_turn_telemetry(res)
    if name in ("todowrite", "todo_write"):
        return

    will_decision = res.get("willDecision", "approved")
    will_reason = res.get("willReason")
    is_approved = will_decision in ("approve", "approved")

    items = []

    title_line = Text()
    title_line.append("● SAFi ", style=f"bold {COLOR_BRAND_400}")
    title_line.append("-> ", style="dim")
    title_line.append(f"{name}", style="bold white")
    if is_approved:
        if will_reason:
            clean_reason = will_reason.rstrip(" .")
            suffix = " [approved ✓]"
            prefix_len = len(f"● SAFi -> {name}  # ")
            avail = max((console.width or 80) - prefix_len - len(suffix) - (CLI_MARGIN * 2) - 2, 15)
            if len(clean_reason) > avail:
                clean_reason = clean_reason[:avail - 1].rstrip() + "…"
            title_line.append(f"  # {clean_reason}{suffix}", style="dim")
        else:
            title_line.append("  # approved ✓", style="dim")
    else:
        title_line.append("  [⛔ BLOCKED]", style=f"bold {COLOR_FAIL}")
        if will_reason:
            title_line.append(f"  # {will_reason}", style="dim")
    items.append(title_line)

    ledger = res.get("toolProposalLedger") or res.get("conscienceLedger") or []
    rubric_tags = _rubric_tags(ledger)
    if rubric_tags:
        preflight_text = Text("  Preflight:", style="dim")
        preflight_text.append_text(rubric_tags)
        items.append(preflight_text)

    if name == "bash":
        cmd = _cap_lines(args.get("command", ""), limit=MAX_PREVIEW_LINES)
        if len(cmd.splitlines()) > MAX_PREVIEW_LINES:
            cmd += "\n… [command preview capped]"
        syntax = Syntax(
            cmd,
            "bash",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
            padding=(0, 1),
        )
        items.append(syntax)
    elif name in ("edit", "write"):
        path = args.get("path", "")
        file_line = Text("  File: ", style="dim")
        file_line.append(path, style="bold white")
        items.append(file_line)
        if name == "edit":
            target = args.get("target", "")
            replacement = args.get("replacement", "")

            diff_lines = list(difflib.unified_diff(
                target.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            ))
            diff_text = _cap_lines("".join(diff_lines), limit=MAX_PREVIEW_LINES)
            if len("".join(diff_lines).splitlines()) > MAX_PREVIEW_LINES:
                diff_text += "\n… [diff preview capped]"
            adds = sum(1 for l in "".join(diff_lines).splitlines() if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in "".join(diff_lines).splitlines() if l.startswith("-") and not l.startswith("---"))
            _add_diff_stats_line(items, adds, dels)
            syntax = Syntax(
                diff_text if diff_text else replacement,
                "diff",
                theme="monokai",
                word_wrap=True,
                padding=(0, 1),
            )
            items.append(syntax)
        else:
            code = args.get("content", "")
            preview = code[:600] + ("\n... [truncated]" if len(code) > 600 else "")
            lexer = _detect_lexer(path)
            syntax = Syntax(
                preview,
                lexer,
                theme="monokai",
                word_wrap=True,
                padding=(0, 1),
            )
            items.append(syntax)
    else:
        args_str = _summarize_args(name, args)
        if len(args_str) > 120:
            args_str = args_str[:120] + "..."
        items.append(Text(f"Arguments: {args_str}", style="dim cyan"))

    console.print(Group(*items))


def prompt_user_permission(name: str, args: Dict[str, Any], auto_approve: bool = True) -> bool:
    """Prompt the developer before running mutating tools (bash, write, edit, delete)."""
    if auto_approve or name in ("read", "grep", "glob", "list", "git_status", "git_diff"):
        return True

    margin = " " * CLI_MARGIN if CLI_MARGIN > 0 else ""
    console.print(f"\n{margin}[bold black on {COLOR_WARN}] ⚠️  ACTION CONFIRMATION [/] [bold white]Allow executing tool [cyan]{escape(name)}[/]? [Y/n]:[/] ", end="")
    try:
        choice = input().strip().lower()
        return choice in ("", "y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[{COLOR_WARN}]Action cancelled by user.[/]")
        return False


def prompt_question(question: str, options: Optional[List[str]] = None) -> str:
    """Render an interactive question card for developer clarification and capture input."""
    card_items = [Text(f"❓ {question}", style="bold white")]

    if options and isinstance(options, list):
        card_items.append(Text("\nOptions:", style="dim cyan"))
        for idx, opt in enumerate(options, 1):
            card_items.append(Text(f"  [{idx}] {opt}", style="cyan"))
        card_items.append(Text("  [Enter a number or type your own response]", style="dim italic"))

    panel = Panel(
        Group(*card_items),
        title=f"[bold {COLOR_BRAND_400}]SAFi Clarification[/]",
        border_style=COLOR_BRAND_500,
        box=box.ROUNDED,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)

    margin = " " * CLI_MARGIN if CLI_MARGIN > 0 else ""
    prompt_label = f"{margin}Choice / Answer › "
    try:
        ans = input(prompt_label).strip()
        if options and ans.isdigit():
            idx = int(ans) - 1
            if 0 <= idx < len(options):
                return options[idx]
        return ans if ans else (options[0] if options else "Acknowledged.")
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[{COLOR_WARN}]Clarification skipped by developer.[/]")
        return "Developer skipped answering the question."


def build_plan_panel(todos: Optional[List[Dict[str, Any]]] = None) -> Optional[Panel]:
    """Build a styled Plan & Tasks view showing checklist items and progress in a clean rounded panel."""
    active = todos if todos is not None else _active_todos
    if not active:
        return None

    total = len(active)
    completed = sum(1 for t in active if (t.get("status") or "").lower() in ("completed", "done"))
    pct = int((completed / total) * 100) if total > 0 else 0

    bar_width = 12
    filled = int(round((completed / total) * bar_width)) if total > 0 else 0
    bar_str = "█" * filled + "░" * (bar_width - filled)

    items = []

    # Clean progress bar line
    prog_text = Text()
    prog_text.append("Progress: ", style="dim")
    prog_text.append(f"[{bar_str}] ", style=f"bold {COLOR_BRAND_400}")
    prog_text.append(f"{pct}% ", style="bold white")
    prog_text.append(f"({completed}/{total} completed)\n", style="dim")
    items.append(prog_text)

    # 2-column grid for tasks so multi-line wrapped text stays indented
    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="left", no_wrap=True)
    grid.add_column(justify="left", overflow="fold")

    for item in active:
        task_text = item.get("task") or item.get("description") or ""
        status = (item.get("status") or "pending").lower()
        if status in ("completed", "done"):
            badge = Text("  ✔", style=f"bold {COLOR_PASS}")
            text = Text(task_text, style="dim white")
        elif status in ("in_progress", "running"):
            badge = Text("▶ ⏳", style=f"bold {COLOR_WARN}")
            text = Text(task_text, style="bold #38bdf8")
        elif status in ("failed", "error"):
            badge = Text("  ✖", style=f"bold {COLOR_FAIL}")
            text = Text(task_text, style="bold red")
        else:
            badge = Text("  ○", style="dim")
            text = Text(task_text, style="white")

        grid.add_row(badge, text)

    items.append(grid)

    title = Text()
    title.append(" Plan & Tasks ", style=f"bold {COLOR_BRAND_400}")
    title.append(f"({completed}/{total} • {pct}%) ", style="dim")

    return Panel(
        Group(*items),
        title=title,
        title_align="left",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )


def print_workspace_step(
    tool_name: str,
    args: Dict[str, Any],
    proposal_res: Dict[str, Any],
    result_str: str,
):
    """Render an executed tool step in the Workspace."""
    ws_items = []

    is_approved = proposal_res.get("willDecision", "approved") in ("approve", "approved")
    title_line = Text()
    if is_approved:
        title_line.append("[✓ APPROVED] ", style=f"bold {COLOR_PASS}")
    else:
        title_line.append("[⛔ BLOCKED] ", style=f"bold {COLOR_FAIL}")
    title_line.append("-> ", style="dim")
    title_line.append(f"{tool_name}", style="bold white")
    will_reason = proposal_res.get("willReason")
    if will_reason:
        title_line.append(f"  # {will_reason}", style="dim")
    ws_items.append(title_line)

    ledger = proposal_res.get("toolProposalLedger") or proposal_res.get("conscienceLedger") or []
    rubric_tags = _rubric_tags(ledger)
    if rubric_tags:
        preflight_text = Text("  Preflight:", style="dim")
        preflight_text.append_text(rubric_tags)
        ws_items.append(preflight_text)

    if tool_name == "bash":
        cmd = _cap_lines(args.get("command", ""), limit=MAX_PREVIEW_LINES)
        syntax = Syntax(cmd, "bash", theme="monokai", line_numbers=False, word_wrap=True, padding=(0, 1))
        ws_items.append(syntax)
    elif tool_name in ("edit", "write"):
        path = args.get("path", "")
        file_line = Text("  File: ", style="dim")
        file_line.append(path, style="bold white")
        ws_items.append(file_line)
    elif tool_name not in ("todowrite", "todo_write"):
        args_str = _summarize_args(tool_name, args)
        if len(args_str) > 90:
            args_str = args_str[:90] + "..."
        ws_items.append(Text(f"  Arguments: {args_str}", style="dim cyan"))

    preview = result_str.strip().splitlines()
    first_line = preview[0] if preview else "(no output)"
    max_first_line = min(75, max(25, console.width - 45))
    if len(first_line) > max_first_line:
        first_line = first_line[:max_first_line - 3] + "..."
    line_count = len(preview)
    is_error = _result_is_error(result_str)
    icon = "✖" if is_error else "✔"
    icon_style = COLOR_FAIL if is_error else COLOR_PASS
    action_text = "Failed" if is_error else "Executed"

    res_line = Text("  ")
    res_line.append(f"↳ {icon} ", style=f"bold {icon_style}")
    res_line.append(f"{action_text} ", style="dim")
    res_line.append(f"{tool_name}", style="bold white")
    res_line.append(f": {first_line} ({line_count} line{'s' if line_count != 1 else ''})", style="dim")
    ws_items.append(res_line)

    console.print(Group(*ws_items))


def render_todo_list(todos: List[Dict[str, Any]], align_right: bool = False):
    """Render an active plan/todo checklist inline in the main terminal workspace."""
    global _active_todos
    if not todos:
        return
    _active_todos = list(todos)

    panel = build_plan_panel(_active_todos)
    if not panel:
        return

    console.print()
    console.print(panel)
    console.print()


_recent_tool_results: deque = deque(maxlen=20)


def record_tool_result(name: str, result: str) -> None:
    """Track the full output of a completed tool call for later paging."""
    if not name or name in ("todowrite", "todo_write"):
        return
    _recent_tool_results.append({"tool": name, "result": result})


def get_last_tool_result(name: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Return the most recent tool result, optionally filtered by tool name."""
    if name:
        for entry in reversed(_recent_tool_results):
            if entry["tool"] == name:
                return entry
        return None
    return _recent_tool_results[-1] if _recent_tool_results else None


def list_recent_tool_results() -> List[Dict[str, str]]:
    return list(_recent_tool_results)


def print_full_tool_result(name: Optional[str] = None) -> None:
    """Print the full body of a recent tool result, paged when interactive."""
    entry = get_last_tool_result(name)
    if not entry:
        if name:
            console.print(f"[{COLOR_WARN}]No recent '{escape(name)}' tool result to show.[/]")
        else:
            console.print(f"[{COLOR_WARN}]No recent tool results to show.[/]")
        return
    header = Text()
    header.append(f"Full {entry['tool']} result ", style="bold white")
    header.append(f"({len(entry['result'].splitlines())} lines)", style="dim")
    body_text = Text(entry["result"])
    if getattr(console, "is_terminal", False):
        with console.pager(styles=True):
            console.print(header)
            console.print(body_text)
    else:
        console.print(header)
        console.print(body_text)


def print_tool_result_summary(name: str, result: str, show_error_detail: bool = True):
    """Print a clean execution indicator for completed tool calls, with active plan progress."""
    record_tool_result(name, result)
    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(no output)"
    max_first_line = min(55, max(25, console.width - 45))
    if len(first_line) > max_first_line:
        first_line = first_line[:max_first_line - 3] + "..."
    line_count = len(preview)

    is_error = _result_is_error(result)
    icon = "✖" if is_error else "✔"
    icon_style = COLOR_FAIL if is_error else COLOR_PASS
    action_text = "Failed" if is_error else "Executed"

    line = Text("  ")
    line.append(f"↳ {icon} ", style=f"bold {icon_style}")
    line.append(f"{action_text} ", style="dim")
    line.append(f"{name}", style="bold white")
    line.append(f": {first_line} ({line_count} line{'s' if line_count != 1 else ''})", style="dim")

    if _active_todos and name not in ("todowrite", "todo_write"):
        total = len(_active_todos)
        completed = sum(1 for t in _active_todos if (t.get("status") or "").lower() in ("completed", "done"))
        pct = int((completed / total) * 100) if total > 0 else 0
        line.append(f"  [Plan: {completed}/{total} • {pct}%]", style=f"dim {COLOR_BRAND_400}")

    console.print(line)

    if is_error and show_error_detail and line_count > 1:
        detail_cap = min(line_count, 12)
        detail_lines = []
        for raw in preview[1:detail_cap]:
            detail_lines.append(
                Text(f"    {raw}", style="dim red", overflow="ellipsis", no_wrap=False)
            )
        if line_count > detail_cap:
            note = Text(
                f"    … {line_count - detail_cap} more lines (type /last {name} for the full output)",
                style=f"dim {COLOR_WARN}",
            )
            detail_lines.append(note)
        console.print(Group(*detail_lines))


def print_subagent_start(role: str, description: str):
    """Print the launch indicator for a delegated subagent task."""
    line = Text("  ")
    line.append(f"↳ [Subagent: {role}] ", style="bold #38bdf8")
    line.append(f'Delegated: "{description}"', style="dim")
    console.print(line)


def print_subagent_step(role: str, tool_name: str, args: Dict[str, Any], result: str):
    """Print an inline progress step executed by a child subagent."""
    args_summary = _summarize_args(tool_name, args)

    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(done)"
    if len(first_line) > 70:
        first_line = first_line[:67] + "..."

    line = Text("    ↳ ", style="dim #38bdf8")
    line.append(f"({role}) ", style="dim")
    line.append(f"{tool_name}", style="bold white")
    line.append(f"({args_summary}) -> ", style="dim")
    line.append(first_line, style="dim")
    console.print(line)


def print_subagent_done(role: str, summary: str, steps: int = 1):
    """Print the completion verdict for a subagent."""
    preview = summary.strip().splitlines()
    first_line = preview[0] if preview else "(synthesis complete)"
    if len(first_line) > 90:
        first_line = first_line[:87] + "..."
    line = Text("  ")
    line.append(f"↳ ✓ [Subagent: {role}] ", style=f"bold {COLOR_PASS}")
    line.append(f"Completed in {steps} step{'s' if steps != 1 else ''}: {first_line}", style="dim")
    console.print(line)


def print_final_output(text: str, res: Dict[str, Any]):
    """Render the final governed markdown response in a single workspace."""
    _record_turn_telemetry(res)

    now_str = datetime.now().strftime("%H:%M:%S")
    w = console.width
    margin = CLI_MARGIN if getattr(console, "is_terminal", False) else 0
    avail = w - (margin * 2) - 6
    left_text = Text.from_markup(f"[bold {COLOR_BRAND_400}]● SAFI Response[/] ")
    right_text = Text.from_markup(f" [dim]{now_str}[/dim]")
    gap = avail - (left_text.cell_len + right_text.cell_len)

    if gap >= 2:
        top_title = Text.assemble(left_text, ("─" * gap, COLOR_BRAND_600), right_text)
        title_align = "left"
    else:
        top_title = f"[bold {COLOR_BRAND_400}]● SAFI Response[/]"
        title_align = "center"

    response_panel = Panel(
        Markdown(text),
        title=top_title,
        title_align=title_align,
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
        padding=(1, 2),
    )

    console.print()
    console.print(response_panel)

    if get_show_audit_panel():
        footer = build_audit_footer(res)
        if footer is not None:
            console.print(footer)


def print_audit_details(result: Dict[str, Any]):
    """Detailed drill-down of all policy rubrics, scores, confidence, and rationales."""
    ledger = result.get("conscienceLedger") or []
    if not ledger:
        console.print(f"[{COLOR_WARN}]No governance audit ledger available for this turn.[/]")
        return

    policy_title = result.get("policyName") or result.get("policyId") or "Domain Policy"
    table = Table(title=f"Detailed Governance Audit: {policy_title}", box=box.ROUNDED, border_style=COLOR_BRAND_600)
    table.add_column("Rubric / Value", style="bold white")
    table.add_column("Score", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Rationale", style="dim")

    for entry in ledger:
        val = str(entry.get("value") or "Standard")
        s_val = _safe_float(entry.get("score"))
        rationale = str(entry.get("rationale") or entry.get("reason") or "—")
        if s_val is None:
            continue
        if s_val >= 0.7:
            status = f"[bold {COLOR_PASS}]PASS[/]"
            score_text = Text(f"+{s_val:.2f}", style=f"bold {COLOR_PASS}")
        elif s_val >= 0.0:
            status = f"[bold {COLOR_WARN}]CAUTION[/]"
            score_text = Text(f"+{s_val:.2f}", style=f"bold {COLOR_WARN}")
        else:
            status = f"[bold {COLOR_FAIL}]VIOLATION[/]"
            score_text = Text(f"{s_val:.2f}", style=f"bold {COLOR_FAIL}")

        table.add_row(escape(val), score_text, status, escape(rationale))

    console.print(table)


def print_error(message: str):
    """Render an error message panel."""
    console.print(Panel(f"[bold {COLOR_FAIL}]Error:[/] {escape(message)}", border_style=COLOR_FAIL, box=box.ROUNDED))


def print_compression_result(data: Dict[str, Any]):
    """Render a clean summary panel for context compression and token savings."""
    if not data.get("ok"):
        error_msg = data.get("error", "Unknown error during compression.")
        console.print(Panel(f"[bold {COLOR_FAIL}]Compression Error:[/] {escape(str(error_msg))}", border_style=COLOR_FAIL, box=box.ROUNDED))
        return

    if not data.get("compressed"):
        msg = data.get("message", "Conversation is already minimal (no compression needed).")
        console.print(f"[dim]{escape(str(msg))}[/dim]")
        if data.get("summary"):
            console.print(Panel(
                Markdown(data["summary"]),
                title=f"[bold {COLOR_BRAND_400}]Active Compacted Memory[/]",
                border_style=COLOR_BRAND_600,
                box=box.ROUNDED,
            ))
        return

    turns = data.get("turns_count", 0)
    before = data.get("tokens_before", 0)
    after = data.get("tokens_after", 0)
    saved = data.get("tokens_saved", 0)
    pct = data.get("reduction_pct", 0.0)
    summary_text = data.get("summary", "")

    stats = (
        f"  [bold white]Messages Compacted:[/]    [cyan]{turns}[/] turns\n"
        f"  [bold white]Context Tokens Before:[/]   [dim]~{before:,} tokens[/]\n"
        f"  [bold white]Context Tokens After:[/]    [bold {COLOR_PASS}]~{after:,} tokens[/]\n"
        f"  [bold white]Tokens Saved:[/]            [bold {COLOR_PASS}]~{saved:,} tokens[/] [bold green]({pct}% reduction)[/]\n"
        f"  [bold white]Session Net Tokens:[/]      [bold cyan]~{_session_intellect['in']:,} in[/] [dim](compaction reduction applied)[/dim]"
    )
    console.print(Panel(
        stats,
        title=f"[bold {COLOR_BRAND_400}]Context Compression & Token Savings[/]",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
    ))

    if summary_text:
        console.print(Panel(
            Markdown(summary_text),
            title=f"[bold {COLOR_BRAND_400}]Compacted Technical Memory[/]",
            subtitle="[dim]Anchored into session context for future turns[/dim]",
            border_style=COLOR_BRAND_700,
            box=box.ROUNDED,
        ))

    console.print(build_telemetry_panel())
