#!/usr/bin/env python3
"""Regression tests for batched client tool calls.

One Intellect turn may propose several independent tools (read four files, or
list+grep+read). The provider already parses the whole tool_calls array; these
tests pin that the intent carries every call, that the orchestrator batches them
ONLY when all are approved, and that each still gets its own structured receipt
and the same deterministic WillGate. Any blocked call must fall back to the
single-proposal path with no side effects.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator import SAFi
from safi_app.core.faculties.intellect import normalize_tool_calls
from safi_app.core.faculties.will import WillGate
from safi_app.core.faculties.phase_zero import PhaseZeroGate

PROFILE = {
    "name": "developer",
    "allowed_tools": ["read", "glob", "edit", "write", "bash", "delete"],
    "will_rules": {},
}


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_orch(intellect_results, profile=None):
    profile = dict(profile or PROFILE)
    store = SimpleNamespace(
        insert_turn_atomic=MagicMock(return_value=True),
        fetch_chat_history_for_conversation=MagicMock(return_value=[]),
        set_conversation_title_from_first_message=MagicMock(return_value="Title"),
        fetch_conversation_summary=MagicMock(return_value=""),
        fetch_user_profile_memory=MagicMock(return_value="{}"),
        fetch_agent_context_memory=MagicMock(return_value="{}"),
        load_spirit_memory=MagicMock(return_value={"turn": 0, "mu": {}}),
        update_spirit_memory_atomic=MagicMock(),
        update_message_reasoning=MagicMock(),
        update_message_content=MagicMock(),
        update_audit_results=MagicMock(),
    )
    calls = []

    async def mock_generate(*args, **kwargs):
        calls.append(kwargs)
        return intellect_results.pop(0)

    intellect = SimpleNamespace(generate=mock_generate, last_error=None)
    conscience = SimpleNamespace(evaluate=AsyncMock(), evaluate_tool_preflight=AsyncMock())

    orch = SAFi.__new__(SAFi)
    orch.config = SimpleNamespace(MAX_AGENT_TURNS=5, AGENT_MEMORY_MAX_CHARS=2000, ENABLE_PROFILE_EXTRACTION=False)
    orch.profile = profile
    orch.active_profile_name = "developer"
    orch.values = [{"value": "accuracy", "weight": 1.0}]
    orch.intellect_engine = intellect
    orch.conscience = conscience
    orch.spirit = SimpleNamespace(compute=MagicMock(), compute_redirect=MagicMock(), values=[])
    orch.will_gate = WillGate(None, values=[], profile=profile)
    orch.phase_zero = PhaseZeroGate(threat_rules={})
    orch.store = store
    orch.log = SimpleNamespace(info=MagicMock(), warning=MagicMock(), error=MagicMock(), exception=MagicMock())
    orch._spirit_state_lock = _Lock()
    orch.mu_history = []
    orch.last_drift = 0.0
    orch.intellect_model = "test-model"
    orch.conscience_model = "test-conscience"
    orch.model_attribution = {}
    orch.mcp_manager = None
    orch.review_alert_callback = None
    orch.background_task_callback = None
    orch.context_budgeter = lambda ctx, cap: ctx
    orch._resolve_history_window = lambda: (5, 4000)
    orch._is_cancelled = lambda msg_id: False
    orch._pii_enabled = lambda org: False
    orch._append_log = MagicMock()
    orch.activate_org = MagicMock()
    orch.activate_agent = MagicMock()
    orch._record_harness_progress = MagicMock()
    return orch, store, conscience, calls


def _run_batch(orch, proposed, client_tool_results=None, server_tool_names=None):
    tool_audit = []
    payload = asyncio.run(orch._propose_tools_batch(
        proposed,
        profile_for_turn=orch.profile,
        client_tool_results=client_tool_results or [],
        server_tool_names=server_tool_names or set(),
        user_prompt="do the thing",
        user_id="user-1",
        message_id="msg-1",
        new_title=None,
        recent_turns_text="",
        tool_audit=tool_audit,
    ))
    return payload, tool_audit


# ---------------------------------------------------------------------------
# Provider/Intellect normalisation
# ---------------------------------------------------------------------------
def test_normalize_keeps_every_call_and_coerces_args():
    calls = normalize_tool_calls([
        {"name": "read", "arguments": {"path": "a.py"}},
        {"tool_name": "glob", "parameters": '{"pattern": "*.py"}'},
        {"name": "grep"},  # missing args -> {}
        {"arguments": {"x": 1}},  # no name -> dropped
        "not-a-dict",  # dropped
    ])
    assert calls == [
        {"tool_name": "read", "parameters": {"path": "a.py"}},
        {"tool_name": "glob", "parameters": {"pattern": "*.py"}},
        {"tool_name": "grep", "parameters": {}},
    ]


def test_normalize_handles_non_list():
    assert normalize_tool_calls(None) == []
    assert normalize_tool_calls({"name": "read"}) == []


# ---------------------------------------------------------------------------
# Orchestrator batch path
# ---------------------------------------------------------------------------
def test_batch_all_approved_returns_multiple_proposals():
    orch, store, conscience, _ = _make_orch([])
    proposed = [
        {"tool_name": "read", "parameters": {"path": "/repo/a.py"}},
        {"tool_name": "glob", "parameters": {"pattern": "*.py"}},
    ]
    payload, tool_audit = _run_batch(orch, proposed)

    assert payload is not None
    assert payload["type"] == "tool_call"
    assert payload["willDecision"] == "approve"
    assert [e["tool_name"] for e in payload["tool_calls"]] == ["read", "glob"]
    # One structured receipt per call.
    assert [e["tool_name"] for e in tool_audit] == ["read", "glob"]
    assert all(e["decision"] == "approve" for e in tool_audit)
    # Audit is written once for the batch, never per-step Conscience.
    store.update_audit_results.assert_called_once()
    store.update_message_content.assert_called_once()
    conscience.evaluate.assert_not_called()
    conscience.evaluate_tool_preflight.assert_not_called()


def test_batch_falls_back_when_any_call_is_blocked():
    orch, store, _, _ = _make_orch([])
    proposed = [
        {"tool_name": "read", "parameters": {"path": "/repo/a.py"}},
        {"tool_name": "unauthorized_tool", "parameters": {}},
    ]
    payload, tool_audit = _run_batch(orch, proposed)

    assert payload is None
    # No side effects: the single-proposal path below owns the blocked handling.
    assert tool_audit == []
    store.update_audit_results.assert_not_called()
    store.update_message_content.assert_not_called()


def test_batch_skipped_when_policy_requires_llm_preflight():
    profile = dict(PROFILE)
    profile["will_rules"] = {"audit_tool_intents": True}
    orch, store, _, _ = _make_orch([], profile=profile)
    proposed = [
        {"tool_name": "read", "parameters": {"path": "/repo/a.py"}},
        {"tool_name": "glob", "parameters": {"pattern": "*.py"}},
    ]
    payload, tool_audit = _run_batch(orch, proposed)

    assert payload is None
    store.update_audit_results.assert_not_called()


def test_batch_env_toggle(monkeypatch):
    assert SAFi._batch_tools_enabled() is True
    monkeypatch.setenv("SAFI_AGENTIC_BATCH_TOOLS", "0")
    assert SAFi._batch_tools_enabled() is False


# ---------------------------------------------------------------------------
# End-to-end through process_prompt
# ---------------------------------------------------------------------------
def test_process_prompt_returns_batched_proposals():
    multi = {
        "type": "tool_call",
        "tool_name": "read",
        "parameters": {"path": "/repo/a.py"},
        "tool_calls": [
            {"tool_name": "read", "parameters": {"path": "/repo/a.py"}},
            {"tool_name": "glob", "parameters": {"pattern": "*.py"}},
        ],
    }
    orch, store, conscience, _ = _make_orch([(multi, "reading", "ctx")])

    res = asyncio.run(orch.process_prompt(
        user_prompt="read the sources",
        user_id="user-1",
        conversation_id="conv-1",
        client_owned_tools=[{"name": "read", "type": "function"}, {"name": "glob", "type": "function"}],
    ))

    assert res.get("type") == "tool_call"
    assert len(res.get("tool_calls", [])) == 2
    assert [e["tool_name"] for e in res["tool_calls"]] == ["read", "glob"]
    conscience.evaluate.assert_not_called()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
