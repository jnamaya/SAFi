"""Terminal UI formatting and rich display for the SAFi CLI."""

import json
from typing import Any, Dict, List, Optional
from rich.console import Console
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


def print_tool_proposal(name: str, args: Dict[str, Any], will_decision: str, will_reason: Optional[str] = None):
    is_approved = will_decision in ("approve", "approved")
    decision_style = "bold green" if is_approved else "bold red"
    icon = "" if is_approved else "⛔ "

    title = f"Will Gate: [{decision_style}]{will_decision.upper()}[/] -> Tool '{name}'" if is_approved else f"⛔ Will Gate: [{decision_style}]{will_decision.upper()}[/] -> Tool '{name}'"
    if will_reason:
        title += f" ({will_reason})"

    # Format arguments
    content = Text()
    if name == "bash":
        cmd = args.get("command", "")
        console.print(Panel(Syntax(cmd, "bash", theme="monokai", line_numbers=False), title=title, border_style="cyan"))
        return
    elif name in ("edit", "write"):
        path = args.get("path", "")
        content.append(f"File: {path}\n", style="bold")
        if name == "edit":
            content.append("Target to replace:\n", style="red")
            content.append(f"{args.get('target', '')}\n", style="dim")
            content.append("Replacement:\n", style="green")
            content.append(f"{args.get('replacement', '')}", style="green")
        else:
            code = args.get("content", "")
            preview = code[:500] + ("\n... [truncated]" if len(code) > 500 else "")
            content.append(preview)
        console.print(Panel(content, title=title, border_style="cyan"))
        return

    # Default tool display
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    if is_approved:
        console.print(f"[bold green]Will Gate:[/] [bold cyan]{name}[/]({args_str})")
    else:
        console.print(f"[bold red]⛔ Will Gate [{will_decision}]:[/] [bold cyan]{name}[/]({args_str})")



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
    console.print(f"  [dim green]✓ Executed {name}: {first_line} ({line_count} lines)[/dim green]")


def print_final_output(text: str):
    console.print()
    console.print(Panel(Markdown(text), title="[bold green]Governed Response[/]", border_style="green"))


def print_governance_scorecard(result: Dict[str, Any]):
    """Render Conscience rubric scores, Spirit EMA drift, and Will gate decisions."""
    ledger = result.get("conscienceLedger") or []
    will_decision = result.get("willDecision", "unknown")
    will_reason = result.get("willReason")
    spirit_score = result.get("spirit_score")
    if spirit_score is None:
        spirit_score = result.get("spiritScore")
    spirit_note = result.get("spiritNote") or ""

    table = Table(title="SAFi Governance Compliance Scorecard", border_style="dim")
    table.add_column("Standard / Rubric", style="bold")
    table.add_column("Verdict", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Assessment", style="dim")

    for entry in ledger:
        val = entry.get("value") or "Standard"
        score = entry.get("score")
        reason = entry.get("reason") or entry.get("descriptor") or ""

        if score is not None:
            score_val = float(score)
            if score_val >= 0.7:
                verdict = "[green]✓ PASS[/green]"
                score_str = f"[green]{score_val:+.2f}[/green]"
            elif score_val >= 0.0:
                verdict = "[yellow]⚠ WARN[/yellow]"
                score_str = f"[yellow]{score_val:+.2f}[/yellow]"
            else:
                verdict = "[red]✗ FAIL[/red]"
                score_str = f"[red]{score_val:+.2f}[/red]"
        else:
            verdict = "[dim]AUDIT[/dim]"
            score_str = "-"

        table.add_row(val, verdict, score_str, reason[:80] + ("..." if len(reason) > 80 else ""))

    console.print(table)

    summary = Text()
    summary.append("Will Gate Decision: ", style="bold")
    decision_color = "green" if will_decision in ("approve", "approved") else "red"
    summary.append(f"{will_decision.upper()} ", style=f"bold {decision_color}")
    if will_reason:
        summary.append(f"({will_reason}) ", style="dim")

    if spirit_score is not None:
        summary.append(" | Spirit EMA Score: ", style="bold")
        summary.append(f"{float(spirit_score):.3f}", style="cyan")

    if spirit_note:
        summary.append(f"\nSpirit: {spirit_note}", style="italic dim")

    console.print(Panel(summary, border_style="blue", expand=False))


def print_error(message: str):
    console.print(Panel(f"[bold red]Error:[/] {message}", border_style="red"))
