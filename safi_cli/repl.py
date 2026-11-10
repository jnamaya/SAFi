"""Interactive REPL: command menu, completions, session setup wizard."""

import glob
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None

from . import config, prompt_input, tools, ui
from .client import SafiClient, SafiClientError

logger = logging.getLogger("safi.main")


from . import agent_registry, turn_loop
from .agent_registry import (
    AVAILABLE_AGENTS,
    COMMAND_OPTIONS,
    DEFAULT_AGENTS,
    discover_agents,
    discover_models,
    discover_serving_model,
    is_serving_alias,
    prompt_switch_agent,
    prompt_switch_model,
    resolve_model_preference,
    serving_model_id,
    _infer_provider,
)
from .turn_loop import DEFAULT_MAX_STEPS, run_agent_turn


def _collect_multiline(initial: str) -> str:
    """Join backslash-continued input lines so users can compose/paste multi-line prompts."""
    return prompt_input.collect_multiline(initial)


def _archive_scratchpad(workspace_root: Path) -> None:
    """Rotate .safi/scratchpad.md to .safi/scratchpad.prev.md on session reset."""
    try:
        sp = Path(workspace_root) / ".safi" / "scratchpad.md"
        if sp.is_file():
            prev_sp = Path(workspace_root) / ".safi" / "scratchpad.prev.md"
            sp.replace(prev_sp)
    except Exception as exc:
        logger.warning("Could not archive scratchpad in %s: %s", workspace_root, exc)


def show_config(
    client: SafiClient,
    workspace_root: Path,
    current_agent: str,
    current_conv: str,
    current_model: Optional[str] = None,
):
    """Display current runtime settings and Policy API key status."""
    from rich.table import Table
    from rich import box

    discover_agents(client)
    pref = config.resolve_intellect_model(current_agent)
    if not current_model and is_serving_alias(pref):
        pref = discover_serving_model(client)
    resolved_model = current_model or pref or "(policy default)"
    ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]● SAFi CLI Configuration[/]")
    ui.console.print(f"  [dim]Backend URL:[/]     {client.api_url}")
    ui.console.print(f"  [dim]Workspace:[/]       {workspace_root}")
    ui.console.print(f"  [dim]Active Agent:[/]    [bold {ui.COLOR_BRAND_500}]{current_agent}[/]")
    ui.console.print(f"  [dim]Model:[/]           [bold {ui.COLOR_BRAND_400}]{resolved_model}[/]")
    ui.console.print(f"  [dim]Active Session:[/]  [dim]{current_conv}[/]")
    names = config.session_names()
    if names.get(current_conv):
        ui.console.print(f"  [dim]Session Name:[/]    [bold white]{names[current_conv]}[/]")
    ui.console.print(f"  [dim]Config File:[/]     {config.CONFIG_FILE}\n")

    table = Table(title="Policy API Keys by Agent", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
    table.add_column("Agent Key", style=f"bold {ui.COLOR_BRAND_400}")
    table.add_column("Title", style="bold white")
    table.add_column("Policy API Key", style="dim")

    for k, v in AVAILABLE_AGENTS.items():
        key_val = config.resolve_agent_api_key(k)
        if key_val:
            masked = key_val[:8] + "..." + key_val[-4:] if len(key_val) > 14 else "••••••••"
            status = f"[{ui.COLOR_PASS}]✓ Configured ({masked})[/]"
        else:
            status = f"[{ui.COLOR_WARN}]⚠️  Key Needed[/]"
        table.add_row(k, v["title"], status)

    ui.console.print(table)


def print_help():
    """Print help menu."""
    commands = [
        ("/", "Open interactive command menu"),
        ("/agents", "Interactive agent selector & Policy API key status"),
        ("/agent <name>", "Switch directly to an agent (e.g. /agent fiduciary)"),
        ("/models", "Select the AI model powering the agent"),
        ("/model <name>", "Switch directly to an AI model (e.g. /model gpt-4o)"),
        ("/memory", "Show the agent's distilled working memory summary"),
        ("/memory compress", "Compact conversation history and distill working memory to save tokens"),
        ("/memory clear", "Clear compacted memory summary and reset agent context"),
        ("/compress", "Alias for /memory compress (compact conversation history)"),
        ("/session name <name>", "Assign a friendly name to the current session (or /title <name>)"),
        ("/sessions [resume <name>]", "List stored sessions or resume one by name/number"),
        ("/audit", "View detailed governance audit ledger & rationales for the last turn"),
        ("/usage", "Show session token, cost, and compaction totals"),
        ("/last [tool]", "Page through the full output of the last tool result"),
        ("/compact-ui", "Hide or show the compact governance audit line on responses"),
        ("/schedule <time> <instruction>", "Schedule delayed or recurring tasks (e.g. /schedule 10m run audit)"),
        ("/tasks", "List active scheduled tasks and countdowns"),
        ("/queue", "View or clear queued prompts awaiting execution"),
        ("/skills", "List custom project skills defined in .safi/skills/"),
        ("/new", "Start a fresh conversation session without clearing screen"),
        ("/clear [screen]", "Clear screen & reset session memory (or /clear screen for visual only)"),
        ("/reset", "Reset session and flush agent working memory"),
        ("/config", "View backend URL, active model, and Policy API key status"),
        ("/setup-key [target]", "Deploy SSH key to Linux or Windows server from inventory"),
        ("/setup-cloud", "Configure Microsoft 365 or Azure credentials & test connectivity"),
        ("/cloud-status", "View connected M365 tenants and Azure subscriptions"),
        ("/keygen", "Generate the local Ed25519 key pair (no deployment)"),
        ("/help", "Show this help menu"),
        ("exit, quit, :q", "Exit SAFi CLI"),
    ]
    ui.render_menu(
        "Available Slash Commands",
        [
            {"name": "Command", "style": f"bold {ui.COLOR_BRAND_400}"},
            {"name": "Description", "style": "dim white"},
        ],
        [list(row) for row in commands],
    )


def _render_scheduled_tasks(tasks: List[Any]) -> None:
    from . import scheduler
    if not tasks:
        ui.console.print("[dim]No scheduled tasks. Use /schedule <time> <instruction> to create one.[/dim]")
        return
    rows = []
    for t in tasks:
        task_type = "Recurring" if t.repeat else "Once"
        rem = scheduler.format_remaining_time(t.remaining_seconds) if t.status == "pending" else t.status
        interval = scheduler.format_remaining_time(t.interval_seconds) if t.interval_seconds else "-"
        prompt_snippet = t.prompt if len(t.prompt) <= 35 else t.prompt[:32] + "..."
        agent_lbl = t.agent or "active"
        rows.append([t.id, task_type, rem, interval, prompt_snippet, agent_lbl, t.status])
    ui.render_menu(
        "Scheduled Tasks",
        [
            {"name": "Task ID", "style": f"bold {ui.COLOR_BRAND_400}"},
            {"name": "Type", "style": "cyan"},
            {"name": "Next Run", "style": "bold yellow"},
            {"name": "Interval", "style": "dim"},
            {"name": "Prompt", "style": "white"},
            {"name": "Agent", "style": "dim green"},
            {"name": "Status", "style": "magenta"},
        ],
        rows,
    )
    ui.console.print("[dim]Cancel a task with: /schedule cancel <task_id>[/dim]")


def _render_queued_prompts(items: List[Any]) -> None:
    if not items:
        ui.console.print("[dim]No prompts currently queued.[/dim]")
        return
    rows = []
    for idx, item in enumerate(items, 1):
        prompt_snippet = item.prompt if len(item.prompt) <= 45 else item.prompt[:42] + "..."
        rows.append([f"#{idx}", item.id, item.source, prompt_snippet, item.agent or "active"])
    ui.render_menu(
        "Prompt Queue",
        [
            {"name": "Position", "style": f"bold {ui.COLOR_BRAND_400}"},
            {"name": "ID", "style": "dim"},
            {"name": "Source", "style": "cyan"},
            {"name": "Prompt", "style": "white"},
            {"name": "Agent", "style": "dim green"},
        ],
        rows,
    )
    ui.console.print("[dim]Clear queue with: /queue clear[/dim]")


def _handle_schedule_command(line: str, sched: Any, current_agent: str) -> None:
    from . import scheduler
    parts = line.split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) > 1 else ""

    if sub in ("list", "ls", "show", ""):
        _render_scheduled_tasks(sched.list_all_tasks())
        return

    if sub in ("cancel", "rm", "delete", "remove"):
        target_id = parts[2].strip() if len(parts) > 2 else ""
        if not target_id:
            ui.console.print("[dim]Usage: /schedule cancel <task_id>[/dim]")
        elif sched.cancel_task(target_id):
            ui.console.print(f"[bold green]✓ Cancelled scheduled task:[/] [cyan]{target_id}[/]")
        else:
            ui.console.print(f"[{ui.COLOR_WARN}]Task ID not found:[/] {target_id}")
        return

    if sub in ("every", "recurring", "repeat"):
        sub_parts = parts[2].split(maxsplit=1) if len(parts) > 2 else []
        if len(sub_parts) < 2:
            ui.console.print("[dim]Usage: /schedule every <interval> <instruction> (e.g. /schedule every 1h run health check)[/dim]")
            return
        interval_str, task_prompt = sub_parts[0], sub_parts[1].strip()
        interval_sec = scheduler.parse_time_offset(interval_str)
        if not interval_sec:
            ui.console.print(f"[{ui.COLOR_FAIL}]Invalid interval:[/] '{interval_str}'. Use formats like 30s, 5m, 1h, 1d.")
            return
        t = sched.schedule_recurring(interval_sec, task_prompt, agent=current_agent)
        ui.console.print(
            f"[bold green]✓ Scheduled recurring task:[/] [cyan]{t.id}[/]\n"
            f"[dim]Runs every {scheduler.format_remaining_time(interval_sec)}: '{t.prompt}'[/dim]"
        )
        return

    time_str = sub
    task_prompt = parts[2].strip() if len(parts) > 2 else ""
    if not task_prompt:
        ui.console.print("[dim]Usage: /schedule <time> <instruction> (e.g. /schedule 10m run git status)[/dim]")
        return
    delay_sec = scheduler.parse_time_offset(time_str)
    if not delay_sec:
        ui.console.print(f"[{ui.COLOR_FAIL}]Invalid delay:[/] '{time_str}'. Use formats like 30s, 5m, 1h, 1d.")
        return
    t = sched.schedule_once(delay_sec, task_prompt, agent=current_agent)
    ui.console.print(
        f"[bold green]✓ Scheduled task:[/] [cyan]{t.id}[/]\n"
        f"[dim]Runs in {scheduler.format_remaining_time(delay_sec)}: '{t.prompt}'[/dim]"
    )


def prompt_resume_session(current_conv: str, workspace_root: Path, target_arg: Optional[str] = None) -> str:
    """List stored conversation sessions and resume a selected one."""
    sessions = config.list_sessions()
    if not sessions:
        ui.console.print(f"[{ui.COLOR_WARN}]No stored sessions yet. Start a conversation to create one.[/]")
        return current_conv

    paths = config.session_paths()
    names = config.session_names()
    agents = config.session_agents()
    entries = list(sessions.items())

    if target_arg:
        arg_clean = target_arg.strip().lower()
        if arg_clean.isdigit() and 1 <= int(arg_clean) <= len(entries):
            conv_id = entries[int(arg_clean) - 1][1]
            config.set_workspace_session(str(workspace_root), conv_id)
            label = f"'{names[conv_id]}' ({conv_id})" if names.get(conv_id) else conv_id
            ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Resumed session:[/] [dim]{label}[/]")
            return conv_id
        for _, conv_id in entries:
            name = names.get(conv_id, "").lower()
            if arg_clean == name or conv_id.lower().startswith(arg_clean):
                config.set_workspace_session(str(workspace_root), conv_id)
                label = f"'{names[conv_id]}' ({conv_id})" if names.get(conv_id) else conv_id
                ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Resumed session:[/] [dim]{label}[/]")
                return conv_id
        ui.console.print(f"[bold {ui.COLOR_FAIL}]Session not found matching:[/] '{target_arg}'.")
        return current_conv

    rows = []
    for idx, (key, conv_id) in enumerate(entries, 1):
        active = f" [bold {ui.COLOR_BRAND_500}](active)[/]" if conv_id == current_conv else ""
        ws = paths.get(conv_id) or f"…{key}"
        name = names.get(conv_id) or "[dim](unnamed)[/dim]"
        ag = agents.get(conv_id) or "[dim]default[/dim]"
        rows.append([str(idx), name, ag, conv_id, ws + active])

    ui.render_menu(
        "Stored Sessions",
        [
            {"name": "#", "style": f"bold {ui.COLOR_WARN}", "width": 3, "justify": "right"},
            {"name": "Session Name", "style": "bold white"},
            {"name": "Agent", "style": f"bold {ui.COLOR_BRAND_500}"},
            {"name": "Session ID", "style": f"bold {ui.COLOR_BRAND_400}"},
            {"name": "Workspace", "style": "dim"},
        ],
        rows,
    )

    try:
        choice = input("\nResume session [# or Name] (or press Enter to cancel): ").strip()
    except (KeyboardInterrupt, EOFError):
        return current_conv

    if not choice:
        return current_conv
    if choice.isdigit() and 1 <= int(choice) <= len(entries):
        conv_id = entries[int(choice) - 1][1]
        config.set_workspace_session(str(workspace_root), conv_id)
        label = f"'{names[conv_id]}' ({conv_id})" if names.get(conv_id) else conv_id
        ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Resumed session:[/] [dim]{label}[/]")
        return conv_id

    choice_lower = choice.lower()
    for _, conv_id in entries:
        name = names.get(conv_id, "").lower()
        if choice_lower == name or conv_id.lower().startswith(choice_lower):
            config.set_workspace_session(str(workspace_root), conv_id)
            label = f"'{names[conv_id]}' ({conv_id})" if names.get(conv_id) else conv_id
            ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Resumed session:[/] [dim]{label}[/]")
            return conv_id

    ui.console.print(f"[bold {ui.COLOR_FAIL}]Invalid selection:[/] '{choice}'.")
    return current_conv


def prompt_command_menu(
    current_agent: str,
    client: SafiClient,
    workspace_root: Path,
    current_conv: str,
    current_model: Optional[str] = None,
    current_user_name: Optional[str] = None,
    user_id: str = "cli_user",
) -> tuple[str, str, Optional[str], Optional[str], bool]:
    """Display the interactive slash command menu when the user types '/'."""
    rows = [
        [str(idx), f"/{cmd}", action, desc]
        for idx, (cmd, action, desc) in enumerate(COMMAND_OPTIONS, 1)
    ]
    ui.console.print()
    ui.render_menu(
        "SAFi Command Menu",
        [
            {"name": "#", "style": f"bold {ui.COLOR_WARN}", "width": 3, "justify": "right"},
            {"name": "Command", "style": f"bold {ui.COLOR_BRAND_400}"},
            {"name": "Action", "style": "bold white"},
            {"name": "Description", "style": "dim"},
        ],
        rows,
    )

    old_completer = readline.get_completer() if readline else None
    if readline:
        menu_cmds = [cmd for cmd, _, _ in COMMAND_OPTIONS]
        def menu_sub_completer(text: str, state: int) -> Optional[str]:
            clean_text = text.lstrip("/")
            matches = [f"/{c}" if text.startswith("/") else c for c in menu_cmds if c.startswith(clean_text)]
            if state < len(matches):
                return matches[state]
            return None
        readline.set_completer(menu_sub_completer)

    try:
        choice = input("\nSelect an option [# or command] (or press Enter to cancel): ").strip()
    except (KeyboardInterrupt, EOFError):
        return current_agent, current_conv, current_model, current_user_name, False
    finally:
        if readline and old_completer:
            readline.set_completer(old_completer)

    if not choice:
        return current_agent, current_conv, current_model, current_user_name, False

    choice_clean = choice.lstrip("/").lower().strip()

    if choice_clean.isdigit():
        idx = int(choice_clean) - 1
        if 0 <= idx < len(COMMAND_OPTIONS):
            choice_clean = COMMAND_OPTIONS[idx][0]

    if choice_clean in ("agents", "agent", "switch"):
        new_agent, new_conv = prompt_switch_agent(
            current_agent=current_agent,
            client=client,
            workspace_root=workspace_root,
        )
        new_model = resolve_model_preference(client, new_agent)
        return new_agent, new_conv, new_model, current_user_name, False

    elif choice_clean == "new":
        new_conv = config.resolve_session_id(str(workspace_root), new_session=True, agent=current_agent)
        config.set_workspace_agent(str(workspace_root), current_agent, new_conv)
        try:
            client.clear_agent_memory(new_conv, user_id=user_id, agent=current_agent)
        except Exception as exc:
            logger.warning("Could not clear agent memory for new session: %s", exc)
        _archive_scratchpad(workspace_root)
        ui.reset_session_telemetry()
        ui.clear_active_todos()
        ui.console.print(f"[bold {ui.COLOR_PASS}]Started new conversation session:[/] [dim]{new_conv}[/]")
        return current_agent, new_conv, current_model, current_user_name, False

    elif choice_clean in ("clear", "reset"):
        os.system("cls" if os.name == "nt" else "clear")
        new_conv = config.resolve_session_id(str(workspace_root), new_session=True, agent=current_agent)
        config.set_workspace_agent(str(workspace_root), current_agent, new_conv)
        try:
            client.clear_agent_memory(new_conv, user_id=user_id, agent=current_agent)
        except Exception as exc:
            logger.warning("Could not clear agent memory for new session: %s", exc)
        _archive_scratchpad(workspace_root)
        ui.reset_session_telemetry()
        ui.clear_active_todos()
        ui.record_compression_reset()
        ui.print_banner(
            str(workspace_root),
            current_agent,
            client.api_url,
            user_name=current_user_name,
            intellect_model=current_model,
        )
        ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Cleared screen and started fresh session:[/] [dim]{new_conv}[/]")
        ui.console.print("[dim green]↳ Flushed previous conversation and agent working memory.[/dim green]\n")
        return current_agent, new_conv, current_model, current_user_name, False

    elif choice_clean in ("config", "keys"):
        show_config(client, workspace_root, current_agent, current_conv, current_model=current_model)
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("audit", "ledger"):
        if turn_loop.get_last_turn_result():
            ui.print_audit_details(turn_loop.get_last_turn_result())
        else:
            ui.console.print(f"[{ui.COLOR_WARN}]No recent turn audit available yet. Run a prompt first.[/]")
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("models", "model"):
        updated_model = prompt_switch_model(
            current_model=current_model,
            client=client,
            current_agent=current_agent,
        )
        return current_agent, current_conv, updated_model, current_user_name, False

    elif choice_clean in ("memory", "working-memory", "compress", "summarize", "compact"):
        if choice_clean in ("compress", "summarize", "compact"):
            sub_c = "compress"
        else:
            ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]● Working Memory & Token Compaction[/]")
            ui.console.print("  [bold cyan]1[/] View active working memory summary")
            ui.console.print("  [bold cyan]2[/] Compact conversation history & distill memory (/memory compress)")
            ui.console.print("  [bold cyan]3[/] Clear working memory summary & reset context (/memory clear)")
            try:
                sub_c = input("\nSelect option (1-3, or Enter to view): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return current_agent, current_conv, current_model, current_user_name, False

        if sub_c in ("2", "compress", "compact"):
            with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Compressing conversation tokens...[/]", spinner="dots"):
                comp_res = client.compress_conversation(
                    current_conv,
                    user_id=user_id,
                    agent=current_agent,
                    model=current_model,
                    action="compress",
                )
            ui.clear_live_status_tail()
            if comp_res.get("ok") and comp_res.get("compressed"):
                ui.record_compression_telemetry(
                    tokens_before=comp_res.get("tokens_before", 0),
                    tokens_after=comp_res.get("tokens_after", 0),
                    tokens_saved=comp_res.get("tokens_saved", 0),
                    reduction_pct=comp_res.get("reduction_pct", 0.0),
                    intellect_model=current_model,
                )
            ui.print_compression_result(comp_res)
        elif sub_c in ("3", "clear", "reset"):
            with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Clearing memory summary & agent context...[/]", spinner="dots"):
                comp_res = client.compress_conversation(
                    current_conv,
                    user_id=user_id,
                    agent=current_agent,
                    model=current_model,
                    action="clear",
                    clear_agent_memory=True,
                )
            ui.clear_live_status_tail()
            ui.record_compression_reset()
            ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Compacted memory summary and agent context memory cleared.[/]")
        else:
            with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Fetching active memory summary...[/]", spinner="dots"):
                comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="get")
            ui.clear_live_status_tail()
            if comp_res.get("summary") or comp_res.get("agent_context"):
                ui.print_compression_result(comp_res)
            else:
                ui.console.print("[dim]No active memory summary or project context exists for this agent yet. Run /memory compress to distill one, or continue chatting.[/dim]")
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("skills", "skill"):
        from .skills import discover_skills
        local_skills = discover_skills(workspace_root)
        if local_skills:
            ui.render_menu(
                "Custom Project Skills (.safi/skills/)",
                [
                    {"name": "Command", "style": f"bold {ui.COLOR_BRAND_400}"},
                    {"name": "Description", "style": "white"},
                    {"name": "Path", "style": "dim"},
                ],
                [
                    [f"/{s_name}", s_obj.description, str(s_obj.file_path.relative_to(workspace_root))]
                    for s_name, s_obj in local_skills.items()
                ],
            )
        else:
            ui.console.print(f"[dim]No custom skills found in {workspace_root / '.safi' / 'skills'}. Create a .md file there to add skills![/dim]")
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("schedule", "tasks", "schedules"):
        from . import scheduler
        sched = scheduler.get_scheduler()
        _render_scheduled_tasks(sched.list_all_tasks())
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("queue", "queued"):
        from . import scheduler
        q = scheduler.get_prompt_queue()
        _render_queued_prompts(q.peek_all())
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("usage", "totals"):
        ui.console.print()
        ui.console.print(ui.build_session_usage_panel())
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("last", "last-result"):
        ui.print_full_tool_result()
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("compact-ui", "density", "toggle-ui"):
        new_flag = not ui.get_show_audit_panel()
        ui.set_show_audit_panel(new_flag)
        state = "shown" if new_flag else "hidden"
        ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Governance audit line is now {state}.[/]")
        return current_agent, current_conv, current_model, current_user_name, False


    elif choice_clean in ("sessions", "session", "resume"):
        new_conv = prompt_resume_session(current_conv, workspace_root)
        return current_agent, new_conv, current_model, current_user_name, False

    elif choice_clean in ("setup-key", "push-key", "ssh-key"):
        from . import ssh_keys
        ssh_keys.interactive_setup_key()
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("setup-cloud", "cloud", "cloud-setup"):
        from . import cloud
        cloud.interactive_setup_cloud()
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("cloud-status",):
        from . import cloud
        ui.console.print(cloud.execute_cloud_status())
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("keygen", "gen-key"):
        from . import ssh_keys
        ssh_keys.keygen_local()
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("help", "?"):
        print_help()
        return current_agent, current_conv, current_model, current_user_name, False

    elif choice_clean in ("exit", "quit", ":q"):
        ui.console.print("[dim]Goodbye.[/dim]")
        return current_agent, current_conv, current_model, current_user_name, True

    else:
        ui.console.print(f"[bold {ui.COLOR_FAIL}]Unknown command:[/] '{choice}'. Type [bold]/[/] to see options.")
        return current_agent, current_conv, current_model, current_user_name, False


SLASH_COMMANDS = [
    "/agents",
    "/agent",
    "/models",
    "/model",
    "/memory",
    "/compress",
    "/skills",
    "/audit",
    "/ledger",
    "/new",
    "/clear",
    "/reset",
    "/config",
    "/keys",
    "/usage",
    "/last",
    "/compact-ui",
    "/schedule",
    "/tasks",
    "/schedules",
    "/queue",
    "/sessions",
    "/setup-key",
    "/ssh-key",
    "/setup-cloud",
    "/cloud",
    "/cloud-status",
    "/help",
    "/exit",
    "/quit",
]


def _compute_completions(
    line: str,
    text: str,
    client: Optional[SafiClient] = None,
    workspace_root: Optional[Path] = None,
) -> List[str]:
    """Compute auto-completion matches for the given input line and current token."""
    line_clean = line.lstrip()

    if line_clean.startswith("/"):
        tokens = line_clean.split()

        if len(tokens) <= 1 and not line.endswith(" "):
            commands = list(SLASH_COMMANDS)
            if workspace_root:
                try:
                    from .skills import discover_skills
                    local_skills = discover_skills(workspace_root)
                    for s in local_skills.keys():
                        commands.append(f"/{s}")
                except Exception as exc:
                    logger.debug("Skill discovery for completion failed: %s", exc)
            exact = [c for c in commands if c.startswith(text)]
            sub = [c for c in commands if text.lower() in c.lower() and c not in exact]
            return exact + sub

        cmd = tokens[0].lower() if tokens else ""

        if cmd in ("/setup-key", "/ssh-key", "/push-key"):
            targets = config.get_inventory_targets()
            exact = [t for t in targets if t.startswith(text)]
            sub = [t for t in targets if text.lower() in t.lower() and t not in exact]
            return exact + sub

        if cmd in ("/agent", "/agents", "/switch"):
            agent_keys = list(AVAILABLE_AGENTS.keys())
            exact = [k for k in agent_keys if k.startswith(text)]
            sub = [k for k in agent_keys if text.lower() in k.lower() and k not in exact]
            return exact + sub

        if cmd in ("/model", "/models"):
            model_ids = [m["id"] for m in agent_registry.AVAILABLE_MODELS if "id" in m]
            exact = [m for m in model_ids if m.startswith(text)]
            sub = [m for m in model_ids if text.lower() in m.lower() and m not in exact]
            return exact + sub

        if cmd in ("/memory", "/compress", "/compact", "/summarize"):
            subcommands = ["compress", "show", "clear", "status", "view"]
            return [sc for sc in subcommands if sc.startswith(text)]

        if cmd in ("/last", "/last-result"):
            avail = tools.get_tools_for_agent(agent) or tools.TOOL_SCHEMAS
            tool_names = [t["function"]["name"] for t in avail]
            return [n for n in tool_names if n.startswith(text)]

        if cmd == "/clear":
            return [sc for sc in ["screen", "all"] if sc.startswith(text)]

        return []

    if text and workspace_root:
        try:
            root_str = str(workspace_root)
            target = os.path.join(root_str, text)
            matches = glob.glob(target + "*")
            results = []
            for m in matches:
                rel = os.path.relpath(m, root_str)
                if os.path.isdir(m):
                    rel += "/"
                results.append(rel)
            return sorted(results)
        except Exception as exc:
            logger.debug("Path completion failed: %s", exc)
            return []

    return []


_RICH_COMPLETION_CLIENT: Optional[SafiClient] = None
_RICH_COMPLETION_ROOT: Optional[Path] = None


def _rich_completions(line: str, text: str) -> List[str]:
    """Completion source for the prompt_toolkit composer (slash cmds, agents, models, paths)."""
    try:
        return _compute_completions(line, text, _RICH_COMPLETION_CLIENT, _RICH_COMPLETION_ROOT)
    except Exception as exc:
        logger.debug("Rich completion failed: %s", exc)
        return []


def setup_readline_completer(client: Optional[SafiClient] = None, workspace_root: Optional[Path] = None):
    """Configure readline auto-completion for slash commands, agent names, model names, and file paths."""
    if not readline:
        return

    try:
        readline.set_completer_delims(" \t\n")
    except Exception as exc:
        logger.debug("readline.set_completer_delims failed: %s", exc)

    try:
        if "libedit" in (getattr(readline, "__doc__", "") or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-query-items 0")
            readline.parse_and_bind("set page-completions off")
    except Exception as exc:
        logger.debug("readline.parse_and_bind failed: %s", exc)

    try:
        discover_agents(client)
    except Exception as exc:
        logger.debug("discover_agents during completion setup failed: %s", exc)

    cached: List[str] = []

    def cli_completer(text: str, state: int) -> Optional[str]:
        nonlocal cached
        if state == 0:
            try:
                line = readline.get_line_buffer()
                cached = _compute_completions(line, text, client, workspace_root)
            except Exception as exc:
                logger.debug("Completion computation failed: %s", exc)
                cached = []

        if state < len(cached):
            return cached[state]
        return None

    readline.set_completer(cli_completer)


def interactive_repl(
    client: SafiClient,
    workspace_root: Path,
    conversation_id: str,
    user_id: str,
    agent: str,
    user_name: Optional[str] = None,
    model: Optional[str] = None,
    auto_approve: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
):
    """Start an interactive command-line session."""
    current_agent = agent
    if AVAILABLE_AGENTS and current_agent not in AVAILABLE_AGENTS:
        current_agent = next(iter(AVAILABLE_AGENTS))
    current_user_name = user_name
    current_model = resolve_model_preference(client, current_agent, model)
    current_effort = config.resolve_reasoning_effort()
    ui.print_banner(
        str(workspace_root),
        current_agent,
        client.api_url,
        user_name=current_user_name,
        intellect_model=current_model,
    )
    ui.console.print(
        f"[dim]Commands: [bold {ui.COLOR_BRAND_400}]/[/] menu  •  [bold {ui.COLOR_BRAND_400}]/memory[/] memory & compact  •  [bold {ui.COLOR_BRAND_400}]/models[/] switch model  •  [bold {ui.COLOR_BRAND_400}]/agents[/] switch agent  •  [bold {ui.COLOR_BRAND_400}]/new[/] fresh session[/dim]\n"
    )
    rich_input = prompt_input.using_prompt_toolkit()

    config.ensure_config_dir()
    hist_file = str(config.get_agent_history_file(current_agent))

    if readline:
        setup_readline_completer(client, workspace_root)
        if not rich_input and os.path.exists(hist_file):
            try:
                readline.read_history_file(hist_file)
            except OSError:
                pass

    global _RICH_COMPLETION_CLIENT, _RICH_COMPLETION_ROOT
    _RICH_COMPLETION_CLIENT = client
    _RICH_COMPLETION_ROOT = workspace_root

    current_conv = conversation_id
    cancel_event = threading.Event()

    from . import scheduler
    sched = scheduler.get_scheduler()
    sched.set_wakeup_callback(prompt_input.wakeup_prompt_session)
    prompt_q = scheduler.get_prompt_queue()
    draft_text = ""

    ui.set_non_blocking_mode(True)
    turn_worker_stop = threading.Event()

    def _turn_worker_loop():
        while not turn_worker_stop.is_set():
            item = prompt_q.get(block=True, timeout=0.25)
            if turn_worker_stop.is_set() or not item:
                continue

            prompt_text = item.prompt
            turn_agent = item.agent or current_agent
            cancel_event.clear()
            scheduler.set_agent_busy(True, prompt_text)
            if item.source == "scheduled":
                ui.console.print(
                    f"\n[bold cyan]● Running scheduled task ({item.task_id or item.source}):[/] "
                    f"[bold white]{prompt_text}[/]"
                )
            ui.print_user_prompt(prompt_text, agent=turn_agent, user_name=current_user_name)
            try:
                run_agent_turn(
                    client=client,
                    prompt=prompt_text,
                    workspace_root=workspace_root,
                    conversation_id=current_conv,
                    user_id=user_id,
                    agent=turn_agent,
                    user_name=current_user_name,
                    model=current_model,
                    auto_approve=auto_approve,
                    max_steps=max_steps,
                    cancel_event=cancel_event,
                    echo_prompt=False,
                    reasoning_effort=current_effort,
                )
            except KeyboardInterrupt:
                ui.clear_live_status_tail()
                ui.console.print("\n[bold yellow]↳ Interrupted.[/bold yellow]")
            except Exception as exc:
                logger.error("Turn execution error: %s", exc)
                ui.print_error(f"Error executing turn: {exc}")
            finally:
                scheduler.set_agent_busy(False)
                prompt_input.wakeup_prompt_session()

    worker_thread = threading.Thread(target=_turn_worker_loop, daemon=True, name="safi-turn-worker")
    worker_thread.start()

    try:
        while True:
            agent_hist_file = str(config.get_agent_history_file(current_agent))
            if not rich_input and readline and agent_hist_file != hist_file:
                try:
                    readline.write_history_file(hist_file)
                except OSError:
                    pass
                hist_file = agent_hist_file
                if os.path.exists(hist_file):
                    try:
                        readline.read_history_file(hist_file)
                    except OSError:
                        pass
            try:
                raw_line = prompt_input.read_prompt(
                    agent_label=current_agent,
                    completions_fn=_rich_completions,
                    history_path=agent_hist_file if rich_input else None,
                    default=draft_text,
                )
                draft_text = ""
                if raw_line is None:
                    ui.console.print("\n[dim]Session terminated.[/dim]")
                    break

                if isinstance(raw_line, tuple) and len(raw_line) == 2 and raw_line[0] == "__QUEUED_WAKEUP__":
                    draft_text = raw_line[1] or ""
                    continue
                else:
                    line = str(raw_line).strip()
            except (KeyboardInterrupt, EOFError):
                if scheduler.is_agent_busy():
                    cancel_event.set()
                    ui.console.print("\n[bold yellow]↳ Sent interrupt to active turn (Ctrl+C).[/bold yellow]")
                    continue
                ui.console.print("\n[dim]Session terminated.[/dim]")
                break

            if not line:
                continue

            if line.lower() in ("exit", "quit", ":q", "/exit", "/quit"):
                ui.console.print("[dim]Goodbye.[/dim]")
                break

            if line.lower() in ("/cancel", "/stop", "/abort"):
                if scheduler.is_agent_busy():
                    cancel_event.set()
                    ui.console.print("\n[bold yellow]↳ Sent interrupt to active turn.[/bold yellow]")
                else:
                    ui.console.print("[dim]No agent turn is currently running.[/dim]")
                continue

            if line.lower() in ("/status", "/progress"):
                ui.console.print("[dim]Agent is idle. Ready for next prompt.[/dim]")
                continue

            if line.lower() in ("/", "/menu", "/commands", "menu"):
                current_agent, current_conv, current_model, current_user_name, should_exit = prompt_command_menu(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                    current_conv=current_conv,
                    current_model=current_model,
                    current_user_name=current_user_name,
                    user_id=user_id,
                )
                if should_exit:
                    break
                continue

            if line.lower().startswith(("/schedule", "/task", "/tasks")):
                _handle_schedule_command(line, sched, current_agent)
                continue

            if line.lower().startswith(("/queue", "/queued")):
                parts = line.split(maxsplit=1)
                sub = parts[1].strip().lower() if len(parts) > 1 else ""
                if sub in ("clear", "flush", "reset", "empty"):
                    cleared = prompt_q.clear()
                    ui.console.print(f"[bold green]✓ Cleared {cleared} queued prompt(s).[/]")
                else:
                    _render_queued_prompts(prompt_q.peek_all())
                continue

            if line.lower() == "/new":
                current_conv = config.resolve_session_id(str(workspace_root), new_session=True, agent=current_agent)
                config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
                try:
                    client.clear_agent_memory(current_conv, user_id=user_id, agent=current_agent)
                except Exception as exc:
                    logger.warning("Could not clear agent memory for new session: %s", exc)
                _archive_scratchpad(workspace_root)
                ui.reset_session_telemetry()
                ui.clear_active_todos()
                ui.record_compression_reset()
                ui.console.print(f"[bold green]Started new conversation session:[/] [cyan]{current_conv}[/]")
                ui.console.print("[dim green]↳ Cleared previous agent task & working memory.[/dim green]")
                continue

            if line.lower().startswith(("/clear", "/reset")):
                parts = line.split(maxsplit=1)
                sub_arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if sub_arg == "screen":
                    os.system("cls" if os.name == "nt" else "clear")
                    ui.print_banner(
                        str(workspace_root),
                        current_agent,
                        client.api_url,
                        user_name=current_user_name,
                        intellect_model=current_model,
                    )
                    continue

                os.system("cls" if os.name == "nt" else "clear")
                current_conv = config.resolve_session_id(str(workspace_root), new_session=True, agent=current_agent)
                config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
                try:
                    client.clear_agent_memory(current_conv, user_id=user_id, agent=current_agent)
                except Exception as exc:
                    logger.warning("Could not clear agent memory for new session: %s", exc)
                _archive_scratchpad(workspace_root)
                ui.reset_session_telemetry()
                ui.clear_active_todos()
                ui.record_compression_reset()
                ui.print_banner(
                    str(workspace_root),
                    current_agent,
                    client.api_url,
                    user_name=current_user_name,
                    intellect_model=current_model,
                )
                ui.console.print(f"[bold green]✓ Started fresh conversation session:[/] [cyan]{current_conv}[/]")
                ui.console.print("[dim green]↳ Cleared screen, session history, and agent working memory.[/dim green]\n")
                continue

            if line.lower() in ("/config", "/keys"):
                show_config(client, workspace_root, current_agent, current_conv, current_model=current_model)
                continue

            if line.lower().startswith(("/setup-key", "/ssh-key", "/push-key")):
                parts = line.split(maxsplit=1)
                sub_target = parts[1].strip() if len(parts) > 1 else ""
                from . import ssh_keys
                ssh_keys.interactive_setup_key(target_arg=sub_target or None)
                continue

            if line.lower().startswith(("/setup-cloud", "/cloud")):
                parts = line.split(maxsplit=1)
                sub_cmd = parts[1].strip().lower() if len(parts) > 1 else ""
                from . import cloud
                if sub_cmd in ("status", "info", "list"):
                    ui.console.print(cloud.execute_cloud_status())
                else:
                    cloud.interactive_setup_cloud()
                continue

            if line.lower() == "/cloud-status":
                from . import cloud
                ui.console.print(cloud.execute_cloud_status())
                continue

            if line.lower() in ("/audit", "/ledger"):
                if turn_loop.get_last_turn_result():
                    ui.print_audit_details(turn_loop.get_last_turn_result())
                else:
                    ui.console.print(f"[{ui.COLOR_WARN}]No recent turn audit available yet. Run a prompt first.[/]")
                continue

            if line.lower().startswith(("/memory", "/working-memory", "/compress", "/summarize", "/compact")):
                parts = line.split(maxsplit=1)
                cmd_head = parts[0].lower()
                sub_arg = parts[1].strip().lower() if len(parts) > 1 else ""

                # /compress with no args defaults to "compress"
                # /memory with no args defaults to "show"
                if not sub_arg:
                    if cmd_head in ("/compress", "/compact", "/summarize"):
                        sub_arg = "compress"
                    else:
                        sub_arg = "show"

                if sub_arg in ("show", "view", "get", "status"):
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Fetching active memory summary...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="get")
                    ui.clear_live_status_tail()
                    if comp_res.get("summary") or comp_res.get("agent_context"):
                        ui.print_compression_result(comp_res)
                    else:
                        ui.console.print("[dim]No active memory summary or project context exists for this agent yet. Run /memory compress to distill one, or continue chatting.[/dim]")
                elif sub_arg in ("clear", "reset"):
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Clearing memory summary & agent context...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="clear", clear_agent_memory=True)
                    ui.clear_live_status_tail()
                    ui.record_compression_reset()
                    ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Compacted memory summary and agent context memory cleared.[/]")
                elif sub_arg in ("compress", "compact", "summarize"):
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Compressing conversation tokens...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="compress")
                    ui.clear_live_status_tail()
                    if comp_res.get("ok") and comp_res.get("compressed"):
                        ui.record_compression_telemetry(
                            tokens_before=comp_res.get("tokens_before", 0),
                            tokens_after=comp_res.get("tokens_after", 0),
                            tokens_saved=comp_res.get("tokens_saved", 0),
                            reduction_pct=comp_res.get("reduction_pct", 0.0),
                            intellect_model=current_model,
                        )
                    ui.print_compression_result(comp_res)
                else:
                    ui.console.print(f"[bold {ui.COLOR_WARN}]Unknown memory subcommand:[/] '{sub_arg}'. Usage: /memory [compress | show | clear]")
                continue

            if line.lower().strip() in ("/agents", "/agent", "/switch", "/list-agents"):
                current_agent, current_conv = prompt_switch_agent(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                )
                current_model = resolve_model_preference(client, current_agent)
                continue

            if line.lower().startswith(("/agent ", "/agents ", "/switch ")):
                parts = line.split(maxsplit=1)
                req = parts[1].strip() if len(parts) > 1 else None
                current_agent, current_conv = prompt_switch_agent(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                    requested_agent=req,
                )
                current_model = resolve_model_preference(client, current_agent)
                continue

            if line.lower().strip() in ("/models", "/model", "/list-models", "model", "models"):
                current_model = prompt_switch_model(
                    current_model=current_model,
                    client=client,
                    current_agent=current_agent,
                )
                continue

            if line.lower().startswith(("/model ", "/models ", "model ", "models ")):
                parts = line.split(maxsplit=1)
                req = parts[1].strip() if len(parts) > 1 else None
                current_model = prompt_switch_model(
                    current_model=current_model,
                    client=client,
                    requested_model=req,
                    current_agent=current_agent,
                )
                continue

            if line.lower().startswith("/reasoning") or line.lower().startswith("/thinking"):
                parts = line.split(maxsplit=1)
                req = parts[1].strip().lower() if len(parts) > 1 else ""
                if req in config.REASONING_LEVELS:
                    current_effort = req
                    config.save_reasoning_effort(req)
                    ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Reasoning level set to:[/] [magenta]{req}[/] [dim](saved as default)[/]")
                elif req in ("off", "none", "default", "auto", ""):
                    current_effort = ""
                    if req:
                        config.save_reasoning_effort("")
                    label = current_effort or "default (provider decides)"
                    ui.console.print(f"[bold]Reasoning level:[/] [magenta]{current_effort or 'default (provider decides)'}[/]")
                else:
                    ui.console.print(
                        f"[bold]Reasoning level:[/] [magenta]{current_effort or 'default (provider decides)'}[/]\n"
                        f"[dim]Usage: /reasoning <low|medium|high|off> - controls thinking/reasoning "
                        f"effort for reasoning-capable models (e.g. gpt-5, o-series, Claude).[/]"
                    )
                continue

            if line.lower() in ("/usage", "/totals"):
                ui.console.print()
                ui.console.print(ui.build_session_usage_panel())
                continue

            if line.lower().startswith("/last"):
                parts = line.split(maxsplit=1)
                target_tool = parts[1].strip() if len(parts) > 1 else None
                ui.print_full_tool_result(target_tool or None)
                continue

            if line.lower() in ("/compact-ui", "/density", "/toggle-ui"):
                new_flag = not ui.get_show_audit_panel()
                ui.set_show_audit_panel(new_flag)
                state = "shown" if new_flag else "hidden"
                ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Governance audit line is now {state}.[/]")
                continue

            if line.lower().startswith(("/session", "/sessions", "/resume")):
                parts = line.split(maxsplit=2)
                sub = parts[1].strip().lower() if len(parts) > 1 else ""
                if sub in ("name", "rename", "title", "set-name"):
                    if len(parts) > 2 and parts[2].strip():
                        s_name = parts[2].strip()
                        config.set_session_name(current_conv, s_name)
                        ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Session named:[/] [bold white]{s_name}[/] [dim]({current_conv})[/]")
                    else:
                        current_names = config.session_names()
                        curr_name = current_names.get(current_conv)
                        if curr_name:
                            ui.console.print(f"[dim]Current session name:[/] [bold white]{curr_name}[/]")
                        ui.console.print("[dim]Usage: /session name <friendly_name>[/dim]")
                    continue
                elif sub in ("resume", "switch"):
                    target_name = parts[2].strip() if len(parts) > 2 else None
                    new_conv = prompt_resume_session(current_conv, workspace_root, target_arg=target_name)
                    if new_conv != current_conv:
                        current_conv = new_conv
                        resumed_agent = config.session_agent(current_conv)
                        if resumed_agent and resumed_agent != current_agent:
                            current_agent = resumed_agent
                            current_model = resolve_model_preference(client, current_agent)
                            client.api_key = config.resolve_agent_api_key(current_agent) or client.api_key
                            config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
                            agent_title = AVAILABLE_AGENTS.get(current_agent, {}).get("title", current_agent)
                            ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Switched active agent to:[/] [bold cyan]{current_agent}[/] ([green]{agent_title}[/])")
                    continue
                else:
                    target_arg = parts[1].strip() if len(parts) > 1 and sub not in ("list", "show") else None
                    new_conv = prompt_resume_session(current_conv, workspace_root, target_arg=target_arg)
                    if new_conv != current_conv:
                        current_conv = new_conv
                        resumed_agent = config.session_agent(current_conv)
                        if resumed_agent and resumed_agent != current_agent:
                            current_agent = resumed_agent
                            current_model = resolve_model_preference(client, current_agent)
                            client.api_key = config.resolve_agent_api_key(current_agent) or client.api_key
                            config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
                            agent_title = AVAILABLE_AGENTS.get(current_agent, {}).get("title", current_agent)
                            ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Switched active agent to:[/] [bold cyan]{current_agent}[/] ([green]{agent_title}[/])")
                    continue

            if line.lower().startswith(("/name-session", "/title")):
                parts = line.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    s_name = parts[1].strip()
                    config.set_session_name(current_conv, s_name)
                    ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Session named:[/] [bold white]{s_name}[/] [dim]({current_conv})[/]")
                else:
                    ui.console.print("[dim]Usage: /title <session_name>[/dim]")
                continue


            if line.lower() in ("/help", "/?", "help", "?"):
                print_help()
                continue

            if line.startswith("/"):
                from .skills import discover_skills
                local_skills = discover_skills(workspace_root)
                cmd_parts = line[1:].split(maxsplit=1)
                skill_trigger = cmd_parts[0].lower()
                skill_args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

                if skill_trigger in local_skills:
                    matched_skill = local_skills[skill_trigger]
                    rendered_prompt = matched_skill.render_prompt(skill_args)
                    ui.console.print(f"[bold {ui.COLOR_BRAND_400}]● Skill:[/] [bold white]{matched_skill.description}[/]")
                    if scheduler.is_agent_busy():
                        prompt_q.put(rendered_prompt, source=f"skill:{skill_trigger}", agent=current_agent)
                        ui.console.print(f"[bold green]✓ Queued skill prompt for next turn:[/] [white]{matched_skill.description}[/]")
                    else:
                        prompt_q.put(rendered_prompt, source=f"skill:{skill_trigger}", agent=current_agent)
                    continue
                elif skill_trigger in ("skills", "list-skills"):
                    if local_skills:
                        ui.render_menu(
                            "Custom Project Skills (.safi/skills/)",
                            [
                                {"name": "Command", "style": f"bold {ui.COLOR_BRAND_400}"},
                                {"name": "Description", "style": "white"},
                                {"name": "Path", "style": "dim"},
                            ],
                            [
                                [f"/{s_name}", s_obj.description, str(s_obj.file_path.relative_to(workspace_root))]
                                for s_name, s_obj in local_skills.items()
                            ],
                        )
                    else:
                        ui.console.print(f"[dim]No custom skills found in {workspace_root / '.safi' / 'skills'}. Create a .md file there to add skills![/dim]")
                    continue
                else:
                    ui.console.print(f"[bold {ui.COLOR_FAIL}]Unknown command:[/] '{line}'. Type [bold]/[/] to see options.")
                    continue

            # Only erase lines manually when using readline fallback; prompt_toolkit uses erase_when_done=True
            if not rich_input and sys.stdout.isatty():
                try:
                    cols = os.get_terminal_size(sys.__stdout__.fileno()).columns
                except (OSError, ValueError, AttributeError):
                    cols = shutil.get_terminal_size((80, 24)).columns
                margin_len = ui.CLI_MARGIN if ui.CLI_MARGIN > 0 else 0
                prompt_vis_len = margin_len + len(f" SAFi [{current_agent}] › ")
                input_lines = line.splitlines() or [""]
                lines_count = 1  # Account for top divider line
                for idx_l, l_str in enumerate(input_lines):
                    prefix_len = prompt_vis_len if idx_l == 0 else len("    ")
                    total_len = prefix_len + len(l_str)
                    lines_count += max(1, ((total_len - 1) // cols) + 1) if cols > 0 else 1
                for _ in range(lines_count):
                    sys.stdout.write("\033[F\033[2K")
                sys.stdout.flush()

            if is_serving_alias(config.resolve_intellect_model(current_agent)):
                current_model = resolve_model_preference(client, current_agent, force_refresh=True)

            if scheduler.is_agent_busy():
                prompt_q.put(line, source="user", agent=current_agent)
                ui.console.print(f"[bold green]✓ Queued prompt #{len(prompt_q.peek_all())}:[/] [bold white]{line}[/]")
                continue

            prompt_q.put(line, source="user", agent=current_agent)
            continue

    finally:
        ui.set_non_blocking_mode(False)
        turn_worker_stop.set()
        sched.shutdown()
        try:
            config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
        except Exception as exc:
            logger.warning("Could not persist workspace agent session state: %s", exc)
        if readline and not rich_input:
            try:
                readline.write_history_file(hist_file)
            except OSError:
                pass


def _wizard_login_or_key(api_url: str, agent: str) -> str:
    """Setup-wizard auth step: web username/password login (default) or manual key.

    Returns the Policy API key (already saved to config), or an empty string
    if the user skips.
    """
    import getpass

    while True:
        try:
            identifier = input("SAFi username (or DOMAIN\\user, or press Enter for API key): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

        if not identifier:
            try:
                key_val = input("Enter Policy API Key (sk-safi-...) [press Enter to skip for now]: ").strip()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)
            if key_val:
                config.save_agent_api_key(agent, key_val)
                ui.console.print(f"[bold green]✓ Saved Policy API Key for {agent} to {config.CONFIG_FILE}[/]")
            else:
                ui.console.print(f"[yellow]Skipped for now. You will be prompted when launching '{agent}'.[/]")
            return key_val

        # Web-credential login: exchange username/password for a provisioned key.
        try:
            password = getpass.getpass("Password: ")
            totp_code = input("TOTP code (blank if MFA not enabled): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

        login_client = SafiClient(api_url)
        ldap_hint = "\\" in identifier
        try:
            payload = login_client.login(identifier, password, totp_code=totp_code, ldap=ldap_hint)
        except Exception as exc:
            # Second chance: server demanded MFA we didn't supply.
            if getattr(exc, "status_code", None) == 401 and not totp_code:
                try:
                    totp_code = input("Multi-factor code required. Enter TOTP code: ").strip()
                    payload = login_client.login(identifier, password, totp_code=totp_code, ldap=ldap_hint)
                except Exception as exc2:
                    ui.print_error(f"Login failed: {exc2}")
                    continue
            else:
                ui.print_error(f"Login failed: {exc}")
                continue

        new_key = payload.get("api_key") or ""
        if not new_key:
            ui.print_error("Server did not return an API key.")
            continue
        # One policy key is valid for every agent - save it under all known
        # agents so none is left without a key (active agent stays 'agent').
        login_client.api_key = new_key
        user_info = payload.get("user") or {}
        user_id_val = user_info.get("id") or ""
        if user_id_val:
            login_client.user_id = user_id_val
        save_updates = {}
        if user_id_val:
            save_updates["user_id"] = user_id_val
        if user_info.get("name") or identifier:
            save_updates["user_name"] = user_info.get("name") or identifier
        if save_updates:
            config.save_config(save_updates)

        agents = login_client.get_available_agents()
        agent_names = [a.get("key") for a in agents if isinstance(a, dict) and a.get("key")]
        if not agent_names:
            config.set_default_agent("")
            ui.console.print(
                f"[bold green]✓ Logged in as {payload.get('user', {}).get('name', identifier)}[/]\n"
                f"[bold yellow]Notice:[/] No agents currently available. Contact your administrator to grant you access to an agent."
            )
            return None

        if agent not in agent_names:
            agent = agent_names[0]
        for name in agent_names:
            config.save_agent_api_key(name, new_key)
        default_agent = "software_engineer" if "software_engineer" in agent_names else agent_names[0]
        config.set_default_agent(default_agent)
        ui.console.print(
            f"[bold green]✓ Logged in as {payload.get('user', {}).get('name', identifier)} - "
            f"Policy API key saved for {len(agent_names)} agent(s) to {config.CONFIG_FILE}[/]\n"
            f"[dim]Policy: {payload.get('policy_id', '?')} - key labelled 'safi-cli' (re-login replaces it). "
            f"Default agent: {default_agent}.[/]"
        )
        return new_key


def run_setup_wizard() -> tuple[str, str, Optional[str]]:
    """Interactive onboarding wizard to configure SAFi CLI for the first time.

    Returns:
        (api_url, target_agent, api_key)
    """
    from rich.panel import Panel
    from rich import box

    ui.console.print()
    ui.console.print(
        Panel(
            "[bold white]Welcome to the SAFi Governed Agent Interface![/]\n\n"
            "[dim]This wizard connects your workstation to your SAFi appliance\n"
            "and configures your primary agent.[/dim]",
            title=f"[bold {ui.COLOR_BRAND_400}]SAFi CLI - Setup Wizard[/]",
            border_style=ui.COLOR_BRAND_500,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )

    cfg = config.load_config()
    prior_user = cfg.get("user_name") or cfg.get("user_id")
    prior_url = cfg.get("api_url")
    prior_key = config.resolve_agent_api_key("software_engineer") or config.resolve_agent_api_key("sysadmin") or cfg.get("api_key")
    if prior_user or prior_key:
        ui.console.print(
            f"\n[dim]Existing profile detected: User=[bold]{prior_user or 'Configured User'}[/], "
            f"Endpoint=[bold]{prior_url or 'Configured Endpoint'}[/][/dim]"
        )
        try:
            reset_choice = input("Reset prior profile and credentials to reconfigure from scratch? [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("\n[yellow]Setup cancelled.[/]")
            sys.exit(0)
        if reset_choice in ("y", "yes"):
            config.clear_credentials()
            ui.console.print("[bold green]✓ Prior profile and credentials cleared.[/]\n")

    # 1. Ask for SAFi Appliance URL
    existing_url = str(config.load_config().get("api_url") or "").strip() or prior_url or "https://localhost"
    ui.console.print("\n[bold white]1. SAFi Appliance Endpoint[/]")
    ui.console.print(
        "[dim]Enter the base URL of your SAFi server or Mini-PC appliance.\n"
        "Examples: [cyan]https://localhost[/], [cyan]https://192.168.1.223[/][/dim]"
    )

    while True:
        try:
            val = input(f"Endpoint URL [{existing_url}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("\n[yellow]Setup cancelled.[/]")
            sys.exit(0)

        chosen_url = val.rstrip("/") if val else existing_url
        if not chosen_url.startswith(("http://", "https://")):
            chosen_url = f"https://{chosen_url}"

        ui.console.print(f"[dim]⠋ Verifying connection to {chosen_url}...[/dim]")
        test_client = SafiClient(chosen_url)
        is_live, err_msg, meta = test_client.verify_connection()

        if is_live:
            agents = meta.get("agents") or []
            agent_names = [a.get("key") or a.get("name") for a in agents if isinstance(a, dict)]
            ui.console.print(
                f"[bold green]✓ Connected successfully to live SAFi endpoint![/] "
                + (f"[dim](Discovered {len(agents)} agent(s): {', '.join(agent_names)})[/dim]" if agent_names else "")
            )
            config.save_config({"api_url": chosen_url})
            discover_agents(test_client)
            break
        else:
            ui.console.print(f"[bold red]✗ Connection verification failed:[/] {err_msg}")
            ui.console.print(f"[dim]The server at [bold]{chosen_url}[/] is not responding as a live SAFi instance.[/dim]")
            try:
                confirm = input("Save this unverified endpoint anyway? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)
            if confirm in ("y", "yes"):
                config.save_config({"api_url": chosen_url})
                ui.console.print(f"[yellow]⚠️ Warning: Saved unverified URL '{chosen_url}'. CLI commands will fail until this endpoint is live.[/]")
                break
            else:
                ui.console.print("[dim]Please re-enter the correct endpoint URL.[/dim]")

    # 2. Authenticate: web login (default) or manual Policy API key
    ui.console.print(f"\n[bold white]2. Authenticate[/]")
    default_probe_agent = config.get_default_agent() or "software_engineer"
    existing_key = config.resolve_agent_api_key(default_probe_agent) or config.load_config().get("api_key")
    if existing_key:
        cfg = config.load_config()
        current_user = cfg.get("user_name") or cfg.get("user_id")
        user_label = f" for '{current_user}'" if current_user else ""
        ui.console.print(f"[bold green]✓ Found existing Policy API key{user_label} in config.[/]")
        try:
            reauth = input("Keep existing credentials? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            reauth = "y"
        if reauth in ("n", "no"):
            config.clear_credentials()
            ui.console.print(
                "[dim]Sign in with your new SAFi web username and password. A Policy API key\n"
                "is provisioned automatically and saved for all available agents.\n"
                "Or paste an existing key (sk-safi-...).[/dim]"
            )
            key_val = _wizard_login_or_key(chosen_url, default_probe_agent)
        else:
            key_val = existing_key
    else:
        ui.console.print(
            "[dim]Sign in with your SAFi web username and password. A Policy API key\n"
            "is provisioned automatically and saved for all available agents.\n"
            "Or paste an existing key (sk-safi-...).[/dim]"
        )
        key_val = _wizard_login_or_key(chosen_url, default_probe_agent)

    if not key_val:
        ui.print_error("No agents currently available. Contact your administrator to grant you access to an agent.")
        sys.exit(0)

    test_client = SafiClient(chosen_url, key_val or "", user_id=config.resolve_user_id())
    discover_agents(test_client)
    if not AVAILABLE_AGENTS:
        ui.print_error("No agents currently available. Contact your administrator to grant you access to an agent.")
        sys.exit(0)

    chosen_agent = config.get_default_agent() or next(iter(AVAILABLE_AGENTS), "software_engineer")
    agent_title = AVAILABLE_AGENTS.get(chosen_agent, {}).get("title", chosen_agent)

    ui.console.print()
    ui.console.print(
        Panel(
            f"[bold green]✓ SAFi CLI configured successfully![/]\n\n"
            f"[dim]• Endpoint: [cyan]{chosen_url}[/]\n"
            f"• Default Agent: [cyan]{chosen_agent}[/]\n"
            f"• Config File: [cyan]{config.CONFIG_FILE}[/][/dim]\n\n"
            f"[bold white]Launching {agent_title}...[/]",
            border_style=ui.COLOR_BRAND_600,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    return chosen_url, chosen_agent, key_val or None


