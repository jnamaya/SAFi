"""safi-cli entrypoint (thin): argument parsing, client bootstrap, dispatch."""

import argparse
import glob
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, prompt_input, ssh_keys, tools, ui
from .client import SafiClient, SafiClientError

# Backwards-compatible re-exports (tests and callers import via safi_cli.main)
from .subagents import (
    MAX_SUBAGENTS_PER_TURN,
    _execute_tool_with_live_status,
    run_subagent_task,
)
from .turn_loop import DEFAULT_MAX_STEPS, run_agent_turn, get_last_turn_result
from .agent_registry import (
    AVAILABLE_AGENTS,
    DEFAULT_AGENTS,
    _infer_provider,
    discover_agents,
    discover_models,
    discover_serving_model,
    is_serving_alias,
    prompt_switch_agent,
    prompt_switch_model,
    resolve_model_preference,
    serving_model_id,
)
from .repl import (
    _archive_scratchpad,
    _collect_multiline,
    _compute_completions,
    interactive_repl,
    print_help,
    prompt_command_menu,
    prompt_resume_session,
    run_setup_wizard,
    setup_readline_completer,
    show_config,
)

logger = logging.getLogger("safi.main")


def main():
    # Direct command shortcuts: safi setup-key [target], safi push-key [target], safi ssh-key [target]
    if len(sys.argv) > 1 and sys.argv[1] in ("setup-key", "push-key", "ssh-key"):
        code = ssh_keys.run_setup_key(sys.argv[2:]) if len(sys.argv) > 2 else (ssh_keys.interactive_setup_key() or 0)
        sys.exit(code if isinstance(code, int) else 0)

    # Standalone keygen shortcut: safi keygen (local Ed25519 key, no deployment)
    if len(sys.argv) > 1 and sys.argv[1] in ("keygen", "gen-key"):
        sys.exit(ssh_keys.keygen_local())

    parser = argparse.ArgumentParser(
        prog="safi",
        description="SAFi (The Self-alignment Framework Interface) — The governance engine for AI agents.",
    )
    parser.add_argument("--setup", "--init", dest="setup_wizard", action="store_true", help="Launch the interactive first-run setup wizard.")
    parser.add_argument("prompt", nargs="?", help="Task prompt. If omitted, starts interactive REPL mode.")
    parser.add_argument("-k", "--api-key", help="SAFi Policy API Key (defaults to SAFI_API_KEY env or config).")
    parser.add_argument("-u", "--api-url", help="SAFi backend URL (one-off override; default is the URL saved via `safi --set-url`).")
    parser.add_argument("-a", "--agent", default=None, help="Agent (default: last used in workspace, or software_engineer).")
    parser.add_argument(
        "-m",
        "--model",
        help="AI model powering the agent (e.g. claude-3-5-sonnet, gpt-4o, gemini-2.5-flash). Pass 'local' to always follow the model the appliance is serving.",
    )

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
        default=False,
        help="Auto-approve tool execution without prompting (approval is required by default).",
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
    parser.add_argument(
        "--set-model",
        help="Save default AI model to ~/.config/safi/config.json and exit. Pass 'local' to always follow the model the appliance is serving.",
    )
    parser.add_argument("--user-name", help="Display name of the user for the agent to address.")
    parser.add_argument("--set-user", help="Save the default user display name to ~/.config/safi/config.json and exit.")
    parser.add_argument(
        "--setup-key",
        "--push-key",
        dest="setup_key",
        nargs="*",
        help="Deploy local SSH public key to Linux or Windows inventory host or user@host.",
    )

    args = parser.parse_args()

    if args.setup_key is not None:
        if args.setup_key:
            code = ssh_keys.run_setup_key(args.setup_key)
        else:
            ssh_keys.interactive_setup_key()
            code = 0
        sys.exit(code if isinstance(code, int) else 0)

    if args.set_user:
        config.save_user_name(args.set_user.strip())
        ui.console.print(f"[bold green]✓ Saved user name '{args.set_user.strip()}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_model:
        target_save_agent = args.agent if args.agent and args.agent != "software_engineer" else None
        config.save_intellect_model(args.set_model.strip(), target_save_agent)
        agent_note = f" for '{args.agent}'" if target_save_agent else " globally"
        ui.console.print(
            f"[bold green]✓ Saved default AI model '{args.set_model.strip()}'{agent_note} to {config.CONFIG_FILE}[/]"
        )
        sys.exit(0)

    if args.set_key:
        target_key_agent = args.agent or "software_engineer"
        config.save_agent_api_key(target_key_agent, args.set_key.strip())
        ui.console.print(f"[bold green]✓ Saved Policy API key for '{target_key_agent}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_url:
        new_url = args.set_url.strip().rstrip("/")
        config.save_config({"api_url": new_url})
        ui.console.print(f"[bold green]✓ Saved API URL to {config.CONFIG_FILE}[/]")
        test_client = SafiClient(new_url)
        discovered = discover_agents(test_client)
        ui.console.print(f"[dim]Backend {new_url}: discovered {len(discovered)} available agent(s).[/dim]")
        sys.exit(0)

    # Run setup wizard if requested via --setup or on first run in an interactive terminal
    is_first_run = (not config.has_configured_api_url() and not args.api_url)
    if args.setup_wizard or (is_first_run and sys.stdin.isatty()):
        wizard_url, wizard_agent, wizard_key = run_setup_wizard()
        if not args.api_url:
            args.api_url = wizard_url
        if not args.agent:
            args.agent = wizard_agent
        if not args.api_key and wizard_key:
            args.api_key = wizard_key

    workspace_root = Path(args.workspace).resolve()
    target_agent = args.agent or config.get_workspace_agent(str(workspace_root)) or config.get_default_agent() or "software_engineer"

    api_url = config.resolve_api_url(args.api_url)
    api_key = config.resolve_agent_api_key(target_agent, args.api_key)
    user_name = config.resolve_user_name(args.user_name)

    client = SafiClient(api_url, api_key or "")
    discover_agents(client)

    if not api_key:
        agent_title = AVAILABLE_AGENTS.get(target_agent, {}).get("title", target_agent)
        ui.console.print(
            f"[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]\n"
            f"[dim]Each agent is governed by its own domain policy and requires its own Policy API Key.[/dim]"
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
        client.api_key = api_key
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")
        discover_agents(client)

    intellect_model = resolve_model_preference(client, target_agent, args.model)

    conv_id = config.resolve_session_id(str(workspace_root), new_session=args.new, agent=target_agent)
    config.set_workspace_agent(str(workspace_root), target_agent, conv_id)
    user_id = config.resolve_user_id()
    if args.new:
        try:
            client.clear_agent_memory(conv_id, user_id=user_id, agent=target_agent)
        except Exception as exc:
            logger.warning("Could not clear agent memory for new session: %s", exc)
        _archive_scratchpad(workspace_root)
    auto_approve = not args.require_approval or args.auto_approve

    if args.prompt:
        ui.print_banner(str(workspace_root), target_agent, api_url, user_name=user_name, intellect_model=intellect_model)
        run_agent_turn(
            client=client,
            prompt=args.prompt,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=target_agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )
    else:
        interactive_repl(
            client=client,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=target_agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )


if __name__ == "__main__":
    main()
