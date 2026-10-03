import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None

from . import config, tools, ui
from .client import SafiClient, SafiClientError


DEFAULT_MAX_STEPS = 25


def run_agent_turn(
    client: SafiClient,
    prompt: str,
    workspace_root: Path,
    conversation_id: str,
    user_id: str,
    agent: str,
    auto_approve: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
):
    """Run an agentic loop until SAFi produces a final governed response."""
    tool_results = []
    recent_turns = ""

    try:
        for step in range(max_steps):
            try:
                with ui.console.status("[bold cyan]Thinking...[/]"):
                    res = client.send_turn(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message=prompt,
                        workspace_root=str(workspace_root.resolve()),
                        agent=agent,
                        tool_results=tool_results,
                        recent_turns=recent_turns,
                    )
            except SafiClientError as err:
                ui.print_error(str(err))
                return None

            # Handle tool call proposal
            if res.get("type") == "tool_call":
                tool_name = res.get("tool_name", "")
                args = res.get("parameters") or {}
                will_decision = res.get("willDecision", "approved")
                will_reason = res.get("willReason")

                ui.print_tool_proposal(tool_name, args, res)

                # If WillGate blocked the proposal, SAFi does not expect client execution
                if will_decision not in ("approve", "approved"):
                    tool_results.append({
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": f"The Will Gatekeeper rejected '{tool_name}' ({will_reason}).",
                    })
                    continue

                # Permission check for mutating/shell tools
                allowed = ui.prompt_user_permission(tool_name, args, auto_approve=auto_approve)
                if not allowed:
                    result_str = f"Execution of '{tool_name}' was declined by the developer."
                else:
                    result_str = tools.execute_tool(tool_name, args, workspace_root)
                    ui.print_tool_result_summary(tool_name, result_str)

                tool_results.append({
                    "tool_name": tool_name,
                    "arguments": args,
                    "result": result_str,
                })
                continue

            # Terminal answer reached
            final_text = res.get("finalOutput") or ""
            ui.print_final_output(final_text, res)
            return res

        ui.print_error(f"Reached maximum tool loop iterations ({max_steps}).")
        return None
    except KeyboardInterrupt:
        ui.console.print("\n[bold yellow]Turn cancelled (Ctrl+C).[/bold yellow]")
        return None


AVAILABLE_AGENTS = {
    "coding_harness": {
        "title": "Coding Assistant",
        "description": "Direct, audited repository engineering & software development",
    },
    "fiduciary": {
        "title": "The Fiduciary",
        "description": "Market-aware financial analyst, portfolio educator & data-driven guide",
    },
    "health_navigator": {
        "title": "Health Navigator",
        "description": "Evidence-based health literature, clinical navigation & wellness guide",
    },
    "socratic_tutor": {
        "title": "Socratic Tutor",
        "description": "Pedagogical inquiry, conceptual reasoning & critical thinking coach",
    },
    "bible_scholar": {
        "title": "Bible Scholar",
        "description": "Scriptural hermeneutics, historical-grammatical exegesis & theology",
    },
    "safi_steward": {
        "title": "SAFi Steward",
        "description": "Platform administration, policy governance & compliance stewardship",
    },
}


def prompt_switch_agent(
    current_agent: str,
    client: SafiClient,
    workspace_root: Path,
    requested_agent: Optional[str] = None,
) -> tuple[str, str]:
    """Interactively select or switch to an agent persona, prompting for its Policy API key if not yet configured."""
    from rich.table import Table
    from rich import box

    agent_keys = list(AVAILABLE_AGENTS.keys())
    target_agent = None

    if requested_agent:
        req = requested_agent.strip().lower()
        if req in AVAILABLE_AGENTS:
            target_agent = req
        else:
            if req.isdigit() and 1 <= int(req) <= len(agent_keys):
                target_agent = agent_keys[int(req) - 1]
            else:
                for k, v in AVAILABLE_AGENTS.items():
                    if req in v["title"].lower() or req in k:
                        target_agent = k
                        break
        if not target_agent:
            ui.console.print(f"[bold red]Unknown agent persona:[/] [yellow]'{requested_agent}'[/]. Use [bold]/[/] to see available options.")
            return current_agent, config.resolve_session_id(str(workspace_root))

    if not target_agent:
        table = Table(title="Available SAFi Agent Personas", box=box.ROUNDED)
        table.add_column("#", style="bold yellow", width=3, justify="right")
        table.add_column("Agent Key", style="cyan bold")
        table.add_column("Title", style="green")
        table.add_column("Policy API Key", style="magenta")
        table.add_column("Description", style="dim")

        for idx, (k, v) in enumerate(AVAILABLE_AGENTS.items(), 1):
            active_marker = " [bold yellow](active)[/]" if k == current_agent else ""
            key_val = config.resolve_agent_api_key(k)
            key_status = "[green]✓ Configured[/green]" if key_val else "[yellow]⚠️  Key Needed[/yellow]"
            table.add_row(str(idx), f"{k}{active_marker}", v["title"], key_status, v["description"])

        ui.console.print(table)
        try:
            choice = input("\nSelect an agent [# or name] (or press Enter to cancel): ").strip()
        except (KeyboardInterrupt, EOFError):
            return current_agent, config.resolve_session_id(str(workspace_root))

        if not choice:
            return current_agent, config.resolve_session_id(str(workspace_root))

        choice_lower = choice.lower()
        if choice.isdigit() and 1 <= int(choice) <= len(agent_keys):
            target_agent = agent_keys[int(choice) - 1]
        elif choice_lower in AVAILABLE_AGENTS:
            target_agent = choice_lower
        else:
            for k, v in AVAILABLE_AGENTS.items():
                if choice_lower in v["title"].lower() or choice_lower in k:
                    target_agent = k
                    break

        if not target_agent:
            ui.console.print(f"[bold red]Invalid selection:[/] '{choice}'.")
            return current_agent, config.resolve_session_id(str(workspace_root))

    # Check Policy API key for target_agent
    agent_info = AVAILABLE_AGENTS.get(target_agent, {})
    agent_title = agent_info.get("title", target_agent)
    agent_key_val = config.resolve_agent_api_key(target_agent)

    if not agent_key_val:
        ui.console.print(f"\n[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]")
        ui.console.print("[dim]Each agent is governed by a separate domain policy and requires its own Policy API Key.[/dim]")
        try:
            entered_key = input(f"Enter Policy API Key for {target_agent} (from SAFi Governance Portal): ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("[dim]Switch cancelled.[/dim]")
            return current_agent, config.resolve_session_id(str(workspace_root))

        if not entered_key:
            ui.console.print(f"[dim]Agent switch cancelled: no API key provided for {target_agent}.[/dim]")
            return current_agent, config.resolve_session_id(str(workspace_root))

        config.save_agent_api_key(target_agent, entered_key)
        agent_key_val = entered_key
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")

    client.api_key = agent_key_val
    new_conv = config.resolve_session_id(str(workspace_root), new_session=True)
    ui.console.print(f"[bold green]✓ Switched active agent to:[/] [bold cyan]{target_agent}[/] ([green]{agent_title}[/])")
    ui.console.print(f"[dim]Started fresh session:[/] [cyan]{new_conv}[/]")
    return target_agent, new_conv


def interactive_repl(
    client: SafiClient,
    workspace_root: Path,
    conversation_id: str,
    user_id: str,
    agent: str,
    auto_approve: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
):
    """Start an interactive command-line session."""
    current_agent = agent
    ui.print_banner(str(workspace_root), current_agent, client.api_url)
    ui.console.print(
        "[dim]Type your prompt, or 'exit' to quit. Type '/' to switch agent personas, '/new' for a fresh session, or '/help'.[/dim]\n"
    )

    # Setup readline history
    config.ensure_config_dir()
    hist_file = str(config.HISTORY_FILE)
    if readline and os.path.exists(hist_file):
        try:
            readline.read_history_file(hist_file)
        except OSError:
            pass

    current_conv = conversation_id
    try:
        while True:
            try:
                line = input(f"\n[SAFi:{current_agent}]> ").strip()
            except (KeyboardInterrupt, EOFError):
                ui.console.print("\n[dim]Session terminated.[/dim]")
                break

            if not line:
                continue
            if line.lower() in ("exit", "quit", ":q"):
                ui.console.print("[dim]Goodbye.[/dim]")
                break
            if line.lower() == "/new":
                current_conv = config.resolve_session_id(str(workspace_root), new_session=True)
                ui.console.print(f"[bold green]Started new conversation session:[/] [cyan]{current_conv}[/]")
                continue

            if line == "/" or line.lower() in ("/agents", "/list-agents"):
                current_agent, current_conv = prompt_switch_agent(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                )
                continue

            if line.lower().startswith(("/agent", "/switch")):
                parts = line.split(maxsplit=1)
                req = parts[1].strip() if len(parts) > 1 else None
                current_agent, current_conv = prompt_switch_agent(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                    requested_agent=req,
                )
                continue

            if line.lower() in ("/help", "/?"):
                ui.console.print("""[bold]Available Slash Commands:[/]
  [cyan]/[/]                 Interactive agent persona selector & switcher
  [cyan]/agents[/]           List available agent personas and API key status
  [cyan]/agent <name>[/]     Switch directly to an agent persona (e.g. [bold]/agent fiduciary[/])
  [cyan]/new[/]              Start a fresh conversation session
  [cyan]/help[/]             Show this help menu
  [cyan]exit, quit, :q[/]    Exit SAFi CLI
""")
                continue

            run_agent_turn(
                client=client,
                prompt=line,
                workspace_root=workspace_root,
                conversation_id=current_conv,
                user_id=user_id,
                agent=current_agent,
                auto_approve=auto_approve,
                max_steps=max_steps,
            )

    finally:
        if readline:
            try:
                readline.write_history_file(hist_file)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        prog="safi",
        description="SAFi Governed Coding Assistant — Direct, audited repository engineering.",
    )
    parser.add_argument("prompt", nargs="?", help="Task prompt. If omitted, starts interactive REPL mode.")
    parser.add_argument("-k", "--api-key", help="SAFi Policy API Key (defaults to SAFI_API_KEY env or config).")
    parser.add_argument("-u", "--api-url", help="SAFi backend URL (default: http://localhost:5000).")
    parser.add_argument("-a", "--agent", default="coding_harness", help="Agent persona (default: coding_harness).")
    parser.add_argument("-w", "--workspace", default=".", help="Workspace path (default: current directory).")
    parser.add_argument(
        "--confirm",
        "--require-approval",
        dest="require_approval",
        action="store_true",
        help="Prompt for developer confirmation before executing tools (default is auto-approve governed tools).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        dest="auto_approve",
        action="store_true",
        default=True,
        help="Auto-approve tool execution without prompting (enabled by default).",
    )
    parser.add_argument("-n", "--new", action="store_true", help="Start a new conversation session.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"Maximum tool loop iterations per turn (default: {DEFAULT_MAX_STEPS}).",
    )
    parser.add_argument("--set-key", help="Save the given API key to ~/.config/safi/config.json and exit.")
    parser.add_argument("--set-url", help="Save the given backend URL to ~/.config/safi/config.json and exit.")

    args = parser.parse_args()

    # Save key / URL commands
    if args.set_key:
        config.save_agent_api_key(args.agent, args.set_key.strip())
        ui.console.print(f"[bold green]✓ Saved Policy API key for '{args.agent}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_url:
        config.save_config({"api_url": args.set_url.strip().rstrip("/")})
        ui.console.print(f"[bold green]✓ Saved API URL to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    # Resolve settings for the targeted agent
    target_agent = args.agent
    api_key = config.resolve_agent_api_key(target_agent, args.api_key)
    if not api_key:
        agent_title = AVAILABLE_AGENTS.get(target_agent, {}).get("title", target_agent)
        ui.console.print(
            f"[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]\n"
            f"[dim]Each agent persona is governed by its own domain policy and requires its own Policy API Key.[/dim]"
        )
        try:
            api_key = input(f"Enter Policy API Key for {target_agent} (from SAFi Governance Portal): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(1)
        if not api_key:
            ui.print_error(
                f"No SAFi Policy API key provided for '{target_agent}'.\n\n"
                "You can also set it via:\n"
                f"  • export SAFI_API_KEY_{target_agent.upper()}=sk-safi-...\n"
                f"  • safi --set-key sk-safi-... -a {target_agent}"
            )
            sys.exit(1)
        config.save_agent_api_key(target_agent, api_key)
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")


    api_url = config.resolve_api_url(args.api_url)
    workspace_root = Path(args.workspace).resolve()
    conv_id = config.resolve_session_id(str(workspace_root), new_session=args.new)
    user_id = f"cli_{os.getlogin() if hasattr(os, 'getlogin') else 'user'}"
    auto_approve = not args.require_approval

    client = SafiClient(api_url, api_key)

    if args.prompt:
        # Single-shot command
        ui.print_banner(str(workspace_root), args.agent, api_url)
        run_agent_turn(
            client=client,
            prompt=args.prompt,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=args.agent,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )
    else:
        # Interactive mode
        interactive_repl(
            client=client,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=args.agent,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )


if __name__ == "__main__":
    main()
