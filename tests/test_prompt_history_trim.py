"""Tests for the bounded (trimming) history file used by the composer."""

import os

from prompt_toolkit.history import FileHistory

from safi_cli.prompt_input import _TrimmingHistory


def _entries(path):
    return list(FileHistory(path).load_history_strings())


def test_trim_caps_file_at_max_entries(tmp_path):
    path = str(tmp_path / "history")
    h = _TrimmingHistory(path)
    h.TRIM_INTERVAL = 5
    h.MAX_ENTRIES = 10
    for i in range(50):
        h.append_string(f"prompt-{i}")
    assert len(_entries(path)) == 10
    # load_history_strings() yields newest-first.
    assert _entries(path) == [f"prompt-{i}" for i in range(49, 39, -1)]


def test_trim_drops_consecutive_duplicates(tmp_path):
    path = str(tmp_path / "history")
    h = _TrimmingHistory(path)
    h.TRIM_INTERVAL = 3
    h.MAX_ENTRIES = 100
    for line in ["a", "a", "a", "b", "b", "c"]:
        h.append_string(line)
    # Consecutive dupes collapsed; order preserved.
    assert _entries(path) == ["c", "b", "a"]


def test_no_trim_before_interval(tmp_path):
    path = str(tmp_path / "history")
    h = _TrimmingHistory(path)
    for i in range(10):
        h.append_string(f"x{i}")
    # Below TRIM_INTERVAL (500): plain FileHistory behaviour, nothing dropped.
    assert len(_entries(path)) == 10


def test_multiline_entries_round_trip(tmp_path):
    path = str(tmp_path / "history")
    h = _TrimmingHistory(path)
    h.TRIM_INTERVAL = 1
    h.MAX_ENTRIES = 5
    h.append_string("line one\nline two\nback\\slash")
    assert _entries(path) == ["line one\nline two\nback\\slash"]


def test_trim_leaves_no_temp_files(tmp_path):
    path = str(tmp_path / "history")
    h = _TrimmingHistory(path)
    h.TRIM_INTERVAL = 2
    for i in range(4):
        h.append_string(f"y{i}")
    assert sorted(os.listdir(tmp_path)) == ["history"]
