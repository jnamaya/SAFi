"""Rich interactive prompt input for the SAFi CLI.

Prefers ``prompt_toolkit`` when it is installed and the session is attached to a
TTY. That path gives true multi-line editing (Enter submits, Alt+Enter / Ctrl+J
insert a newline), bracketed paste so pasted code blocks don't submit early,
history, and inline completion.

When ``prompt_toolkit`` is unavailable (or stdin is not a TTY, e.g. piped input
or tests) it degrades to an enhanced GNU readline path: bracketed paste lets a
multi-line paste land in the buffer, and a trailing backslash continues onto the
next line. No hard dependency is introduced.
"""

from __future__ import annotations

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
        """Stub used only when prompt_toolkit is absent; never instantiated
        because _HAS_PROMPT_TOOLKIT is False (see using_prompt_toolkit)."""

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
    """Whether the rich prompt_toolkit input path is active for this session."""
    return _HAS_PROMPT_TOOLKIT and sys.stdin.isatty()


def collect_multiline(initial: str) -> str:
    """Join backslash-continued input lines so a prompt can span several lines."""
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
    """Wake up the active prompt session if a background scheduled prompt is ready."""
    try:
        from prompt_toolkit.application.current import get_app
        app = get_app()
        if app and app.is_running:
            draft = ""
            try:
                if hasattr(app, "current_buffer") and app.current_buffer:
                    draft = app.current_buffer.text or ""
            except Exception:
                pass
            app.exit(result=("__QUEUED_WAKEUP__", draft))
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
    """Read one (possibly multi-line) prompt from the user."""
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
    """Best-available terminal width, preferring prompt_toolkit's live app.

    Width sources in priority order:
    1. The running prompt_toolkit Application's output size. This is the
       *exact* width prompt_toolkit lays the prompt out with, so dividers
       built from it can never disagree with the render (the ioctl on
       sys.__stdout__ can, e.g. when pt renders through a wrapped/alternate
       output, or the width was captured before a pane resize).
    2. ioctl on the real stdout TTY (ignores stale COLUMNS).
    3. ioctl on the controlling terminal.
    4. shutil fallback (COLUMNS env, then 80).
    """
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
            # Typed text deliberately has NO explicit color: it inherits the
            # terminal's default foreground, which always contrasts with the
            # terminal's own background. Guessing (near-white on a light
            # terminal) made typed text invisible; this is detection-proof.
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
            # Unbalanced code fence: Enter continues the block instead of
            # submitting a half-finished prompt.
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


_SPINNER_FRAMES = ["✻", "✼", "✽", "✾", "❁", "❂"]


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
    try:
        from . import scheduler
        sched = scheduler.get_scheduler()
        is_busy = scheduler.is_agent_busy()
        active_tasks = sched.list_active_tasks()

        if is_busy:
            text_parts: List[tuple[str, str]] = []
            text_len = 0

            if active_tasks:
                s_tasks = f"⏱ {len(active_tasks)} Scheduled • "
                text_parts.append(("class:safi-scheduled", s_tasks))
                text_len += len(s_tasks)

            s_abort = "(Ctrl+C to abort) • /tasks"
            if cols < (text_len + len(s_abort) + 4) and text_len > 0:
                s_abort = "(Ctrl+C)"
            text_parts.append(("class:safi-dim", s_abort))
            text_len += len(s_abort)

            spaces = max(0, cols - text_len - 2)
            fragments: List[tuple[str, str]] = [
                ("class:safi-divider", divider + "\n"),
                ("", " " * spaces),
            ]
            fragments.extend(text_parts)
            return FormattedText(fragments)

        if active_tasks:
            next_task = active_tasks[0]
            rem = scheduler.format_remaining_time(next_task.remaining_seconds)
            lbl = next_task.label
            if len(lbl) > 16:
                lbl = lbl[:13] + "..."
            s_label = f"⏱ {len(active_tasks)} Scheduled"
            s_detail = f" (next: '{lbl}' in {rem}) • /tasks"

            text_parts = [
                ("class:safi-scheduled", s_label),
                ("class:safi-dim", s_detail),
            ]
            text_len = len(s_label) + len(s_detail)

            spaces = max(0, cols - text_len - 2)
            fragments = [
                ("class:safi-divider", divider + "\n"),
                ("", " " * spaces),
            ]
            fragments.extend(text_parts)
            return FormattedText(fragments)
    except Exception:
        pass

    return FormattedText([("class:safi-divider", divider)])


_bottom_toolbar = _bottom_divider_text


class SafiPromptSession(_SessionBase):
    """Prompt session that places the bottom border immediately below the input line."""

    def _create_layout(self) -> "Layout":
        layout = super()._create_layout()
        bottom_divider_window = ConditionalContainer(
            Window(
                FormattedTextControl(_bottom_divider_text),
                dont_extend_height=True,
            ),
            filter=~is_done,
        )
        # Attach directly to the inner HSplit containing the prompt and input buffer,
        # and prevent the default buffer window from stretching down the terminal.
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
    """Adapt SAFi's ``(line, text) -> List[str]`` completions to prompt_toolkit."""

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
    """FileHistory that never lets the file grow unboundedly.

    Every TRIM_INTERVAL appends it drops consecutive duplicates and rewrites
    the file atomically with only the most recent MAX_ENTRIES lines. Between
    trims it behaves exactly like FileHistory (plain appends).
    """

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
        # load_history_strings() yields newest-first, so keeping the head of
        # the list keeps the most recent entries.
        trimmed = _TrimmingHistory._drop_consecutive_dupes(entries)[: self.MAX_ENTRIES]
        oldest_first = list(reversed(trimmed))
        try:
            dirname = os.path.dirname(os.path.abspath(self.filename)) or "."
            os.makedirs(dirname, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix=".history-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for entry in oldest_first:
                        # Match FileHistory.store_string's format: a comment
                        # separator line, then each physical line "+"-prefixed.
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
            # Trimming is best-effort; never break the input loop over it.
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
    # Swap the active completer when the caller's completion source changes
    # (e.g. after an agent switch) so stale suggestions never leak across.
    if completions_fn is not _SESSION_COMPLETER_FN:
        session.completer = _CallbackCompleter(completions_fn) if completions_fn else None
        _SESSION_COMPLETER_FN = completions_fn
    try:
        # Pass a callable so the prompt (and its divider) is built at RENDER
        # time, when prompt_toolkit's Application is running. _terminal_columns()
        # then reads app.output.get_size() (the exact width pt lays out with)
        # instead of a pre-render ioctl that can disagree with the render.
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
