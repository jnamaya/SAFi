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
from typing import Callable, List, Optional



from . import ui

try:
    from prompt_toolkit import PromptSession
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


def read_prompt(
    agent_label: str,
    completions_fn: Optional[CompletionsFn] = None,
    history_path: Optional[str] = None,
) -> Optional[str]:
    """Read one (possibly multi-line) prompt from the user."""
    if using_prompt_toolkit():
        return _read_prompt_toolkit(agent_label, completions_fn, history_path)
    return _read_prompt_readline(agent_label)


_SESSION = None
_SESSION_HISTORY: Optional[str] = None
_SESSION_COMPLETER_FN: Optional[CompletionsFn] = None
_KEY_BINDINGS = None
_STYLE = None


def _get_divider(cols: Optional[int] = None) -> str:
    if cols is None:
        cols = shutil.get_terminal_size((80, 24)).columns
    return "─" * max(20, cols)


def _prompt_style():
    global _STYLE
    if _STYLE is None:
        _STYLE = Style.from_dict({
            "safi-divider": "#334155",
            "safi-badge": "#4ade80 bold",
            "safi-agent": "#94a3b8",
            "safi-arrow": "#38bdf8 bold",
            "": "#f8fafc",
            "auto-suggest": "#64748b italic",
            "bottom-toolbar": "noinherit #334155",
            "completion-menu": "bg:#1e293b #f8fafc",
            "completion-menu.completion": "bg:#1e293b #cbd5e1",
            "completion-menu.completion.current": "bg:#334155 #38bdf8 bold",
            "completion-menu.meta": "bg:#0f172a #94a3b8",
            "scrollbar.background": "bg:#1e293b",
            "scrollbar.button": "bg:#475569",
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


def _prompt_text(agent_label: str) -> "FormattedText":
    margin = " " * int(os.environ.get("SAFI_CLI_MARGIN", "2") or "2")
    divider = _get_divider()
    agent = agent_label or "software_engineer"
    return FormattedText([
        ("", "\n"),
        ("class:safi-divider", divider + "\n"),
        ("", margin),
        ("class:safi-badge", "SAFi "),
        ("class:safi-agent", f"[{agent}] "),
        ("class:safi-arrow", "› "),
    ])


def _bottom_divider_text() -> "FormattedText":
    return FormattedText([
        ("class:safi-divider", _get_divider()),
    ])


_bottom_toolbar = _bottom_divider_text


class SafiPromptSession(_SessionBase):
    """Prompt session that places the bottom border immediately below the input line."""

    def _create_layout(self) -> "Layout":
        layout = super()._create_layout()
        bottom_divider_window = ConditionalContainer(
            Window(
                FormattedTextControl(_bottom_divider_text),
                height=1,
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
) -> Optional[str]:
    global _SESSION_COMPLETER_FN
    session = _get_session(history_path)
    # Swap the active completer when the caller's completion source changes
    # (e.g. after an agent switch) so stale suggestions never leak across.
    if completions_fn is not _SESSION_COMPLETER_FN:
        session.completer = _CallbackCompleter(completions_fn) if completions_fn else None
        _SESSION_COMPLETER_FN = completions_fn
    try:
        return session.prompt(
            _prompt_text(agent_label),
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
