from __future__ import annotations

from datetime import datetime
import difflib
import os
import re
import shutil
import sys
import threading
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
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("", "0", "false", "no", "off")


CLI_MARGIN = int(os.environ.get("SAFI_CLI_MARGIN", "2"))
_NON_BLOCKING_MODE = False
_INTERACTIVE_LOCK = threading.Lock()
_INTERACTIVE_REQUESTED = threading.Event()
_INTERACTIVE_READY = threading.Event()
_INTERACTIVE_DONE = threading.Event()


def set_non_blocking_mode(enabled: bool) -> None:
    global _NON_BLOCKING_MODE
    _NON_BLOCKING_MODE = enabled
    if not enabled:
        _INTERACTIVE_REQUESTED.clear()
        _INTERACTIVE_READY.set()
        _INTERACTIVE_DONE.set()


def service_pending_interactive_prompt() -> None:
    if _INTERACTIVE_REQUESTED.is_set():
        _INTERACTIVE_READY.set()
        _INTERACTIVE_DONE.wait()


def _run_with_terminal_input(fn):
    if not _NON_BLOCKING_MODE:
        return fn()
    from . import prompt_input
    if not prompt_input.using_prompt_toolkit():
        return fn()
    with _INTERACTIVE_LOCK:
        if not _NON_BLOCKING_MODE:
            return fn()
        _INTERACTIVE_READY.clear()
        _INTERACTIVE_DONE.clear()
        _INTERACTIVE_REQUESTED.set()
        prompt_input.wakeup_prompt_session()
        _INTERACTIVE_READY.wait(timeout=5.0)
        try:
            return fn()
        finally:
            _INTERACTIVE_REQUESTED.clear()
            _INTERACTIVE_DONE.set()


_UNICODE_SPACE_TRANS = str.maketrans({
    "\u00a0": " ",
    "\u202f": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",
    "\u200a": " ",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": " - ",
})


def _sanitize_terminal_text(text: str) -> str:
    if not text:
        return text
    return text.translate(_UNICODE_SPACE_TRANS)


class MarginedConsole(Console):

    def print(self, *objects, **kwargs):
        pad_margin = kwargs.pop("pad_margin", True)
        interactive = getattr(self, "is_terminal", False)

        norm_objects = []
        is_light = globals().get("IS_LIGHT_THEME", False)
        is_legacy_ps = globals().get("_IS_LEGACY_POWERSHELL", False)
        for obj in objects:
            if isinstance(obj, str):
                s = _sanitize_terminal_text(obj)
                if is_light:
                    if "[bold white]" in s:
                        s = s.replace("[bold white]", "[bold #0f172a]").replace("[/bold white]", "[/bold #0f172a]")
                    if "[white]" in s:
                        s = s.replace("[white]", "[#0f172a]").replace("[/white]", "[/#0f172a]")
                elif is_legacy_ps and "[dim]" in s:
                    s = s.replace("[dim]", "[#cbd5e1]").replace("[/dim]", "[/#cbd5e1]")
                norm_objects.append(s)
            else:
                norm_objects.append(obj)
        objects = tuple(norm_objects)

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

    def status(self, status, *args, **kwargs):
        if _NON_BLOCKING_MODE:
            from . import scheduler
            class NonBlockingStatus:
                def __init__(self, initial_status):
                    self.current_step = ""
                    self.update(initial_status)

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_val, exc_tb):
                    scheduler.set_agent_status_text("")

                def start(self):
                    pass

                def stop(self):
                    scheduler.set_agent_status_text("")

                def update(self, status_markup, **kw):
                    if not status_markup:
                        return
                    try:
                        from rich.text import Text
                        plain = Text.from_markup(str(status_markup)).plain.strip()
                    except Exception:
                        plain = re.sub(r"\[.*?\]", "", str(status_markup)).strip()

                    clean = re.sub(r"\s*[·•]\s*\d+(\.\d+)?s\s*$", "", plain).strip()
                    clean = re.sub(r"^(SAFi\s*[·•]\s*|[•·\s]+)", "", clean).strip()
                    if clean.lower().startswith("thinking with "):
                        clean = "Running with " + clean[14:]
                    elif clean.lower() == "thinking":
                        clean = "Running"
                    step_name = clean or "Running"
                    self.current_step = step_name
                    scheduler.set_agent_status_text(step_name)

            return NonBlockingStatus(status)
        return super().status(status, *args, **kwargs)


console = MarginedConsole()

def _query_terminal_bg(timeout: float = 0.15) -> Optional[str]:
    import select
    import sys

    try:
        import termios
    except ImportError:
        return None

    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError, AttributeError):
        return None
    if not os.isatty(fd):
        return None
    try:
        old_attrs = termios.tcgetattr(fd)
    except termios.error:
        return None
    try:
        import tty as _tty
        _tty.setraw(fd)
        sys.stdout.write("\033]11;?\033\\")
        sys.stdout.flush()
        reply = ""
        while len(reply) < 40:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                break
            ch = os.read(fd, 1).decode("utf-8", "ignore")
            reply += ch
            if ch in ("\\", "\x07"):
                break
        match = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", reply)
        return match.group(0) if match else None
    except Exception:
        return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except termios.error:
            pass


def _detect_light_background() -> bool:
    theme = (os.environ.get("SAFI_CLI_THEME") or "").strip().lower()
    if theme in ("light", "dark"):
        return theme == "light"

    bg = _query_terminal_bg()
    if bg:
        parts = re.findall(r"([0-9a-fA-F]+)", bg.split(":", 1)[1])
        if len(parts) == 3:
            r, g, b = (int(part, 16) for part in parts)
            scale = float((16 ** max(len(part) for part in parts)) - 1)
            luminance = (0.2126 * r / scale) + (0.7152 * g / scale) + (0.0722 * b / scale)
            return luminance > 0.5

    colorfgbg = (os.environ.get("COLORFGBG") or "").split(";")
    if colorfgbg and colorfgbg[-1].isdigit():
        bg_code = int(colorfgbg[-1])
        if bg_code in (7, 15) or (bg_code >= 231 and bg_code <= 255 and bg_code not in (234, 235, 236, 237, 238, 239)):
            return True
        return False
    return False


IS_LIGHT_THEME = _detect_light_background()
_IS_LEGACY_POWERSHELL = bool(
    os.environ.get("WSL_DISTRO_NAME")
    and not os.environ.get("WT_SESSION")
    and not IS_LIGHT_THEME
)

if IS_LIGHT_THEME:
    _PALETTE = {
        "COLOR_BRAND_600": "#15803d",
        "COLOR_BRAND_500": "#16a34a",
        "COLOR_BRAND_400": "#16a34a",
        "COLOR_BRAND_700": "#14532d",
        "COLOR_PASS": "#15803d",
        "COLOR_WARN": "#a16207",
        "COLOR_FAIL": "#dc2626",
        "COLOR_PENDING": "#525252",
        "COLOR_MUTED": "#525252",
        "COLOR_BORDER": "#a1a1aa",
        "COLOR_USER_ACCENT": "#0369a1",
        "COLOR_USER_BORDER": "#1d4ed8",
        "COLOR_USER_BG": "#eff6ff",
        "COLOR_USER_BADGE_BG": "#dbeafe",
        "COLOR_PROMPT_DIVIDER": "#64748b",
        "COLOR_PROMPT_BRAND": "#15803d",
        "COLOR_PROMPT_AGENT": "#334155",
        "COLOR_PROMPT_CHEVRON": "#0284c7",
        "COLOR_PROMPT_TEXT": "#1e293b",
    }
    _DEFAULT_USER_BG = "#eff6ff"
    from rich.theme import Theme as _RichTheme
    console.push_theme(_RichTheme({
        "markdown.code": "bold #0369a1 on default",
        "markdown.code_block": "#0f172a on default",
        "markdown.h1": "bold #15803d",
        "markdown.h2": "bold #0f172a",
        "markdown.h3": "bold #1e293b",
        "markdown.link": "underline #0369a1 on default",
        "markdown.link_url": "underline #0369a1 on default",
        "markdown.item.bullet": "bold #15803d",
        "markdown.block_quote": "#475569",
        "repr.url": "underline #0369a1 on default",
        "repr.path": "#0369a1 on default",
        "repr.filename": "bold #0369a1 on default",
        "bold white": "bold #0f172a",
        "white": "#0f172a",
    }))
else:
    _PALETTE = {
        "COLOR_BRAND_600": "#16a34a",
        "COLOR_BRAND_500": "#22c55e",
        "COLOR_BRAND_400": "#4ade80",
        "COLOR_BRAND_700": "#15803d",
        "COLOR_PASS": "#22c55e",
        "COLOR_WARN": "#eab308",
        "COLOR_FAIL": "#ef4444",
        "COLOR_PENDING": "#e2e8f0" if _IS_LEGACY_POWERSHELL else "#a3a3a3",
        "COLOR_MUTED": "#cbd5e1" if _IS_LEGACY_POWERSHELL else "#737373",
        "COLOR_BORDER": "#64748b" if _IS_LEGACY_POWERSHELL else "#27272a",
        "COLOR_USER_ACCENT": "#38bdf8",
        "COLOR_USER_BORDER": "#2563eb",
        "COLOR_USER_BADGE_BG": "#1e3a5f",
        "COLOR_PROMPT_DIVIDER": "#64748b" if _IS_LEGACY_POWERSHELL else "#334155",
        "COLOR_PROMPT_BRAND": "#4ade80",
        "COLOR_PROMPT_AGENT": "#e2e8f0" if _IS_LEGACY_POWERSHELL else "#94a3b8",
        "COLOR_PROMPT_CHEVRON": "#38bdf8",
        "COLOR_PROMPT_TEXT": "#f8fafc",
    }
    from rich.theme import Theme as _RichTheme
    console.push_theme(_RichTheme({
        "markdown.code": "bold cyan on default",
        "markdown.code_block": "cyan on default",
        "markdown.h1": "bold #4ade80",
        "markdown.h2": "bold #f8fafc",
        "markdown.h3": "bold #e2e8f0",
        "markdown.h4": "bold #cbd5e1",
    }))

COLOR_BRAND_600 = _PALETTE["COLOR_BRAND_600"]
COLOR_BRAND_500 = _PALETTE["COLOR_BRAND_500"]
COLOR_BRAND_400 = _PALETTE["COLOR_BRAND_400"]
COLOR_BRAND_700 = _PALETTE["COLOR_BRAND_700"]

COLOR_PASS = _PALETTE["COLOR_PASS"]
COLOR_WARN = _PALETTE["COLOR_WARN"]
COLOR_FAIL = _PALETTE["COLOR_FAIL"]
COLOR_PENDING = _PALETTE["COLOR_PENDING"]
COLOR_MUTED = _PALETTE["COLOR_MUTED"]
COLOR_BORDER = _PALETTE["COLOR_BORDER"]

COLOR_PROMPT_DIVIDER = _PALETTE["COLOR_PROMPT_DIVIDER"]
COLOR_PROMPT_BRAND = _PALETTE["COLOR_PROMPT_BRAND"]
COLOR_PROMPT_AGENT = _PALETTE["COLOR_PROMPT_AGENT"]
COLOR_PROMPT_CHEVRON = _PALETTE["COLOR_PROMPT_CHEVRON"]
COLOR_PROMPT_TEXT = _PALETTE["COLOR_PROMPT_TEXT"]

SYNTAX_THEME = "ansi_light" if IS_LIGHT_THEME else "ansi_dark"


def _syntax(code: str, lexer: str, **kwargs) -> "Syntax":
    kwargs.setdefault("theme", SYNTAX_THEME)
    kwargs.setdefault("background_color", "default")
    pad = kwargs.get("padding", (0, 1))
    try:
        kwargs["padding"] = (1, pad[1] if len(pad) > 1 else pad[0])
    except TypeError:
        kwargs["padding"] = (1, 1)
    return Syntax(code, lexer, **kwargs)

COLOR_USER_ACCENT = _PALETTE["COLOR_USER_ACCENT"]
COLOR_USER_BORDER = _PALETTE["COLOR_USER_BORDER"]
COLOR_USER_BG = os.environ.get("SAFI_CLI_USER_BG") or _PALETTE.get("COLOR_USER_BG", "#1e293b")
COLOR_USER_BADGE_BG = _PALETTE["COLOR_USER_BADGE_BG"]

SHOW_AUDIT_PANEL = _env_flag("SAFI_CLI_SHOW_AUDIT", True)


def set_show_audit_panel(flag: bool) -> None:
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
    clean_step = step_text.rstrip(".…").strip()
    if not clean_step or clean_step.lower() in ("governing turn", "analyzing your request"):
        return
    step_line = Text("  ")
    step_line.append("✔ ", style=f"bold {COLOR_PASS}")
    step_line.append(clean_step, style="dim")
    step_line.append(f" ({elapsed:.1f}s)", style="dim")
    console.print(step_line)


def build_progress_line(
    progress_codes: Optional[List[str]],
    latest_step: Optional[str],
    elapsed: float,
    model: Optional[str] = None,
) -> str:
    codes = [c for c in dict.fromkeys(progress_codes or []) if c in PROGRESS_STAGES]

    step = (latest_step or "").rstrip(".…").strip()
    step_lower = step.lower()
    if step_lower.startswith(("drafting", "thinking", "running")):
        label = f"Running with {model}" if model else "Running"
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
        f"[bold {COLOR_BRAND_400}]SAFi[/] [dim]·[/] {escape(label)} "
        f"[dim]·[/] [dim]{elapsed:.1f}s[/]"
    )


def build_tool_status_line(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    elapsed: float,
    latest_output: Optional[str] = None,
) -> str:
    args = args or {}
    if tool_name == "bash":
        raw_cmd = (args.get("command") or "").strip()
        first_line = raw_cmd.splitlines()[0] if raw_cmd else ""
        if "sys-exec" in first_line:
            parts = first_line.split()
            if len(parts) >= 2 and parts[0] == "sys-exec":
                label = f"Running sys-exec: {parts[1]}"
            else:
                label = "Running sys-exec"
        elif len(first_line) > 50:
            label = f"Running bash: {first_line[:47].rstrip()}…"
        else:
            label = f"Running bash: {first_line}" if first_line else "Running bash command"
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
    elif tool_name == "m365_admin":
        action = args.get("action") or ""
        label = f"M365 Admin: {action.replace('_', ' ')}" if action else "Executing M365 action"
    elif tool_name == "azure_admin":
        action = args.get("action") or ""
        label = f"Azure Admin: {action.replace('_', ' ')}" if action else "Executing Azure action"
    elif tool_name == "cloud_status":
        label = "Checking cloud environment status"
    else:
        label = f"Executing {tool_name}"

    clean_out = ""
    if latest_output:
        clean_out = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", latest_output).strip()
        clean_out = " ".join(clean_out.split())

    term_width = console.width or 120
    available_budget = max(term_width - 24, 20)

    if clean_out:
        label_len = len(label)
        if label_len + len(clean_out) + 3 > available_budget:
            max_label = min(label_len, max(15, available_budget // 3))
            if label_len > max_label:
                label = label[: max_label - 1].rstrip() + "…"
            remaining_for_out = max(10, available_budget - len(label) - 3)
            if len(clean_out) > remaining_for_out:
                clean_out = clean_out[: remaining_for_out - 1].rstrip() + "…"

        return (
            f"[bold {COLOR_BRAND_400}]SAFi[/] [dim]·[/] {escape(label)} "
            f"[dim]·[/] [dim]{escape(clean_out)}[/] [dim]·[/] [dim]{elapsed:.1f}s[/]"
        )

    if len(label) > available_budget:
        label = label[: available_budget - 1].rstrip() + "…"

    return (
        f"[bold {COLOR_BRAND_400}]SAFi[/] [dim]·[/] {escape(label)} "
        f"[dim]·[/] [dim]{elapsed:.1f}s[/]"
    )


def clear_live_status_tail(last_status_markup: Optional[str] = None) -> None:
    if _NON_BLOCKING_MODE or not getattr(console, "is_terminal", False):
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
    header_text = Text()
    header_text.append("SAFi", style=f"bold {COLOR_BRAND_400}")
    header_text.append(" (The Self-alignment Framework Interface)", style="bold")
    header_text.append("\n")
    header_text.append("      The governance gateway for AI agents", style="dim")

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column("label", style="dim", justify="right")
    info_table.add_column("val", style="bold")

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
    if not prompt or not prompt.strip():
        return

    table = Table.grid(padding=(0, 0))
    table.add_column(width=4, no_wrap=True)
    table.add_column()
    table.add_row(
        Text(">   ", style=f"bold {COLOR_BRAND_400}"),
        Text(prompt.strip(), style=f"bold {COLOR_USER_ACCENT}"),
    )

    console.print()
    try:
        console.print(table, pad_margin=False)
    except TypeError:
        console.print(table)
    console.print()


def get_input_prompt(agent: Optional[str] = None, user_name: Optional[str] = None) -> str:
    agent_label = agent or "software_engineer"
    margin = " " * CLI_MARGIN if CLI_MARGIN > 0 else ""
    try:
        cols = os.get_terminal_size(sys.__stdout__.fileno()).columns
    except (OSError, ValueError, AttributeError):
        cols = shutil.get_terminal_size((80, 24)).columns
    divider = "─" * max(20, cols)
    def _rgb(hex_color: str) -> str:
        h = hex_color.lstrip("#")
        return f"{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}"

    return (
        f"\n\001\033[38;2;{_rgb(COLOR_PROMPT_DIVIDER)}m\002{divider}\001\033[0m\n"
        f"{margin}\001\033[38;2;{_rgb(COLOR_PROMPT_BRAND)}m\033[1m\002SAFi \001\033[0m"
        f"\033[38;2;{_rgb(COLOR_PROMPT_AGENT)}m\002[{agent_label}] \001\033[0m"
        f"\033[38;2;{_rgb(COLOR_PROMPT_CHEVRON)}m\033[1m\002› \001\033[0m\033[38;2;{_rgb(COLOR_PROMPT_TEXT)}m\002"
    )


_active_todos: List[Dict[str, Any]] = []


def get_active_todos() -> List[Dict[str, Any]]:
    return list(_active_todos)


def set_active_todos(todos: List[Dict[str, Any]]) -> None:
    global _active_todos
    _active_todos = list(todos) if todos else []


def clear_active_todos() -> None:
    global _active_todos
    _active_todos = []


def mark_active_todos_completed() -> None:
    global _active_todos
    if not _active_todos:
        return
    for item in _active_todos:
        status = (item.get("status") or "").lower()
        if status in ("pending", "in_progress", "running"):
            item["status"] = "completed"


def advance_active_todo(tool_name: str, args: Dict[str, Any], is_success: bool = True) -> None:
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
    global _active_todos
    if _active_todos and all((t.get("status") or "").lower() in ("completed", "done") for t in _active_todos):
        _active_todos = []


_SCRATCHPAD_CHECKBOX_RE = re.compile(
    r"^\s*(?:[-*+]|\d+\.)?\s*\[(?P<mark>[ xX>~!\-])\]\s+(?P<task>.+?)\s*$"
)


def parse_scratchpad_todos(text: str) -> List[Dict[str, Any]]:
    todos: List[Dict[str, Any]] = []
    for idx, line in enumerate((text or "").splitlines(), start=1):
        m = _SCRATCHPAD_CHECKBOX_RE.match(line)
        if not m:
            continue
        mark = m.group("mark").lower()
        task = m.group("task").strip()
        if not task:
            continue
        if mark == "x":
            status = "completed"
        elif mark in (">", "~", "-"):
            status = "in_progress"
        elif mark == "!":
            status = "failed"
        else:
            status = "pending"
        todos.append({"id": str(len(todos) + 1), "task": task, "status": status})
    return todos


def sync_todos_from_scratchpad(workspace_root: Path, *, render: bool = False) -> List[Dict[str, Any]]:
    global _active_todos
    try:
        sp_path = Path(workspace_root) / ".safi" / "scratchpad.md"
        if not sp_path.is_file():
            return list(_active_todos)
        content = sp_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return list(_active_todos)

    todos = parse_scratchpad_todos(content)
    _active_todos = list(todos)
    if render and _active_todos:
        render_todo_list(_active_todos)
    return list(_active_todos)


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
    global _session_compression
    _session_compression = {
        "tokens_before": 0,
        "tokens_after": 0,
        "tokens_saved": 0,
        "reduction_pct": 0.0,
        "active_context": 0,
    }


def _record_turn_telemetry(result: Dict[str, Any]):
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

    t_intellect = Text("Model: ", style="bold")
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
        or "safi-conscience"
    )
    c_cost = _estimate_cost(effective_c_model, c_in, c_out) if (c_in or c_out) else None
    c_cost_str = f" (${c_cost:.4f})" if c_cost and c_cost >= 0.0001 else (" (<$0.0001)" if c_cost and c_cost > 0 else "")
    c_sess_cost = _session_conscience["cost"]
    c_sess_cost_str = f" (${c_sess_cost:.4f})" if c_sess_cost >= 0.0001 else (" (<$0.0001)" if c_sess_cost > 0 else "")

    t_conscience = Text("Auditor: ", style="bold")
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
        line.append(score_str, style="bold")
        if tier_label:
            line.append(f" · {tier_label}", style=f"bold {tier_color}")
    tally = []
    if passes:
        tally.append(f"{passes} ✓")
    if cautions:
        tally.append(f"{cautions} warn")
    if violations:
        tally.append(f"{violations} ✗")
    if tally:
        prefix = " · rubrics: " if score_str else "rubrics: "
        line.append(f"{prefix}{' '.join(tally)}", style="dim")
    line.append(" · for full audit type ", style="dim")
    line.append("/audit", style=f"bold {COLOR_BRAND_400}")
    line.append(" · main menu: ", style="dim")
    line.append("/", style=f"bold {COLOR_BRAND_400}")
    return line


def build_session_usage_panel() -> Panel:
    i = _session_intellect
    c = _session_conscience
    comp = _session_compression
    total_cost = i["cost"] + c["cost"]

    rows = [
        ("Model", i.get("model") or "Unknown"),
        ("Model tokens", f"{i['in']:,} in / {i['out']:,} out"),
        ("Auditor model", c.get("model") or "safi-conscience"),
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
    body.add_column("val", style="bold")
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
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result_is_error(result: str) -> bool:
    text = (result or "").strip()
    m = _EXIT_CODE_RE.match(text)
    if m:
        return m.group(1) != "0"
    return text.lower().startswith(_ERROR_PREFIXES)


def _fit(text: str, width: int) -> str:
    flat = " ".join((text or "").split())
    width = max(8, width)
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _cap_lines(text: str, limit: int = MAX_PREVIEW_LINES) -> str:
    lines = (text or "").splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n… {len(lines) - limit} more lines"


def _summarize_args(tool_name: str, args: Dict[str, Any]) -> str:
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
            line.append(f"! {val}  ", style=COLOR_WARN)
        else:
            line.append(f"✗ {val}  ", style=COLOR_FAIL)
        found = True
    return line if found else None


def _add_diff_stats_line(items: List[Any], adds: int, dels: int) -> None:
    line = Text("  Diff: ", style="dim")
    line.append(f"+{adds}", style=f"bold {COLOR_PASS}")
    line.append(" ", style="dim")
    line.append(f"-{dels}", style=f"bold {COLOR_FAIL}")
    items.append(line)


def print_tool_proposal(name: str, args: Dict[str, Any], res: Dict[str, Any]):
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
    title_line.append(f"{name}", style="bold")
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
        title_line.append("  [BLOCKED]", style=f"bold {COLOR_FAIL}")
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
        items.append(_syntax(cmd, "bash", line_numbers=False, word_wrap=True, padding=(0, 1)))
    elif name in ("edit", "write"):
        path = args.get("path", "")
        file_line = Text("  File: ", style="dim")
        file_line.append(path, style="bold")
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
            items.append(_syntax(diff_text if diff_text else replacement, "diff", word_wrap=True, padding=(0, 1)))
        else:
            code = args.get("content", "")
            preview = code[:600] + ("\n... [truncated]" if len(code) > 600 else "")
            lexer = _detect_lexer(path)
            items.append(_syntax(preview, lexer, word_wrap=True, padding=(0, 1)))
    else:
        args_str = _summarize_args(name, args)
        if len(args_str) > 120:
            args_str = args_str[:120] + "..."
        items.append(Text(f"Arguments: {args_str}", style="dim cyan"))

    console.print(Group(*items))


_APPROVAL_STATE = {"approve_all": False}


def reset_approve_all() -> None:
    _APPROVAL_STATE["approve_all"] = False


def approve_all_enabled() -> bool:
    return _APPROVAL_STATE["approve_all"]


def prompt_user_permission(name: str, args: Dict[str, Any], auto_approve: bool = False) -> bool:
    if (
        auto_approve
        or _APPROVAL_STATE["approve_all"]
        or name in ("read", "grep", "glob", "list", "git_status", "git_diff")
    ):
        return True

    def _ask() -> bool:
        margin = " " * CLI_MARGIN if CLI_MARGIN > 0 else ""
        console.print(
            f"\n{margin}[bold black on {COLOR_WARN}] ACTION CONFIRMATION [/] "
            f"[bold white]Allow executing tool [cyan]{escape(name)}[/]? "
            f"[Y/n/a (always)]:[/] ",
            end="",
        )
        try:
            choice = input().strip().lower()
            if choice in ("a", "always"):
                _APPROVAL_STATE["approve_all"] = True
                console.print(f"{margin}[dim]All future tool executions approved for this session.[/]")
                return True
            return choice in ("", "y", "yes")
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[{COLOR_WARN}]Action cancelled by user.[/]")
            return False

    return _run_with_terminal_input(_ask)


def prompt_question(question: str, options: Optional[List[str]] = None) -> str:
    card_items = [Text(f"? {question}", style="bold")]

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
    def _ask() -> str:
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

    return _run_with_terminal_input(_ask)


def build_plan_panel(todos: Optional[List[Dict[str, Any]]] = None) -> Optional[Panel]:
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

    prog_text = Text()
    prog_text.append("Progress: ", style="dim")
    prog_text.append(f"[{bar_str}] ", style=f"bold {COLOR_BRAND_400}")
    prog_text.append(f"{pct}% ", style="bold")
    prog_text.append(f"({completed}/{total} completed)\n", style="dim")
    items.append(prog_text)

    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="left", no_wrap=True)
    grid.add_column(justify="left", overflow="fold")

    for item in active:
        task_text = item.get("task") or item.get("description") or ""
        status = (item.get("status") or "pending").lower()
        if status in ("completed", "done"):
            badge = Text("  ✔", style=f"bold {COLOR_PASS}")
            text = Text(task_text, style="dim")
        elif status in ("in_progress", "running"):
            badge = Text("▶ ...", style=f"bold {COLOR_WARN}")
            text = Text(task_text, style="bold #38bdf8")
        elif status in ("failed", "error"):
            badge = Text("  ✖", style=f"bold {COLOR_FAIL}")
            text = Text(task_text, style="bold red")
        else:
            badge = Text("  ○", style="dim")
            text = Text(task_text, style="")

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
    ws_items = []

    is_approved = proposal_res.get("willDecision", "approved") in ("approve", "approved")
    title_line = Text()
    if is_approved:
        title_line.append("[✓ APPROVED] ", style=f"bold {COLOR_PASS}")
    else:
        title_line.append("[BLOCKED] ", style=f"bold {COLOR_FAIL}")
    title_line.append("-> ", style="dim")
    title_line.append(f"{tool_name}", style="bold")
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
        ws_items.append(_syntax(cmd, "bash", line_numbers=False, word_wrap=True, padding=(0, 1)))
    elif tool_name in ("edit", "write"):
        path = args.get("path", "")
        file_line = Text("  File: ", style="dim")
        file_line.append(path, style="bold")
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
    res_line.append(f"{tool_name}", style="bold")
    res_line.append(f": {first_line} ({line_count} line{'s' if line_count != 1 else ''})", style="dim")
    ws_items.append(res_line)

    console.print(Group(*ws_items))


def render_todo_list(todos: List[Dict[str, Any]], align_right: bool = False):
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
    if not name or name in ("todowrite", "todo_write"):
        return
    _recent_tool_results.append({"tool": name, "result": result})


def get_last_tool_result(name: Optional[str] = None) -> Optional[Dict[str, str]]:
    if name:
        for entry in reversed(_recent_tool_results):
            if entry["tool"] == name:
                return entry
        return None
    return _recent_tool_results[-1] if _recent_tool_results else None


def list_recent_tool_results() -> List[Dict[str, str]]:
    return list(_recent_tool_results)


def print_full_tool_result(name: Optional[str] = None) -> None:
    entry = get_last_tool_result(name)
    if not entry:
        if name:
            console.print(f"[{COLOR_WARN}]No recent '{escape(name)}' tool result to show.[/]")
        else:
            console.print(f"[{COLOR_WARN}]No recent tool results to show.[/]")
        return
    header = Text()
    header.append(f"Full {entry['tool']} result ", style="bold")
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
    line.append(f"{name}", style="bold")
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
    line = Text("  ")
    line.append(f"↳ [Subagent: {role}] ", style="bold #38bdf8")
    line.append(f'Delegated: "{description}"', style="dim")
    console.print(line)


def print_subagent_step(role: str, tool_name: str, args: Dict[str, Any], result: str):
    args_summary = _summarize_args(tool_name, args)

    preview = result.strip().splitlines()
    first_line = preview[0] if preview else "(done)"
    if len(first_line) > 70:
        first_line = first_line[:67] + "..."

    line = Text("    ↳ ", style="dim #38bdf8")
    line.append(f"({role}) ", style="dim")
    line.append(f"{tool_name}", style="bold")
    line.append(f"({args_summary}) -> ", style="dim")
    line.append(first_line, style="dim")
    console.print(line)


def print_subagent_done(role: str, summary: str, steps: int = 1):
    preview = summary.strip().splitlines()
    first_line = preview[0] if preview else "(synthesis complete)"
    if len(first_line) > 90:
        first_line = first_line[:87] + "..."
    line = Text("  ")
    line.append(f"↳ ✓ [Subagent: {role}] ", style=f"bold {COLOR_PASS}")
    line.append(f"Completed in {steps} step{'s' if steps != 1 else ''}: {first_line}", style="dim")
    console.print(line)


def print_final_output(text: str, res: Dict[str, Any]):
    _record_turn_telemetry(res)

    now_str = datetime.now().strftime("%H:%M:%S")
    w = console.width
    margin = CLI_MARGIN if getattr(console, "is_terminal", False) else 0
    avail = w - (margin * 2) - 6
    left_text = Text.from_markup(f"[bold {COLOR_BRAND_400}]● SAFi Response[/] ")
    right_text = Text.from_markup(f" [dim]{now_str}[/dim]")
    gap = avail - (left_text.cell_len + right_text.cell_len)

    if gap >= 2:
        top_title = Text.assemble(left_text, ("─" * gap, COLOR_BRAND_600), right_text)
        title_align = "left"
    else:
        top_title = f"[bold {COLOR_BRAND_400}]● SAFi Response[/]"
        title_align = "center"

    response_panel = Panel(
        Markdown(_sanitize_terminal_text(text), code_theme=SYNTAX_THEME),
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
    ledger = result.get("conscienceLedger") or []
    if not ledger:
        console.print(f"[{COLOR_WARN}]No governance audit ledger available for this turn.[/]")
        return

    policy_title = result.get("policyName") or result.get("policyId") or "Domain Policy"
    table = Table(title=f"Detailed Governance Audit: {policy_title}", box=box.ROUNDED, border_style=COLOR_BRAND_600)
    table.add_column("Rubric / Value", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Rationale", style="dim")

    for entry in ledger:
        val = str(entry.get("value") or "Standard")
        s_val = _safe_float(entry.get("score"))
        rationale = str(entry.get("rationale") or entry.get("reason") or "-")
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
    console.print(Panel(f"[bold {COLOR_FAIL}]Error:[/] {escape(message)}", border_style=COLOR_FAIL, box=box.ROUNDED))


def _format_agent_context_panel(context: Dict[str, Any]) -> Optional[Panel]:
    if not isinstance(context, dict):
        return None

    projects = context.get("projects") or []
    tasks = context.get("tasks") or []
    notes = context.get("notes") or []
    decisions = context.get("decisions") or []

    if not any([projects, tasks, notes, decisions]):
        return None

    elements = []

    if projects:
        p_table = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {COLOR_BRAND_400}", expand=True)
        p_table.add_column("Project", style="bold white", ratio=2)
        p_table.add_column("Objective", style="dim", ratio=4)
        p_table.add_column("Status", justify="center", ratio=1)
        for p in projects:
            p_name = escape(str(p.get("name") or "Unnamed"))
            p_obj = escape(str(p.get("objective") or p.get("notes") or ""))
            p_stat = str(p.get("status") or "active").lower()
            if p_stat in ("done", "completed"):
                stat_style = f"bold {COLOR_PASS}"
                stat_label = "✓ Done"
            elif p_stat in ("blocked", "error"):
                stat_style = f"bold {COLOR_FAIL}"
                stat_label = "✖ Blocked"
            else:
                stat_style = f"bold {COLOR_WARN}"
                stat_label = "● " + p_stat.replace("_", " ").title()
            p_table.add_row(p_name, p_obj[:90] + ("..." if len(p_obj) > 90 else ""), f"[{stat_style}]{stat_label}[/]")
        elements.append(Panel(p_table, title="[bold white]Projects[/]", border_style=COLOR_BRAND_700, box=box.ROUNDED))

    if tasks:
        t_table = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {COLOR_BRAND_400}", expand=True)
        t_table.add_column("Task", style="bold white", ratio=4)
        t_table.add_column("Project", style="dim", ratio=2)
        t_table.add_column("Status", justify="center", ratio=1)
        for t in tasks:
            t_name = escape(str(t.get("task") or "Unnamed task"))
            t_proj = escape(str(t.get("project") or "General"))
            t_stat = str(t.get("status") or "todo").lower()
            if t_stat in ("done", "completed"):
                stat_style = f"bold {COLOR_PASS}"
                stat_label = "✓ Done"
            elif t_stat in ("blocked", "failed"):
                stat_style = f"bold {COLOR_FAIL}"
                stat_label = "✖ Blocked"
            else:
                stat_style = f"bold {COLOR_WARN}"
                stat_label = "● " + t_stat.replace("_", " ").title()
            t_table.add_row(t_name[:80] + ("..." if len(t_name) > 80 else ""), t_proj, f"[{stat_style}]{stat_label}[/]")
        elements.append(Panel(t_table, title="[bold white]Active Tasks[/]", border_style=COLOR_BRAND_700, box=box.ROUNDED))

    if notes:
        n_lines = []
        for n in notes:
            n_text = escape(str(n))
            n_lines.append(f"  [bold {COLOR_BRAND_400}]•[/] {n_text}")
        elements.append(Panel("\n".join(n_lines), title="[bold white]Infrastructure & Technical Notes[/]", border_style=COLOR_BRAND_700, box=box.ROUNDED))

    if decisions:
        d_lines = []
        for d in decisions:
            if isinstance(d, dict):
                q = d.get("question") or d.get("decision") or d.get("text") or str(d)
                proj = f" [dim]({escape(str(d.get('project')))})[/dim]" if d.get('project') else ""
                d_lines.append(f"  [bold {COLOR_PASS}]✔[/] {escape(str(q))}{proj}")
            else:
                d_lines.append(f"  [bold {COLOR_PASS}]✔[/] {escape(str(d))}")
        elements.append(Panel("\n".join(d_lines), title="[bold white]Decisions & Standards[/]", border_style=COLOR_BRAND_700, box=box.ROUNDED))

    return Panel(
        Group(*elements),
        title=f"[bold {COLOR_BRAND_400}]Persistent Agent Project Context[/]",
        subtitle="[dim]Long-term state remembered across sessions[/dim]",
        border_style=COLOR_BRAND_600,
        box=box.ROUNDED,
    )


def print_compression_result(data: Dict[str, Any]):
    if not data.get("ok"):
        error_msg = data.get("error", "Unknown error during compression.")
        console.print(Panel(f"[bold {COLOR_FAIL}]Compression Error:[/] {escape(str(error_msg))}", border_style=COLOR_FAIL, box=box.ROUNDED))
        return

    agent_context = data.get("agent_context")
    summary = data.get("summary")

    if not data.get("compressed"):
        msg = data.get("message", "Conversation is already minimal (no compression needed).")
        if not summary and not agent_context:
            console.print(f"[dim]{escape(str(msg))}[/dim]")
            return

        if summary:
            console.print(Panel(
                Markdown(_sanitize_terminal_text(summary), code_theme=SYNTAX_THEME),
                title=f"[bold {COLOR_BRAND_400}]Active Session Memory Summary[/]",
                subtitle="[dim]Distilled from conversation turns[/dim]",
                border_style=COLOR_BRAND_600,
                box=box.ROUNDED,
            ))
        if agent_context:
            ctx_panel = _format_agent_context_panel(agent_context)
            if ctx_panel:
                console.print(ctx_panel)
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
            Markdown(_sanitize_terminal_text(summary_text), code_theme=SYNTAX_THEME),
            title=f"[bold {COLOR_BRAND_400}]Compacted Technical Memory[/]",
            subtitle="[dim]Anchored into session context for future turns[/dim]",
            border_style=COLOR_BRAND_700,
            box=box.ROUNDED,
        ))

    console.print(build_telemetry_panel())
