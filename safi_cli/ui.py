"""Terminal UI formatting and rich display for the SAFi CLI."""

import json
from typing import Any, Dict, List, Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

console = Console()


def print_banner(workspace_root: str, agent: str, api_url: str):
    banner_text = Text()
    banner_text.append("SAFi Governed Coding Assistant\n", style="bold green")
    banner_text.append("Agent: ", style="bold")
    banner_text.append(f"{agent}  ", style="cyan")
    banner_text.append("Endpoint: ", style="bold")
    banner_text.append(f"{api_url}\n", style="cyan")
    banner_text.append("Workspace: ", style="bold")
    banner_text.append(f"{workspace_root}", style="yellow")
    console.print(Panel(banner_text, border_style="green", expand=False))


from rich import box

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

_session_intellect = {"in": 0, "out": 0, "cost": 0.0}
_session_conscience = {"in": 0, "out": 0, "cost": 0.0}

def _record_turn_telemetry(result: Dict[str, Any]):
    """Accumulate session token and cost counters across turns for each faculty."""
    global _session_intellect, _session_conscience
    models_usage = result.get("models_usage")
    if models_usage and isinstance(models_usage, dict):
        # Intellect
        intellect_data = models_usage.get("intellect") or {}
        in_t = int(intellect_data.get("prompt_tokens") or 0)
        out_t = int(intellect_data.get("completion_tokens") or 0)
        _session_intellect["in"] += in_t
        _session_intellect["out"] += out_t
        model_name = intellect_data.get("model") or ""
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
            if ai_prov and isinstance(ai_prov, dict) and ai_prov.get("model"):
                cost = _estimate_cost(ai_prov.get("model"), in_t, out_t)
                if cost is not None:
                    _session_intellect["cost"] += cost


def _build_scoreboard_panel(result: Dict[str, Any]) -> Any:
    """Build the Governance Scorecard panel to be displayed on the right."""
    ledger = result.get("conscienceLedger") or []
    spirit_score = result.get("spirit_score") or result.get("spiritScore")

    panels = []

    # Alignment Score
    if spirit_score is not None:
        val = float(spirit_score)
        _spirit_history.append(val)
        spark = _get_sparkline(_spirit_history, width=8)
        spirit_text = Text(f"📈 {val:.3f}  {spark}", style="cyan", justify="center")
        panels.append(Panel(spirit_text, title="[bold]ALIGNMENT SCORE", border_style="blue"))

    # Conscience Table
    table = Table(expand=True, show_header=False, box=None)
    table.add_column("Metric")
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
            table.add_row(f"✅ {val}", Text(f"+{score_val:.2f}", style="green"))
        elif score_val >= 0.0:
            table.add_row(f"⚠️ {val}", Text(f"+{score_val:.2f}", style="yellow"))
        else:
            table.add_row(f"🛑 {val}", Text(f"{score_val:.2f}", style="red"))

    if has_scores:
        panels.append(Panel(table, title="[bold]POLICY AUDIT", border_style="dim"))

    # Models Stats Breakdown
    models_usage = result.get("models_usage") or {}
    stats_content = []

    # 1. Intellect Section
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
    cost = _estimate_cost(intellect_model, in_t, out_t)
    cost_str = f" (${cost:.4f})" if cost and cost >= 0.0001 else (" (<$0.0001)" if cost and cost > 0 else "")
    sess_cost = _session_intellect["cost"]
    sess_cost_str = f" (${sess_cost:.4f})" if sess_cost >= 0.0001 else (" (<$0.0001)" if sess_cost > 0 else "")

    stats_content.append(Text(f"Intellect: {intellect_model}", style="bold cyan"))
    if in_t or out_t or _session_intellect["in"]:
        stats_content.append(Text(f"  Turn: {in_t:,} in | {out_t:,} out{cost_str}", style="dim"))
        stats_content.append(Text(f"  Session: {_session_intellect['in']:,} in | {_session_intellect['out']:,} out{sess_cost_str}", style="dim"))
    else:
        stats_content.append(Text("  Turn: - | Session: -", style="dim"))

    # 2. Conscience Section
    conscience_data = models_usage.get("conscience") or {}
    conscience_model = (
        conscience_data.get("model")
        or result.get("conscienceModel")
        or "systemone (Jev)"
    )
    c_in = int(conscience_data.get("prompt_tokens") or 0)
    c_out = int(conscience_data.get("completion_tokens") or 0)
    c_cost = _estimate_cost(conscience_model, c_in, c_out)
    c_cost_str = f" (${c_cost:.4f})" if c_cost and c_cost >= 0.0001 else (" (<$0.0001)" if c_cost and c_cost > 0 else "")
    c_sess_cost = _session_conscience["cost"]
    c_sess_cost_str = f" (${c_sess_cost:.4f})" if c_sess_cost >= 0.0001 else (" (<$0.0001)" if c_sess_cost > 0 else "")

    stats_content.append(Text(f"Conscience: {conscience_model}", style="bold magenta"))
    if c_in or c_out or _session_conscience["in"]:
        stats_content.append(Text(f"  Turn: {c_in:,} in | {c_out:,} out{c_cost_str}", style="dim"))
        stats_content.append(Text(f"  Session: {_session_conscience['in']:,} in | {_session_conscience['out']:,} out{c_sess_cost_str}", style="dim"))
    else:
        stats_content.append(Text("  Audit: Jev / TypeSafe (deterministic)", style="dim italic"))

    if stats_content and has_scores:
        panels.append(Panel(Group(*stats_content), title="[bold]MODELS STATS", border_style="dim"))

    if not panels:
        return Text("")

    return Panel(Group(*panels), title="[bold]Compliance Audit", border_style="magenta")


def print_tool_proposal(name: str, args: Dict[str, Any], res: Dict[str, Any]):
    _record_turn_telemetry(res)
    will_decision = res.get("willDecision", "approved")
    will_reason = res.get("willReason")
    is_approved = will_decision in ("approve", "approved")
    decision_style = "bold green" if is_approved else "bold red"
    icon = "" if is_approved else "⛔ "

    title_text = Text(f"{icon}[{will_decision.upper()}] -> {name}", style=decision_style)
    if will_reason:
        title_text.append(f"  # {will_reason}", style="dim")

    items = [title_text]

    # Inline Policy Preflight Audit: Display rubric badges directly on the thinking stream
    ledger = res.get("toolProposalLedger") or res.get("conscienceLedger") or []
    audit_tags = []
    for entry in ledger:
        score = entry.get("score")
        if score is not None:
            val = entry.get("value", "")
            s_val = float(score)
            if s_val >= 0.7:
                audit_tags.append(f"[green]✓ {val}[/green]")
            elif s_val >= 0.0:
                audit_tags.append(f"[yellow]⚠ {val}[/yellow]")
            else:
                audit_tags.append(f"[red]✗ {val}[/red]")

    if audit_tags:
        items.append(Text.from_markup(f"  [dim]Policy Check:[/] " + "  ".join(audit_tags)))

    if name == "bash":
        cmd = args.get("command", "")
        items.append(Syntax(cmd, "bash", theme="monokai", line_numbers=False, padding=(0, 0, 0, 2)))
    elif name in ("edit", "write"):
        path = args.get("path", "")
        if name == "edit":
            target = args.get('target', '')
            replacement = args.get('replacement', '')

            import difflib
            diff_lines = list(difflib.unified_diff(
                target.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3
            ))
            diff_text = "".join(diff_lines)
            items.append(Text(f"  File: {path}", style="bold"))
            items.append(Syntax(diff_text if diff_text else replacement, "diff", theme="monokai", padding=(0, 0, 0, 2)))
        else:
            code = args.get("content", "")
            preview = code[:300] + ("\n... [truncated]" if len(code) > 300 else "")
            items.append(Text(f"  File: {path}", style="bold"))
            items.append(Syntax(preview, "python", theme="monokai", padding=(0, 0, 0, 2)))
    else:
        # Default tool display
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
        items.append(Text(f"  Arguments: {args_str}", style="cyan"))

    console.print(Group(*items))


def prompt_user_permission(name: str, args: Dict[str, Any], auto_approve: bool = True) -> bool:
    """Prompt the developer before running mutating tools (bash, write, edit)."""
    if auto_approve or name in ("read", "grep", "glob", "list"):
        return True

    console.print(f"[bold yellow]⚠️  Permission required to execute '{name}'[/]")
    try:
        choice = input("Allow this action? [Y/n]: ").strip().lower()
        return choice in ("", "y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Action cancelled by user.[/]")
        return False


def print_tool_result_summary(name: str, result: str):
    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(no output)"
    if len(first_line) > 100:
        first_line = first_line[:100] + "..."
    line_count = len(preview)
    console.print(f"  [dim green]↳ ✓ Executed {name}: {first_line} ({line_count} lines)[/dim green]")


def print_final_output(text: str, res: Dict[str, Any]):
    _record_turn_telemetry(res)
    left_renderable = Panel(Markdown(text), title="[bold green]Governed Response[/]", border_style="green")
    right_panel = _build_scoreboard_panel(res)

    console.print()
    if right_panel and (not isinstance(right_panel, Text) or right_panel.plain.strip()):
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column("left", ratio=3)
        grid.add_column("right", ratio=1)
        grid.add_row(left_renderable, right_panel)
        console.print(grid)
    else:
        console.print(left_renderable)


def print_error(message: str):
    console.print(Panel(f"[bold red]Error:[/] {message}", border_style="red"))
