"""SAFi CLI main entrypoint — interactive & single-shot governed coding assistant."""

import argparse
import os
import readline
import sys
import uuid
from pathlib import Path
from typing import Optional

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
    ui.print_banner(str(workspace_root), agent, client.api_url)
    ui.console.print("[dim]Type your prompt, or 'exit'/'quit' to quit. Press Ctrl+C to cancel a running turn. Use '/new' for a fresh session.[/dim]\n")

    # Setup readline history
    config.ensure_config_dir()
    hist_file = str(config.HISTORY_FILE)
    if os.path.exists(hist_file):
        try:
            readline.read_history_file(hist_file)
        except OSError:
            pass

    current_conv = conversation_id
    try:
        while True:
            try:
                line = input("\n[SAFi]> ").strip()
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

            run_agent_turn(
                client=client,
                prompt=line,
                workspace_root=workspace_root,
                conversation_id=current_conv,
                user_id=user_id,
                agent=agent,
                auto_approve=auto_approve,
                max_steps=max_steps,
            )

    finally:
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
        config.save_config({"api_key": args.set_key.strip()})
        ui.console.print(f"[bold green]✓ Saved API key to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_url:
        config.save_config({"api_url": args.set_url.strip().rstrip("/")})
        ui.console.print(f"[bold green]✓ Saved API URL to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    # Resolve settings
    api_key = config.resolve_api_key(args.api_key)
    if not api_key:
        ui.print_error(
            "No SAFi API key found.\n\n"
            "Set it via:\n"
            "  • export SAFI_API_KEY=sk-safi-...\n"
            "  • safi --set-key sk-safi-...\n"
            "  • safi -k sk-safi-... 'your prompt'"
        )
        sys.exit(1)

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
