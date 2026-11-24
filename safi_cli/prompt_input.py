from __future__ import annotations

import math
import os
import re
import shutil
import sys
import time
from typing import Callable, List, Optional


from . import ui

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.filters import is_done, to_filter
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    _HAS_PROMPT_TOOLKIT = True
    _CompleterBase = Completer
    _SessionBase = PromptSession
except Exception:
    _HAS_PROMPT_TOOLKIT = False

    class _CompleterBase:
        pass

    class _SessionBase:
        pass

    class FileHistory:

        def __init__(self, filename: str) -> None:
            self.filename = filename

    class InMemoryHistory:
        pass

try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None


CompletionsFn = Callable[[str, str], List[str]]


def using_prompt_toolkit() -> bool:
    return _HAS_PROMPT_TOOLKIT and sys.stdin.isatty()


def collect_multiline(initial: str) -> str:
    parts = [initial]
    while parts[-1].rstrip().endswith("\\"):
        parts[-1] = parts[-1].rstrip()[:-1]
        try:
            cont = input("    ")
        except (KeyboardInterrupt, EOFError):
            break
        parts.append(cont)
    return "\n".join(parts)


def wakeup_prompt_session() -> bool:
    try:
        app = getattr(_SESSION, "app", None) if _SESSION is not None else None
        if app is None:
            from prompt_toolkit.application.current import get_app
            app = get_app()
        if app and app.is_running:
            draft = ""
            try:
                if hasattr(app, "current_buffer") and app.current_buffer:
                    draft = app.current_buffer.text or ""
            except Exception:
                pass

            def _do_exit() -> None:
                try:
                    if app.is_running:
                        app.exit(result=("__QUEUED_WAKEUP__", draft))
                except Exception:
                    pass

            loop = getattr(app, "loop", None)
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(_do_exit)
            else:
                _do_exit()
            return True
    except Exception:
        pass
    return False


def read_prompt(
    agent_label: str,
    completions_fn: Optional[CompletionsFn] = None,
    history_path: Optional[str] = None,
    default: str = "",
) -> Optional[Any]:
    if using_prompt_toolkit():
        return _read_prompt_toolkit(agent_label, completions_fn, history_path, default=default)
    return _read_prompt_readline(agent_label)


_SESSION = None
_SESSION_HISTORY: Optional[str] = None
_SESSION_COMPLETER_FN: Optional[CompletionsFn] = None
_KEY_BINDINGS = None
_STYLE = None


def _get_divider(cols: Optional[int] = None) -> str:
    if cols is None:
        cols = _terminal_columns()
    return "─" * max(20, cols)


def _terminal_columns() -> int:
    try:
        from prompt_toolkit.application import get_app

        app = get_app()
        if app is not None and app.is_running:
            out_cols = app.output.get_size().columns
            if out_cols and out_cols > 0:
                return out_cols
    except Exception:
        pass
    try:
        return os.get_terminal_size(sys.__stdout__.fileno()).columns
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return os.get_terminal_size().columns
    except (OSError, ValueError):
        return shutil.get_terminal_size((80, 24)).columns


def _prompt_style():
    global _STYLE
    if _STYLE is None:
        _STYLE = Style.from_dict({
            "safi-divider": ui.COLOR_PROMPT_DIVIDER,
            "safi-badge": f"{ui.COLOR_PROMPT_BRAND} bold",
            "safi-agent": ui.COLOR_PROMPT_AGENT,
            "safi-arrow": f"{ui.COLOR_PROMPT_CHEVRON} bold",
            "safi-scheduled": "bold #38bdf8",
            "safi-queued": "bold #34d399",
            "safi-dim": "#64748b",
            "safi-spinner": f"bold {ui.COLOR_BRAND_400}",
            "safi-step": "#94a3b8" if not ui.IS_LIGHT_THEME else "#475569",
            "": "",
            "auto-suggest": f"{ui.COLOR_PROMPT_AGENT} italic",
            "bottom-toolbar": f"noinherit {ui.COLOR_PROMPT_DIVIDER}",
            "completion-menu": (
                "bg:#e2e8f0 #1e293b" if ui.IS_LIGHT_THEME
                else "bg:#1e293b #f8fafc"
            ),
            "completion-menu.completion": (
                "bg:#e2e8f0 #334155" if ui.IS_LIGHT_THEME
                else "bg:#1e293b #cbd5e1"
            ),
            "completion-menu.completion.current": (
                "bg:#cbd5e1 #0f172a bold" if ui.IS_LIGHT_THEME
                else "bg:#334155 #38bdf8 bold"
            ),
            "completion-menu.meta": (
                "bg:#f1f5f9 #475569" if ui.IS_LIGHT_THEME
                else "bg:#0f172a #94a3b8"
            ),
            "scrollbar.background": (
                "bg:#cbd5e1" if ui.IS_LIGHT_THEME else "bg:#1e293b"
            ),
            "scrollbar.button": (
                "bg:#94a3b8" if ui.IS_LIGHT_THEME else "bg:#475569"
            ),
        })
    return _STYLE


def _prompt_key_bindings():
    global _KEY_BINDINGS
    if _KEY_BINDINGS is not None:
        return _KEY_BINDINGS

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        buf = event.current_buffer
        if buf.text.count("```") % 2 == 1:
            buf.insert_text("\n")
            return
        buf.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline_alt(event):
        event.current_buffer.insert_text("\n")

    @kb.add("c-j")
    def _newline_ctrl_j(event):
        event.current_buffer.insert_text("\n")

    _KEY_BINDINGS = kb
    return kb


_SPINNER_FRAMES = ["❃", "✿", "❀", "❁", "❈", "❉"]


def _get_spinner_char() -> str:
    frame_idx = int(time.time() / 0.15) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[frame_idx]


def _top_divider_fragments(cols: int) -> List[tuple[str, str]]:
    return [("class:safi-divider", _get_divider(cols) + "\n")]


def _prompt_text(agent_label: str) -> "FormattedText":
    margin = " " * int(os.environ.get("SAFI_CLI_MARGIN", "2") or "2")
    agent = agent_label or "software_engineer"
    cols = _terminal_columns()

    fragments: List[tuple[str, str]] = [("", "\n")]

    try:
        from . import scheduler
        if scheduler.is_agent_busy():
            spinner_char = _get_spinner_char()
            status_desc = scheduler.get_agent_status_text() or "Running"
            elapsed = scheduler.get_agent_elapsed_time()
            elapsed_str = f" • {elapsed:.1f}s" if elapsed is not None else ""

            fragments.extend([
                ("", margin),
                ("class:safi-spinner", f"{spinner_char} "),
                ("class:safi-badge", "SAFi "),
                ("class:safi-dim", "• "),
                ("class:safi-step", f"{status_desc}"),
                ("class:safi-dim", f"{elapsed_str}\n\n"),
            ])
    except Exception:
        pass

    fragments.extend(_top_divider_fragments(cols))
    fragments.extend([
        ("", margin),
        ("class:safi-badge", "SAFi "),
        ("class:safi-agent", f"[{agent}] "),
        ("class:safi-arrow", "› "),
    ])
    return FormattedText(fragments)


def _bottom_divider_text() -> "FormattedText":
    cols = _terminal_columns()
    divider = _get_divider(cols)
    margin = " " * int(os.environ.get("SAFI_CLI_MARGIN", "2") or "2")
    try:
        from . import scheduler
        sched = scheduler.get_scheduler()
        is_busy = scheduler.is_agent_busy()
        active_tasks = sched.list_active_tasks()
        prompt_q = scheduler.get_prompt_queue()
        queued_items = prompt_q.peek_all() if prompt_q else []

        if is_busy or active_tasks or queued_items:
            right_parts: List[tuple[str, str]] = []
            right_len = 0

            if is_busy:
                if active_tasks:
                    s_tasks = f"⏱ {len(active_tasks)} Scheduled • "
                    right_parts.append(("class:safi-scheduled", s_tasks))
                    right_len += len(s_tasks)

                s_abort = "(Ctrl+C to abort)"
                if cols < 50:
                    s_abort = "(Ctrl+C)"
                right_parts.append(("class:safi-dim", s_abort))
                right_len += len(s_abort)
            elif active_tasks:
                next_task = active_tasks[0]
                rem = scheduler.format_remaining_time(next_task.remaining_seconds)
                lbl = next_task.label
                if len(lbl) > 16:
                    lbl = lbl[:13] + "..."
                s_label = f"⏱ {len(active_tasks)} Scheduled"
                s_detail = f" (next: '{lbl}' in {rem}) • /tasks"
                right_parts.extend([
                    ("class:safi-scheduled", s_label),
                    ("class:safi-dim", s_detail),
                ])
                right_len += len(s_label) + len(s_detail)
            elif queued_items:
                s_q_hint = "/queue"
                right_parts.append(("class:safi-dim", s_q_hint))
                right_len += len(s_q_hint)

            left_parts: List[tuple[str, str]] = []
            left_len = 0

            if queued_items:
                first_item = queued_items[0]
                prompt_raw = first_item.prompt.replace("\n", " ").strip()
                count = len(queued_items)

                q_prefix = "⏳ Queued: " if count == 1 else f"⏳ Queued ({count}): "
                q_suffix = f" (+{count - 1} more)" if count > 1 else ""

                fixed_len = len(margin) + len(q_prefix) + len(q_suffix) + 2
                avail_prompt = max(4, cols - right_len - fixed_len - 3)

                if len(prompt_raw) > avail_prompt:
                    prompt_preview = prompt_raw[: max(3, avail_prompt - 3)].rstrip() + "..."
                else:
                    prompt_preview = prompt_raw

                left_parts.append(("", margin))
                left_parts.append(("class:safi-queued", q_prefix))
                left_parts.append(("class:safi-step", f'"{prompt_preview}"'))
                if q_suffix:
                    left_parts.append(("class:safi-dim", q_suffix))

                left_len = len(margin) + len(q_prefix) + len(prompt_preview) + 2 + len(q_suffix)

            gap = max(1, cols - left_len - right_len - 2)
            if not left_parts:
                gap = max(0, cols - right_len - 2)

            fragments: List[tuple[str, str]] = [
                ("class:safi-divider", divider + "\n"),
            ]
            fragments.extend(left_parts)
            fragments.append(("", " " * gap))
            fragments.extend(right_parts)
            return FormattedText(fragments)
    except Exception:
        pass

    return FormattedText([("class:safi-divider", divider)])


_bottom_toolbar = _bottom_divider_text


class SafiPromptSession(_SessionBase):

    def _create_layout(self) -> "Layout":
        layout = super()._create_layout()
        bottom_divider_window = ConditionalContainer(
            Window(
                FormattedTextControl(_bottom_divider_text),
                dont_extend_height=True,
            ),
            filter=~is_done,
        )
        for container in (
            getattr(layout.container.children[0], "alternative_content", None),
            getattr(layout.container.children[0], "content", None),
        ):
            if container is None:
                continue
            hsplit = getattr(container, "content", container)
            if hasattr(hsplit, "children") and len(hsplit.children) > 1:
                buf_win = getattr(hsplit.children[1], "content", hsplit.children[1])
                if hasattr(buf_win, "dont_extend_height"):
                    buf_win.dont_extend_height = to_filter(True)
                hsplit.children.insert(2, bottom_divider_window)
                break
        return layout


def _continuation(width: int, line_number: int, is_soft_wrap: bool) -> "FormattedText":
    return FormattedText([("", " " * width)])


class _CallbackCompleter(_CompleterBase):

    def __init__(self, fn: CompletionsFn):
        self._fn = fn

    def get_completions(self, document, complete_event):
        text = document.get_word_before_cursor(WORD=True)
        line = document.text_before_cursor
        try:
            matches = self._fn(line, text) or []
        except Exception:
            matches = []
        for match in matches:
            yield Completion(match, start_position=-len(text))


class _TrimmingHistory(FileHistory):

    TRIM_INTERVAL = 500
    MAX_ENTRIES = 1000

    def __init__(self, filename: str):
        super().__init__(filename)
        self._appends_since_trim = 0

    def append_string(self, line: str) -> None:
        super().append_string(line)
        self._appends_since_trim += 1
        if self._appends_since_trim >= self.TRIM_INTERVAL:
            self._appends_since_trim = 0
            self._trim()

    def _trim(self) -> None:
        import tempfile

        try:
            entries = list(self.load_history_strings())
        except Exception:
            return
        trimmed = _TrimmingHistory._drop_consecutive_dupes(entries)[: self.MAX_ENTRIES]
        oldest_first = list(reversed(trimmed))
        try:
            dirname = os.path.dirname(os.path.abspath(self.filename)) or "."
            os.makedirs(dirname, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix=".history-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for entry in oldest_first:
                        fh.write("\n# trimmed\n")
                        for line in entry.split("\n"):
                            fh.write("+" + line + "\n")
                os.replace(tmp_path, self.filename)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass

    @staticmethod
    def _drop_consecutive_dupes(entries: List[str]) -> List[str]:
        out: List[str] = []
        for entry in entries:
            if not out or out[-1] != entry:
                out.append(entry)
        return out


def _get_session(history_path: Optional[str]):
    global _SESSION, _SESSION_HISTORY, _SESSION_COMPLETER_FN
    if _SESSION is not None and _SESSION_HISTORY == history_path:
        return _SESSION
    history = _TrimmingHistory(history_path) if history_path else InMemoryHistory()
    _SESSION = SafiPromptSession(
        history=history,
        key_bindings=_prompt_key_bindings(),
        style=_prompt_style(),
        multiline=True,
        complete_while_typing=False,
        auto_suggest=AutoSuggestFromHistory(),
        prompt_continuation=_continuation,
        erase_when_done=True,
    )
    _SESSION_HISTORY = history_path
    _SESSION_COMPLETER_FN = None
    return _SESSION


def _read_prompt_toolkit(
    agent_label: str,
    completions_fn: Optional[CompletionsFn],
    history_path: Optional[str],
    default: str = "",
) -> Optional[Any]:
    global _SESSION_COMPLETER_FN
    session = _get_session(history_path)
    if completions_fn is not _SESSION_COMPLETER_FN:
        session.completer = _CallbackCompleter(completions_fn) if completions_fn else None
        _SESSION_COMPLETER_FN = completions_fn
    try:
        with patch_stdout(raw=True):
            return session.prompt(
                lambda: _prompt_text(agent_label),
                default=default,
                refresh_interval=0.15,
            )
    except EOFError:
        return None


def _read_prompt_readline(agent_label: str) -> Optional[str]:
    if readline:
        try:
            readline.parse_and_bind("set enable-bracketed-paste on")
        except Exception:
            pass
    try:
        first = input(ui.get_input_prompt(agent=agent_label))
    except EOFError:
        return None
    return collect_multiline(first)
