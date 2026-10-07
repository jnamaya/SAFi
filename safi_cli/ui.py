"""Terminal UI formatting and rich display for the SAFi CLI.

SAFi Color Palette Philosophy:
    - Primary Brand Accent: Green (#16a34a, #22c55e, #4ade80, #15803d)
    - Dark Canvas / Neutral Axis: (#09090b, #18181b, #27272a, #737373, #ffffff)
    - Semantic Colors: Red (error/blocked/concern), Amber/Yellow (warning/caution), Green (approved/aligned)
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.padding import Padding
from rich.text import Text
from rich import box

console = Console()

# SAFi Brand Tokens
COLOR_BRAND_600 = "#16a34a"  # Primary brand green
COLOR_BRAND_500 = "#22c55e"  # Accent green
COLOR_BRAND_400 = "#4ade80"  # Light brand highlight / center rosetta
COLOR_BRAND_700 = "#15803d"  # Dark green borders

# Semantic Verdicts & Scores (matching SAFi web specification)
COLOR_PASS = "#22c55e"       # Aligned (>= 8.0) / Rubric pass (>= 0.7)
COLOR_WARN = "#eab308"       # Caution (5.0..7.9) / Rubric warning (0.0..0.7)
COLOR_FAIL = "#ef4444"       # Concern (< 5.0) / Rubric violation (< 0.0)
COLOR_PENDING = "#a3a3a3"    # Neutral-400 / Audit pending
COLOR_MUTED = "#737373"      # Neutral-500
COLOR_BORDER = "#27272a"     # Dark border neutral

# User Prompt Theme Tokens (Elevated Contrast)
COLOR_USER_ACCENT = "#38bdf8"   # Bright Sky / Cyan 400
COLOR_USER_BORDER = "#2563eb"   # Vibrant Blue 600
COLOR_USER_BG = os.environ.get("SAFI_CLI_USER_BG", "#182234")  # Deep Midnight / Slate Navy background
COLOR_USER_BADGE_BG = "#1e3a5f" # Background for prompt badge / input chip


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

    # Format agent title nicely
    agent_title = agent.replace("_", " ").title()
    info_table.add_row("Agent Persona:", f"{agent_title} ({agent})")
    if intellect_model:
        info_table.add_row("Intellect Model:", f"{intellect_model}")
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


def print_user_prompt(
    prompt: str,
    agent: Optional[str] = None,
    user_name: Optional[str] = None,
) -> None:
    """Render the user's prompt or question with a distinct background band (no borders, keeping SAFi label)."""
    if not prompt or not prompt.strip():
        return
    agent_label = agent or "software_engineer"
    table = Table.grid(expand=True)
    table.style = f"on {COLOR_USER_BG}"
    table.padding = (0, 1)

    row_text = Text()
    row_text.append("SAFi ", style=f"bold {COLOR_BRAND_400}")
    row_text.append(f"[{agent_label}] › ", style="white")
    row_text.append(prompt.strip(), style="bold white")

    table.add_row(row_text)
    console.print()
    console.print(table)


def get_input_prompt(agent: Optional[str] = None, user_name: Optional[str] = None) -> str:
    """Format the interactive prompt with SAFi brand label and a distinct background."""
    agent_label = agent or "software_engineer"
    # GNU readline non-printing delimiters \001 and \002 ensure prompt width is measured accurately
    return (
        f"\n\001\033[48;2;30;41;59m\033[38;2;74;222;128m\033[1m\002 SAFi \001\033[0m"
        f"\033[48;2;30;41;59m\033[38;2;255;255;255m\002[{agent_label}] › \001\033[0m\002 "
    )


_spirit_history: List[float] = []

def _get_sparkline(data: List[float], width: int = 10) -> str:
    if not data:
        return ""
    plot_data = data[-width:]
    chars = " ▂▃▄▅▆▇█"
    min_val, max_val = min(plot_data), max(plot_data)
    if max_val == min_val:
        return chars[len(chars)//2] * len(plot_data)

    return "".join(chars[int((v - min_val) / (max_val - min_val) * (len(chars) - 1))] for v in plot_data)


PRICING_PER_1M = {
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-opus": (15.00, 75.00),
    "claude-3-haiku": (0.25, 1.25),
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
    global _session_intellect, _session_conscience, _session_compression, _session_active_context
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

    # Explicitly reduce session input tokens baseline to reflect compaction savings
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
        # Intellect
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

        # Conscience
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

    # Intellect Faculty
    effective_i_model = (
        intellect_model
        or _session_intellect.get("model")
        or "Unknown"
    )
    cost = _estimate_cost(effective_i_model, in_t, out_t) if (in_t or out_t) else None
    cost_str = f" (${cost:.4f})" if cost and cost >= 0.0001 else (" (<$0.0001)" if cost and cost > 0 else "")
    sess_cost = _session_intellect["cost"]
    sess_cost_str = f" (${sess_cost:.4f})" if sess_cost >= 0.0001 else (" (<$0.0001)" if sess_cost > 0 else "")

    stats_content.append(Text.from_markup(f"[bold white]Intellect:[/] [dim]{effective_i_model}[/]"))

    # Active Context Window
    active_ctx = in_t or _session_active_context or _session_compression.get("active_context", 0)
    if active_ctx:
        comp_tag = " [bold green](compacted)[/]" if _session_compression.get("tokens_saved", 0) > 0 else ""
        stats_content.append(Text.from_markup(f"  Active Context: [bold cyan]~{active_ctx:,}[/] tokens{comp_tag}"))

    # Turn & Session Tokens
    saved_tokens = _session_compression.get("tokens_saved", 0)
    saved_note = f" [bold green](compacted -{saved_tokens:,})[/]" if saved_tokens > 0 else ""

    if in_t or out_t or _session_intellect["in"]:
        stats_content.append(Text(f"  Turn: {in_t:,} in | {out_t:,} out{cost_str}", style="dim"))
        stats_content.append(Text.from_markup(f"  Session: [bold white]{_session_intellect['in']:,}[/] in | {_session_intellect['out']:,} out{sess_cost_str}{saved_note}"))
    else:
        stats_content.append(Text("  Turn: - | Session: -", style="dim"))

    # Conscience Faculty
    effective_c_model = (
        conscience_model
        or _session_conscience.get("model")
        or "systemone (Jev)"
    )
    c_cost = _estimate_cost(effective_c_model, c_in, c_out) if (c_in or c_out) else None
    c_cost_str = f" (${c_cost:.4f})" if c_cost and c_cost >= 0.0001 else (" (<$0.0001)" if c_cost and c_cost > 0 else "")
    c_sess_cost = _session_conscience["cost"]
    c_sess_cost_str = f" (${c_sess_cost:.4f})" if c_sess_cost >= 0.0001 else (" (<$0.0001)" if c_sess_cost > 0 else "")

    stats_content.append(Text.from_markup(f"[bold white]Conscience:[/] [dim]{effective_c_model}[/]"))
    if c_in or c_out or _session_conscience["in"]:
        stats_content.append(Text(f"  Turn: {c_in:,} in | {c_out:,} out{c_cost_str}", style="dim"))
        stats_content.append(Text.from_markup(f"  Session: [bold white]{_session_conscience['in']:,}[/] in | {_session_conscience['out']:,} out{c_sess_cost_str}"))
    else:
        stats_content.append(Text("  Audit: Jev / TypeSafe (deterministic)", style="dim italic"))

    # Total Session Expenditure
    total_sess_cost = _session_intellect["cost"] + _session_conscience["cost"]
    if total_sess_cost > 0:
        stats_content.append(Text.from_markup(f"[dim]Total Cost:[/] [bold {COLOR_BRAND_400}]${total_sess_cost:.4f}[/]"))

    return Panel(
        Group(*stats_content),
        title="[bold #4ade80]FACULTY TELEMETRY[/]",
        border_style=COLOR_BRAND_700,
        box=box.ROUNDED,
    )


def _build_scoreboard_panel(result: Dict[str, Any]) -> Any:
    """Build the Governance Scorecard panel with SAFi palette styling."""
    ledger = result.get("conscienceLedger") or []
    raw_spirit = result.get("spirit_score") or result.get("spiritScore")
    spirit_note = result.get("spiritNote")

    panels = []

    # 1. Alignment Score Section (0 - 10 scale matching SAFi web app)
    if raw_spirit is not None:
        try:
            val = float(raw_spirit)
            _spirit_history.append(val)
            spark = _get_sparkline(_spirit_history, width=8)

            # Thresholds: >= 8.0 Aligned (Green), 5.0..7.9 Caution (Amber), < 5.0 Concern (Red)
            if val >= 8.0:
                tier_label = "Aligned"
                tier_color = COLOR_PASS
                tier_icon = "●"
            elif val >= 5.0:
                tier_label = "Caution"
                tier_color = COLOR_WARN
                tier_icon = "▲"
            else:
                tier_label = "Concern"
                tier_color = COLOR_FAIL
                tier_icon = "■"

            score_text = Text()
            score_text.append(f"{tier_icon} {tier_label}\n", style=f"bold {tier_color}")
            score_text.append(f"{val:.1f} / 10", style="bold white")
            if spark:
                score_text.append(f"  {spark}\n", style=tier_color)
            else:
                score_text.append("\n")

            if spirit_note:
                score_text.append(f"{spirit_note}", style="dim")

            panels.append(
                Panel(
                    score_text,
                    title="[bold #4ade80]ALIGNMENT SCORE[/]",
                    border_style=COLOR_BRAND_700,
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )
        except (ValueError, TypeError):
            pass

    # 2. Conscience Policy Rubric Table
    table = Table(expand=True, show_header=False, box=None, padding=(0, 1))
    table.add_column("Metric", style="white")
    table.add_column("Score", justify="right")

    has_scores = False
    for entry in ledger:
        score = entry.get("score")
        if score is None:
            continue

        has_scores = True
        val = entry.get("value") or "Standard"
        score_val = float(score)
        if score_val >= 0.7:
            table.add_row(f"[bold {COLOR_PASS}]✓[/] {val}", Text(f"+{score_val:.2f}", style=f"bold {COLOR_PASS}"))
        elif score_val >= 0.0:
            table.add_row(f"[bold {COLOR_WARN}]⚠[/] {val}", Text(f"+{score_val:.2f}", style=f"bold {COLOR_WARN}"))
        else:
            table.add_row(f"[bold {COLOR_FAIL}]✗[/] {val}", Text(f"{score_val:.2f}", style=f"bold {COLOR_FAIL}"))

    if has_scores:
        policy_title = result.get("policyName") or result.get("policyId")
        title = f"[bold #4ade80]POLICY AUDIT:[/] [white]{policy_title}[/]" if policy_title else "[bold #4ade80]POLICY AUDIT[/]"
        panels.append(Panel(table, title=title, border_style=COLOR_BRAND_700, box=box.ROUNDED))

    # 3. Models Stats Breakdown
    models_usage = result.get("models_usage") or {}
    intellect_data = models_usage.get("intellect") or {}
    ai_prov = result.get("aiProvenance") or {}
    intellect_model = (
        intellect_data.get("model")
        or result.get("intellectModel")
        or (ai_prov.get("model") if isinstance(ai_prov, dict) else None)
        or "Unknown"
    )
    token_usage = intellect_data if "prompt_tokens" in intellect_data else (result.get("token_usage") or {})
    in_t = int(token_usage.get("prompt_tokens") or 0)
    out_t = int(token_usage.get("completion_tokens") or 0)

    conscience_data = models_usage.get("conscience") or {}
    conscience_model = (
        conscience_data.get("model")
        or result.get("conscienceModel")
        or "systemone (Jev)"
    )
    c_in = int(conscience_data.get("prompt_tokens") or 0)
    c_out = int(conscience_data.get("completion_tokens") or 0)

    panels.append(build_telemetry_panel(
        intellect_model=intellect_model,
        conscience_model=conscience_model,
        in_t=in_t,
        out_t=out_t,
        c_in=c_in,
        c_out=c_out,
    ))

    if not panels:
        return Text("")

    return Panel(
        Group(*panels),
        title="[bold #4ade80]Governance Audit[/]",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
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


def print_tool_proposal(name: str, args: Dict[str, Any], res: Dict[str, Any]):
    """Render a clean tool proposal without borders, applying SAFi colors directly."""
    _record_turn_telemetry(res)
    will_decision = res.get("willDecision", "approved")
    will_reason = res.get("willReason")
    is_approved = will_decision in ("approve", "approved")

    items = []

    # Title line with clean styled verdict tag
    title_line = Text()
    if is_approved:
        title_line.append("[✓ APPROVED] ", style=f"bold {COLOR_PASS}")
    else:
        title_line.append("[⛔ BLOCKED] ", style=f"bold {COLOR_FAIL}")

    title_line.append("-> ", style="dim")
    title_line.append(f"{name}", style="bold white")
    if will_reason:
        title_line.append(f"  # {will_reason}", style="dim")
    items.append(title_line)

    # Inline Policy Preflight Audit: Display rubric badges directly on the stream
    ledger = res.get("toolProposalLedger") or res.get("conscienceLedger") or []
    audit_tags = []
    for entry in ledger:
        score = entry.get("score")
        if score is not None:
            val = entry.get("value", "")
            s_val = float(score)
            if s_val >= 0.7:
                audit_tags.append(f"[{COLOR_PASS}]✓ {val}[/{COLOR_PASS}]")
            elif s_val >= 0.0:
                audit_tags.append(f"[{COLOR_WARN}]⚠ {val}[/{COLOR_WARN}]")
            else:
                audit_tags.append(f"[{COLOR_FAIL}]✗ {val}[/{COLOR_FAIL}]")

    if audit_tags:
        items.append(Text.from_markup("  [dim]Preflight:[/] " + "  ".join(audit_tags)))

    # Tool Arguments / Payloads with bounded margins and word-wrapping to prevent overflow
    if name == "bash":
        cmd = args.get("command", "")
        syntax = Syntax(
            cmd,
            "bash",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
            padding=(0, 2, 0, 2),
        )
        items.append(Padding(syntax, (0, 3, 0, 3)))
    elif name in ("edit", "write"):
        path = args.get("path", "")
        if name == "edit":
            target = args.get("target", "")
            replacement = args.get("replacement", "")

            import difflib
            diff_lines = list(diff_lib := difflib.unified_diff(
                target.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            ))
            diff_text = "".join(diff_lines)
            items.append(Text.from_markup(f"  [dim]File:[/] [bold white]{path}[/]"))
            syntax = Syntax(
                diff_text if diff_text else replacement,
                "diff",
                theme="monokai",
                word_wrap=True,
                padding=(0, 2, 0, 2),
            )
            items.append(Padding(syntax, (0, 3, 0, 3)))
        else:
            code = args.get("content", "")
            preview = code[:400] + ("\n... [truncated]" if len(code) > 400 else "")
            lexer = _detect_lexer(path)
            items.append(Text.from_markup(f"  [dim]File:[/] [bold white]{path}[/]"))
            syntax = Syntax(
                preview,
                lexer,
                theme="monokai",
                word_wrap=True,
                padding=(0, 2, 0, 2),
            )
            items.append(Padding(syntax, (0, 3, 0, 3)))
    else:
        # Generic arguments with margin
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
        items.append(Padding(Text(f"Arguments: {args_str}", style="dim cyan"), (0, 3, 0, 2)))

    console.print(Group(*items))


def prompt_user_permission(name: str, args: Dict[str, Any], auto_approve: bool = True) -> bool:
    """Prompt the developer before running mutating tools (bash, write, edit)."""
    if auto_approve or name in ("read", "grep", "glob", "list"):
        return True

    console.print(f"\n[bold black on {COLOR_WARN}] ⚠️  ACTION CONFIRMATION [/] [bold white]Allow executing tool [cyan]{name}[/]? [Y/n]:[/] ", end="")
    try:
        choice = input().strip().lower()
        return choice in ("", "y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[{COLOR_WARN}]Action cancelled by user.[/]")
        return False


def print_tool_result_summary(name: str, result: str):
    """Print a clean execution indicator for completed tool calls."""
    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(no output)"
    if len(first_line) > 100:
        first_line = first_line[:100] + "..."
    line_count = len(preview)

    is_error = "exit code" in result.lower() and "exit code 0" not in result.lower() or "error" in first_line.lower()
    icon = "✖" if is_error else "✔"
    icon_style = COLOR_FAIL if is_error else COLOR_PASS
    action_text = "Failed" if is_error else "Executed"

    console.print(
        f"  [bold {icon_style}]↳ {icon}[/] [dim]{action_text} [bold white]{name}[/]: {first_line} ({line_count} line{'s' if line_count != 1 else ''})[/dim]"
    )


def print_subagent_start(role: str, description: str):
    """Print the launch indicator for a delegated subagent task."""
    console.print(
        f"  [bold #38bdf8]↳ [Subagent: {role}][/] [dim]Delegated: [bold white]\"{description}\"[/dim]"
    )


def print_subagent_step(role: str, tool_name: str, args: Dict[str, Any], result: str):
    """Print an inline progress step executed by a child subagent."""
    args_summary = ""
    if tool_name == "read":
        args_summary = args.get("path") or ""
    elif tool_name == "grep":
        args_summary = f"'{args.get('pattern', '')}' in {args.get('path', '.')}"
    elif tool_name == "glob":
        args_summary = f"'{args.get('pattern', '')}'"
    elif tool_name == "bash":
        args_summary = (args.get("command") or "")[:40]
    else:
        args_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])

    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(done)"
    if len(first_line) > 70:
        first_line = first_line[:70] + "..."

    console.print(
        f"    [dim #38bdf8]↳[/dim #38bdf8] [dim]({role})[/dim] [bold white]{tool_name}[/]({args_summary}) -> [dim]{first_line}[/dim]"
    )


def print_subagent_done(role: str, summary: str, steps: int = 1):
    """Print the completion verdict for a subagent."""
    preview = summary.strip().splitlines()
    first_line = preview[0] if preview else "(synthesis complete)"
    if len(first_line) > 90:
        first_line = first_line[:90] + "..."
    console.print(
        f"  [bold {COLOR_PASS}]↳ ✓ [Subagent: {role}][/] [dim]Completed in {steps} step{'s' if steps != 1 else ''}: {first_line}[/dim]"
    )


def print_final_output(text: str, res: Dict[str, Any]):
    """Render the final governed markdown response with side-by-side or stacked scorecard."""
    _record_turn_telemetry(res)
    left_renderable = Panel(
        Markdown(text),
        title=f"[bold {COLOR_BRAND_400}]● SAFi Governed Response[/]",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
        padding=(1, 2),
    )
    right_panel = _build_scoreboard_panel(res)

    console.print()
    if right_panel and (not isinstance(right_panel, Text) or right_panel.plain.strip()):
        # Responsive: use side-by-side grid if terminal width is wide enough
        terminal_width = console.width
        if terminal_width >= 110:
            grid = Table.grid(expand=True, padding=(0, 1))
            grid.add_column("left", ratio=3)
            grid.add_column("right", ratio=1)
            grid.add_row(left_renderable, right_panel)
            console.print(grid)
        else:
            console.print(left_renderable)
            console.print(right_panel)
    else:
        console.print(left_renderable)


def print_audit_details(result: Dict[str, Any]):
    """Detailed drill-down of all policy rubrics, scores, confidence, and rationales."""
    ledger = result.get("conscienceLedger") or []
    if not ledger:
        console.print(f"[{COLOR_WARN}]No conscience audit ledger available for this turn.[/]")
        return

    policy_title = result.get("policyName") or result.get("policyId") or "Domain Policy"
    table = Table(title=f"Detailed Governance Audit: {policy_title}", box=box.ROUNDED, border_style=COLOR_BRAND_600)
    table.add_column("Rubric / Value", style="bold white")
    table.add_column("Score", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Rationale", style="dim")

    for entry in ledger:
        val = entry.get("value") or "Standard"
        score = entry.get("score")
        rationale = entry.get("rationale") or entry.get("reason") or "—"
        if score is None:
            continue
        s_val = float(score)
        if s_val >= 0.7:
            status = f"[bold {COLOR_PASS}]PASS[/]"
            score_text = Text(f"+{s_val:.2f}", style=f"bold {COLOR_PASS}")
        elif s_val >= 0.0:
            status = f"[bold {COLOR_WARN}]CAUTION[/]"
            score_text = Text(f"+{s_val:.2f}", style=f"bold {COLOR_WARN}")
        else:
            status = f"[bold {COLOR_FAIL}]VIOLATION[/]"
            score_text = Text(f"{s_val:.2f}", style=f"bold {COLOR_FAIL}")

        table.add_row(val, score_text, status, rationale)

    console.print(table)


def print_error(message: str):
    """Render an error message panel."""
    console.print(Panel(f"[bold {COLOR_FAIL}]Error:[/] {message}", border_style=COLOR_FAIL, box=box.ROUNDED))


def print_compression_result(data: Dict[str, Any]):
    """Render a clean summary panel for context compression and token savings."""
    if not data.get("ok"):
        error_msg = data.get("error", "Unknown error during compression.")
        console.print(Panel(f"[bold {COLOR_FAIL}]Compression Error:[/] {error_msg}", border_style=COLOR_FAIL, box=box.ROUNDED))
        return

    if not data.get("compressed"):
        msg = data.get("message", "Conversation is already minimal (no compression needed).")
        console.print(f"[dim]ℹ️  {msg}[/dim]")
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

    # Print updated Faculty Telemetry immediately so the developer sees the reduction in session tokens
    console.print(build_telemetry_panel())
