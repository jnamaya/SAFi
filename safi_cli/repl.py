"""Interactive REPL: command menu, completions, session setup wizard."""

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
            if comp_res.get("summary"):
                ui.print_compression_result({"ok": True, "compressed": False, "summary": comp_res["summary"], "message": "Showing active working memory summary."})
            else:
                ui.console.print("[dim]No active memory summary exists for this session yet. Run /memory compress to distill one, or continue chatting.[/dim]")
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

    elif choice_clean in ("user", "name"):
        try:
            curr = current_user_name or config.resolve_user_name() or "Unset"
            new_name = input(f"Enter user name (currently '{curr}'): ").strip()
            if new_name:
                config.save_user_name(new_name)
                current_user_name = new_name
                ui.console.print(f"[bold {ui.COLOR_PASS}]✓ User name updated to:[/] [magenta]{new_name}[/]")
        except (KeyboardInterrupt, EOFError):
            pass
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
    "/user",
    "/name",
    "/new",
    "/clear",
    "/reset",
    "/config",
    "/keys",
    "/usage",
    "/last",
    "/compact-ui",
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
                )
                if raw_line is None:
                    ui.console.print("\n[dim]Session terminated.[/dim]")
                    break
                line = raw_line.strip()
            except (KeyboardInterrupt, EOFError):
                ui.console.print("\n[dim]Session terminated.[/dim]")
                break

            if not line:
                continue
            if line.lower() in ("exit", "quit", ":q", "/exit", "/quit"):
                ui.console.print("[dim]Goodbye.[/dim]")
                break

            if line.lower() in ("/cancel", "/stop", "/abort"):
                ui.console.print("[dim]No agent turn is currently running. Press Ctrl+C during a turn to interrupt.[/dim]")
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
                    if comp_res.get("summary"):
                        ui.print_compression_result({"ok": True, "compressed": False, "summary": comp_res["summary"], "message": "Showing active memory summary."})
                    else:
                        ui.console.print("[dim]No active memory summary exists for this session yet. Run /memory compress to distill one, or continue chatting.[/dim]")
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

            if line.lower().startswith(("/user", "/name")):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    current_user_name = parts[1].strip()
                    config.save_user_name(current_user_name)
                    ui.console.print(f"[bold green]✓ User name updated to:[/] [magenta]{current_user_name}[/]")
                else:
                    ui.console.print(
                        f"[bold]Current user name:[/] [magenta]{current_user_name or 'Unset'}[/]\n"
                        f"[dim]To change, type: /user <Your Name>[/dim]"
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
                        f"[dim]Usage: /reasoning <low|medium|high|off> — controls thinking/reasoning "
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
                    ui.print_user_prompt(rendered_prompt)
                    try:
                        run_agent_turn(
                            client=client,
                            prompt=rendered_prompt,
                            workspace_root=workspace_root,
                            conversation_id=current_conv,
                            user_id=user_id,
                            agent=current_agent,
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
                        logger.error("Skill execution error: %s", exc)
                        ui.print_error(f"Error executing skill: {exc}")
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

            ui.print_user_prompt(line)

            try:
                run_agent_turn(
                    client=client,
                    prompt=line,
                    workspace_root=workspace_root,
                    conversation_id=current_conv,
                    user_id=user_id,
                    agent=current_agent,
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
            continue

    finally:
        try:
            config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
        except Exception as exc:
            logger.warning("Could not persist workspace agent session state: %s", exc)
        if readline and not rich_input:
            try:
                readline.write_history_file(hist_file)
            except OSError:
                pass


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
            "[dim]This quick wizard will connect your workstation to your SAFi appliance\n"
            "and configure your primary agent.[/dim]",
            title=f"[bold {ui.COLOR_BRAND_400}]SAFi CLI — First-Run Setup[/]",
            border_style=ui.COLOR_BRAND_500,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )

    # 1. Ask for SAFi Appliance URL
    existing_url = str(config.load_config().get("api_url") or "").strip() or "http://192.168.1.223:5001"
    ui.console.print("\n[bold white]1. SAFi Appliance Endpoint[/]")
    ui.console.print(
        "[dim]Enter the base URL of your SAFi server or Mini-PC appliance.\n"
        "Examples: [cyan]http://localhost:5000[/], [cyan]http://192.168.1.223:5001[/], [cyan]https://safi.local:5001[/][/dim]"
    )

    while True:
        try:
            val = input(f"Endpoint URL [{existing_url}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("\n[yellow]Setup cancelled.[/]")
            sys.exit(0)

        chosen_url = val.rstrip("/") if val else existing_url
        if not chosen_url.startswith(("http://", "https://")):
            chosen_url = f"http://{chosen_url}"

        ui.console.print(f"[dim]⠋ Testing connection to {chosen_url}...[/dim]")
        test_client = SafiClient(chosen_url)
        discovered = discover_agents(test_client)
        if discovered:
            ui.console.print(
                f"[bold green]✓ Connected successfully![/] "
                f"[dim](Discovered {len(discovered)} agent(s): {', '.join(discovered.keys())})[/dim]"
            )
            config.save_config({"api_url": chosen_url})
            break
        else:
            ui.console.print(
                f"[bold yellow]⚠️ Could not verify connection to {chosen_url}.[/]\n"
                f"[dim]The server may be starting up, behind a firewall, or unreachable.[/dim]"
            )
            try:
                confirm = input("Save and use this endpoint anyway? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)
            if confirm in ("y", "yes"):
                config.save_config({"api_url": chosen_url})
                break

    # 2. Select Default Agent
    ui.console.print("\n[bold white]2. Primary Agent[/]")
    ui.console.print("[dim]Select the primary agent for your workflows:[/dim]")

    agent_options = [
        ("sysadmin", "Sysadmin Agent", "Infrastructure, server maintenance, Active Directory, network"),
        ("software_engineer", "Software Engineer Agent", "Codebase engineering, refactoring, tests, git"),
    ]
    existing_keys = {opt[0] for opt in agent_options}
    for k, v in AVAILABLE_AGENTS.items():
        if k not in existing_keys:
            agent_options.append((k, v.get("title", k), v.get("description", "")))

    for idx, (k, title, desc) in enumerate(agent_options, 1):
        ui.console.print(f"  [bold cyan][{idx}][/] [bold white]{title}[/] [dim]({k})[/]\n      [dim]{desc}[/dim]")

    chosen_agent = "sysadmin"
    while True:
        try:
            choice = input(f"Select Agent [1-{len(agent_options)}, default 1]: ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        if not choice:
            chosen_agent = agent_options[0][0]
            break
        if choice.isdigit() and 1 <= int(choice) <= len(agent_options):
            chosen_agent = agent_options[int(choice) - 1][0]
            break
        matching = [opt[0] for opt in agent_options if choice.lower() in opt[0] or choice.lower() in opt[1].lower()]
        if matching:
            chosen_agent = matching[0]
            break
        ui.console.print("[yellow]Invalid choice, please select a valid number or agent name.[/]")

    config.set_default_agent(chosen_agent)
    agent_title = AVAILABLE_AGENTS.get(chosen_agent, {}).get("title", chosen_agent)
    ui.console.print(f"[bold green]✓ Selected primary agent: {agent_title} ({chosen_agent})[/]")

    # 3. Policy API Key for Chosen Agent
    ui.console.print(f"\n[bold white]3. Policy API Key for '{agent_title}'[/]")
    existing_key = config.resolve_agent_api_key(chosen_agent)
    if existing_key:
        ui.console.print(f"[bold green]✓ Found existing Policy API key for '{chosen_agent}' in config.[/]")
        key_val = existing_key
    else:
        ui.console.print(
            "[dim]Each agent is governed by its own domain policy and requires its own Policy API Key.\n"
            "You can generate one in the SAFi Governance Portal (Settings → API Keys).[/dim]"
        )
        try:
            key_val = input(f"Enter Policy API Key (sk-safi-...) [press Enter to skip for now]: ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        if key_val:
            config.save_agent_api_key(chosen_agent, key_val)
            ui.console.print(f"[bold green]✓ Saved Policy API Key for {chosen_agent} to {config.CONFIG_FILE}[/]")
        else:
            ui.console.print(f"[yellow]Skipped for now. You will be prompted when launching '{chosen_agent}'.[/]")

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


