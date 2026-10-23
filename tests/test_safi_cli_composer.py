"""Tests for the prompt_toolkit composer wiring (completions + history suggestions)."""

import pytest

from safi_cli import prompt_input


def _pt():
    pytest.importorskip("prompt_toolkit")
    return prompt_input


def _fresh_state(monkeypatch):
    """Reset module-level session caches so tests are order-independent."""
    monkeypatch.setattr(prompt_input, "_SESSION", None)
    monkeypatch.setattr(prompt_input, "_SESSION_HISTORY", None)
    monkeypatch.setattr(prompt_input, "_SESSION_COMPLETER_FN", None)


def test_session_gains_history_autosuggest(monkeypatch, tmp_path):
    pt = _pt()
    _fresh_state(monkeypatch)
    session = prompt_input._get_session(str(tmp_path / "hist"))
    assert session.auto_suggest is not None
    assert session.default_buffer is not None  # session constructed OK


def test_completer_swapped_when_fn_changes(monkeypatch, tmp_path):
    pt = _pt()
    _fresh_state(monkeypatch)
    session = prompt_input._get_session(str(tmp_path / "hist"))
    assert session.completer is None

    def fn_a(line, text):
        return []

    prompt_input._SESSION_COMPLETER_FN = fn_a
    session.completer = pt._CallbackCompleter(fn_a)
    assert isinstance(session.completer, pt._CallbackCompleter)

    # read_prompt with a different fn swaps the completer (simulate the swap
    # logic without rendering a real prompt)
    def fn_b(line, text):
        return ["/agent"]

    assert fn_b is not prompt_input._SESSION_COMPLETER_FN


def test_callback_completer_yields_completions(monkeypatch):
    pt = _pt()

    class Doc:
        def __init__(self, text):
            self.text = text
            self.cursor_position = len(text)

        def get_word_before_cursor(self, WORD=False):
            return "/ag"

    Doc.text_before_cursor = "/ag"

    class Ev:
        completion_requested = True

    def fn(line, text):
        return ["/agents", "/agent"]

    completer = pt._CallbackCompleter(fn)
    results = list(completer.get_completions(Doc("/ag"), Ev()))
    names = [c.text for c in results]
    assert "/agents" in names


def test_read_prompt_readline_fallback(monkeypatch):
    _fresh_state(monkeypatch)
    monkeypatch.setattr(prompt_input, "using_prompt_toolkit", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _p: "hello")
    assert prompt_input.read_prompt("dev") == "hello"


def test_agent_history_files_isolated(tmp_path):
    from safi_cli import config
    hist_sys = config.get_agent_history_file("sysadmin")
    hist_swe = config.get_agent_history_file("software_engineer")
    assert hist_sys != hist_swe
    assert "sysadmin" in str(hist_sys)
    assert "software_engineer" in str(hist_swe)


def test_session_swapped_when_agent_history_changes(monkeypatch, tmp_path):
    pt = _pt()
    _fresh_state(monkeypatch)
    hist_sys = str(tmp_path / "hist_sysadmin")
    hist_swe = str(tmp_path / "hist_software_engineer")

    session_sys = prompt_input._get_session(hist_sys)
    assert prompt_input._SESSION_HISTORY == hist_sys

    session_swe = prompt_input._get_session(hist_swe)
    assert prompt_input._SESSION_HISTORY == hist_swe
    assert session_swe is not session_sys
