"""safi-cli entrypoint (thin): argument parsing, client bootstrap, dispatch."""

import argparse
import getpass
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

    # Cloud setup shortcut: safi setup-cloud, safi cloud
    if len(sys.argv) > 1 and sys.argv[1] in ("setup-cloud", "cloud", "cloud-setup"):
        from . import cloud
        cloud.interactive_setup_cloud()
        sys.exit(0)

    # Standalone keygen shortcut: safi keygen (local Ed25519 key, no deployment)
    if len(sys.argv) > 1 and sys.argv[1] in ("keygen", "gen-key"):
        sys.exit(ssh_keys.keygen_local())

    parser = argparse.ArgumentParser(
        prog="safi-cli",
        description="SAFi (The Self-alignment Framework Interface) — The governance engine for AI agents.",
    )
    parser.add_argument("--setup", "--init", dest="setup_wizard", action="store_true", help="Launch the interactive first-run setup wizard.")
    parser.add_argument("prompt", nargs="?", help="Task prompt. If omitted, starts interactive REPL mode.")
    parser.add_argument("-k", "--api-key", help="SAFi Policy API Key (defaults to SAFI_API_KEY env or config).")
    parser.add_argument("-u", "--api-url", help="SAFi backend URL (one-off override; default is the URL saved via `safi-cli --set-url`).")
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
    parser.add_argument(
        "--login",
        dest="login",
        action="store_true",
        help="Log in with your SAFi web username/password (local or LDAP) to obtain a Policy API key and save it for all available agents (default agent: software_engineer).",
    )
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
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Log out of SAFi, removing stored credentials, user identity, and cached API keys.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset SAFi CLI configuration and sessions to initial clean state.",
    )
    parser.add_argument(
        "--setup-cloud",
        "--cloud",
        dest="setup_cloud",
        action="store_true",
        help="Configure Microsoft 365 or Azure Cloud credentials and test connectivity.",
    )

    args = parser.parse_args()

    if getattr(args, "logout", False):
        config.clear_credentials()
        ui.console.print("[bold green]✓ Successfully logged out.[/] Stored credentials and API keys have been removed.")
        sys.exit(0)

    if getattr(args, "reset", False):
        config.clear_all_config()
        ui.console.print("[bold green]✓ SAFi CLI configuration and sessions have been reset to factory state.[/]")
        sys.exit(0)

    if args.setup_key is not None:
        if args.setup_key:
            code = ssh_keys.run_setup_key(args.setup_key)
        else:
            ssh_keys.interactive_setup_key()
            code = 0
        sys.exit(code if isinstance(code, int) else 0)

    if getattr(args, "setup_cloud", False):
        from . import cloud
        cloud.interactive_setup_cloud()
        sys.exit(0)

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

    if args.login:
        target_login_agent = args.agent or "software_engineer"
        login_url = config.resolve_api_url(args.api_url)
        if not login_url:
            ui.print_error("No SAFi backend URL configured. Run 'safi --set-url https://your-appliance' first.")
            sys.exit(1)
        try:
            identifier = input("SAFi username (or DOMAIN\\user): ").strip()
            password = getpass.getpass("Password: ")
            totp_code = ""
            ldap_hint = "\\" in identifier
            totp_hint = input("TOTP code (blank if MFA not enabled): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(1)
        login_client = SafiClient(login_url)
        try:
            payload = login_client.login(identifier, password, totp_code=totp_hint, ldap=ldap_hint)
        except Exception as exc:
            # Second chance: server demanded MFA we didn't supply.
            if getattr(exc, "status_code", None) == 401 and not totp_hint:
                try:
                    totp_code = input("Multi-factor code required. Enter TOTP code: ").strip()
                    payload = login_client.login(identifier, password, totp_code=totp_code, ldap=ldap_hint)
                except Exception as exc2:
                    ui.print_error(f"Login failed: {exc2}")
                    sys.exit(1)
            else:
                ui.print_error(f"Login failed: {exc}")
                sys.exit(1)
        new_key = payload.get("api_key") or ""
        if not new_key:
            ui.print_error("Server did not return an API key.")
            sys.exit(1)
        # The provisioned key is bound to the user's governing policy, so one
        # key is valid for every agent. Save it under all known agents so no
        # agent ever lacks a key; the active/default agent is software_engineer.
        login_client.api_key = new_key
        agents = login_client.get_available_agents()
        agent_names = [a.get("key") for a in agents if isinstance(a, dict) and a.get("key")]
        if not agent_names:
            agent_names = list(AVAILABLE_AGENTS.keys())
        for name in dict.fromkeys(agent_names):
            config.save_agent_api_key(name, new_key)
        user_info = payload.get("user") or {}
        save_updates = {}
        if user_info.get("id"):
            save_updates["user_id"] = user_info["id"]
        if user_info.get("name") or identifier:
            save_updates["user_name"] = user_info.get("name") or identifier
        if not config.has_configured_api_url():
            save_updates["api_url"] = login_url
        if save_updates:
            config.save_config(save_updates)
        default_agent = "software_engineer" if "software_engineer" in agent_names else (agent_names[0] if agent_names else "software_engineer")
        config.set_default_agent(default_agent)
        ui.console.print(
            f"[bold green]✓ Logged in as {payload.get('user', {}).get('name', identifier)} — "
            f"Policy API key saved for {len(agent_names)} agent(s) to {config.CONFIG_FILE}[/]\n"
            f"[dim]Policy: {payload.get('policy_id', '?')} — key labelled 'safi-cli' (re-login replaces it). "
            f"Default agent: {default_agent}.[/]"
        )
        sys.exit(0)

    if args.set_url:
        new_url = args.set_url.strip().rstrip("/")
        if not new_url.startswith(("http://", "https://")):
            new_url = f"https://{new_url}"
        ui.console.print(f"[dim]⠋ Verifying connection to {new_url}...[/dim]")
        test_client = SafiClient(new_url)
        is_live, err_msg, meta = test_client.verify_connection()
        if is_live:
            config.save_config({"api_url": new_url})
            ui.console.print(f"[bold green]✓ Verified and saved API URL to {config.CONFIG_FILE}[/]")
            agents = meta.get("agents") or []
            if agents:
                ui.console.print(f"[dim]Discovered {len(agents)} available agent(s) on {new_url}.[/dim]")
            sys.exit(0)
        else:
            ui.console.print(f"[bold red]✗ Connection verification failed:[/] {err_msg}")
            ui.console.print(f"[yellow]URL '{new_url}' was not saved. Please verify the endpoint is reachable or run 'safi-cli --setup'.[/]")
            sys.exit(1)

    # Run setup wizard if requested via --setup or on first run in an interactive terminal
    is_first_run = (not config.has_configured_api_url() and not args.api_url)
    if args.setup_wizard or (is_first_run and sys.stdin.isatty()):
        wizard_url, wizard_agent, wizard_key = run_setup_wizard()
        args.api_url = wizard_url
        args.agent = wizard_agent
        args.api_key = wizard_key

    workspace_root = Path(args.workspace).resolve()
    target_agent = args.agent or config.get_workspace_agent(str(workspace_root)) or config.get_default_agent() or "software_engineer"

    api_url = config.resolve_api_url(args.api_url)
    api_key = config.resolve_agent_api_key(target_agent, args.api_key)
    user_name = config.resolve_user_name(args.user_name)

    client = SafiClient(api_url, api_key or "")
    discover_agents(client)

    if AVAILABLE_AGENTS and target_agent not in AVAILABLE_AGENTS:
        target_agent = next(iter(AVAILABLE_AGENTS))
        api_key = config.resolve_agent_api_key(target_agent, args.api_key)
        client.api_key = api_key or ""
        config.set_default_agent(target_agent)
        config.set_workspace_agent(str(workspace_root), target_agent)

    if not api_key:
        agent_title = AVAILABLE_AGENTS.get(target_agent, {}).get("title", target_agent)
        ui.console.print(
            f"[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]\n"
            f"[dim]Each agent is governed by its own domain policy and requires its own Policy API Key.[/dim]"
        )
        try:
            identifier = input("SAFi username (or DOMAIN\\user, or press Enter for API key): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(1)

        if identifier:
            try:
                password = getpass.getpass("Password: ")
                totp_code = input("TOTP code (blank if MFA not enabled): ").strip()
                ldap_hint = "\\" in identifier
                payload = client.login(identifier, password, totp_code=totp_code, ldap=ldap_hint)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 401 and not totp_code:
                    try:
                        totp_code = input("Multi-factor code required. Enter TOTP code: ").strip()
                        payload = client.login(identifier, password, totp_code=totp_code, ldap=ldap_hint)
                    except Exception as exc2:
                        ui.print_error(
                            f"Login failed: {exc2}\n\n"
                            "You can also set a key via:\n"
                            f"  • safi-cli --login\n"
                            f"  • safi-cli --set-key sk-safi-... -a {target_agent}"
                        )
                        sys.exit(1)
                else:
                    ui.print_error(f"Login failed: {exc}")
                    sys.exit(1)
            api_key = payload.get("api_key") or ""
            if not api_key:
                ui.print_error("Server did not return an API key.")
                sys.exit(1)
            user_info = payload.get("user") or {}
            save_updates = {}
            if user_info.get("id"):
                save_updates["user_id"] = user_info["id"]
            if user_info.get("name") or identifier:
                save_updates["user_name"] = user_info.get("name") or identifier
            if save_updates:
                config.save_config(save_updates)
            for name in AVAILABLE_AGENTS.keys():
                config.save_agent_api_key(name, api_key)
            ui.console.print(
                f"[bold green]✓ Logged in as {payload.get('user', {}).get('name', identifier)}[/] "
                f"[dim]Policy: {payload.get('policy_id', '?')}[/]"
            )
        else:
            try:
                api_key = input(f"Enter Policy API Key (sk-safi-...): ").strip()
            except (KeyboardInterrupt, EOFError):
                sys.exit(1)
            if not api_key:
                ui.print_error(
                    f"No SAFi Policy API key provided for '{target_agent}'.\n\n"
                    "You can also set it via:\n"
                    f"  • export SAFI_API_KEY_{target_agent.upper()}=sk-safi-...\n"
                    f"  • safi-cli --set-key sk-safi-... -a {target_agent}"
                )
                sys.exit(1)
        config.save_agent_api_key(target_agent, api_key)
        client.api_key = api_key
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")
        discover_agents(client)
        if AVAILABLE_AGENTS and target_agent not in AVAILABLE_AGENTS:
            target_agent = next(iter(AVAILABLE_AGENTS))
            api_key = config.resolve_agent_api_key(target_agent)
            client.api_key = api_key or ""
            config.set_default_agent(target_agent)
            config.set_workspace_agent(str(workspace_root), target_agent)

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
