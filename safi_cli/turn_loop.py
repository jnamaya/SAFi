"""Main agentic turn loop: tool proposals, resume budget, step ceiling."""

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import tools, ui
from .client import SafiClient, SafiClientError
from .subagents import (
    MAX_SUBAGENTS_PER_TURN,
    _execute_tool_with_live_status,
    run_subagent_task,
)

logger = logging.getLogger("safi.turn_loop")

DEFAULT_MAX_STEPS = int(os.environ.get("SAFI_CLI_MAX_STEPS", "150"))
_last_turn_result: Optional[Dict[str, Any]] = None


def get_last_turn_result() -> Optional[Dict[str, Any]]:
    """Return the last completed turn payload (for audit display)."""
    return _last_turn_result


def _handle_tool_proposal(
    proposal: Dict[str, Any],
    *,
    client: SafiClient,
    workspace_root: Path,
    conversation_id: str,
    user_id: str,
    agent: str,
    model: Optional[str],
    auto_approve: bool,
    tool_results: list,
    subagents_run_count: int,
) -> int:
    """Execute one Will-approved tool proposal and record its result."""
    tool_name = proposal.get("tool_name") or proposal.get("tool") or ""
    args = proposal.get("parameters") or proposal.get("params") or proposal.get("arguments") or {}
    will_decision = proposal.get("willDecision") or proposal.get("decision") or "approve"
    will_reason = proposal.get("willReason") or proposal.get("reason")

    ui.print_tool_proposal(tool_name, args, proposal)

    if will_decision not in ("approve", "approved"):
        tool_results.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": f"Security Gate rejected '{tool_name}' ({will_reason}).",
        })
        return subagents_run_count

    if tool_name in ("task", "delegate_subagent"):
        if subagents_run_count >= MAX_SUBAGENTS_PER_TURN:
            tool_results.append({
                "tool_name": tool_name,
                "arguments": args,
                "result": (
                    f"[Refused] Delegation budget exhausted for this turn "
                    f"({subagents_run_count} subagents already run). Do not delegate again. "
                    "Complete the work yourself now using edit/write/bash, then give your "
                    "final answer."
                ),
            })
            return subagents_run_count
        subagents_run_count += 1
        result_str = run_subagent_task(
            client=client,
            args=args,
            workspace_root=workspace_root,
            parent_conv_id=conversation_id,
            user_id=user_id,
            parent_agent=agent,
            model=model,
            max_steps=6,
        )
        if subagents_run_count >= MAX_SUBAGENTS_PER_TURN:
            result_str += (
                f"\n\n[System note: Delegation budget reached "
                f"({MAX_SUBAGENTS_PER_TURN} subagents executed). No further delegations "
                "are permitted this turn. Act on the findings yourself now (edit/write/bash) "
                "and then give your final answer.]"
            )
        tool_results.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": result_str,
        })
        return subagents_run_count

    if tool_name in ("question", "ask_user"):
        q_text = args.get("question") or args.get("prompt") or ""
        opts = args.get("options") or []
        user_answer = ui.prompt_question(q_text, opts)
        ui.print_tool_result_summary(tool_name, f"Developer response: {user_answer}")
        tool_results.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": f"Developer response: {user_answer}",
        })
        return subagents_run_count

    if proposal.get("executed_by") == "server":
        result_str = str(proposal.get("result", ""))
        ui.print_tool_result_summary(tool_name, result_str)
        tool_results.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": result_str,
        })
        return subagents_run_count

    allowed = ui.prompt_user_permission(tool_name, args, auto_approve=auto_approve)
    if not allowed:
        result_str = f"Execution of '{tool_name}' was declined by the developer."
    else:
        result_str = _execute_tool_with_live_status(tool_name, args, workspace_root, agent=agent)
        is_err = ui._result_is_error(result_str)
        if not is_err and tool_name in ("write", "edit"):
            raw_path = str(args.get("path") or args.get("filePath") or args.get("file_path") or "").replace("\\", "/").strip("/")
            if raw_path == ".safi/scratchpad.md" or raw_path.endswith("/.safi/scratchpad.md"):
                ui.sync_todos_from_scratchpad(workspace_root, render=True)
        ui.print_tool_result_summary(tool_name, result_str)

    tool_results.append({
        "tool_name": tool_name,
        "arguments": args,
        "result": result_str,
    })
    return subagents_run_count


def run_agent_turn(
    client: SafiClient,
    prompt: str,
    workspace_root: Path,
    conversation_id: str,
    user_id: str,
    agent: str,
    user_name: Optional[str] = None,
    model: Optional[str] = None,
    auto_approve: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
    cancel_event: Optional[threading.Event] = None,
    echo_prompt: bool = True,
):
    """Run an agentic loop until SAFi produces a final governed response."""
    global _last_turn_result
    tool_results = []
    subagents_run_count = 0
    recent_turns = ""

    ui.clear_active_todos()
    if echo_prompt:
        ui.print_user_prompt(prompt, agent=agent, user_name=user_name)

    resume_budget = 3

    try:
        for step in range(max_steps):
            if cancel_event and cancel_event.is_set():
                ui.console.print("\n[yellow]Turn cancelled by user.[/yellow]")
                break
            turn_msg_id = str(uuid.uuid4())
            last_status_markup = ui.build_progress_line(None, None, 0.0, model=model)
            try:
                with ui.console.status(
                    last_status_markup,
                    spinner="dots",
                ) as status_indicator:
                    stop_poller = threading.Event()
                    start_time = time.time()
                    def _poll_progress():
                        nonlocal last_status_markup
                        current_step_text = "Governing turn"
                        progress_codes: List[str] = []
                        while not stop_poller.wait(0.25):
                            try:
                                progress_data = client.get_turn_progress(turn_msg_id, user_id=user_id)
                                if stop_poller.is_set():
                                    break
                                if isinstance(progress_data, dict):
                                    codes = progress_data.get("progress")
                                    if isinstance(codes, list):
                                        progress_codes = [c for c in codes if isinstance(c, str)]
                                    raw_step = progress_data.get("latest_step")
                                    if raw_step and raw_step != current_step_text:
                                        current_step_text = raw_step
                            except Exception as exc:
                                if stop_poller.is_set():
                                    break
                                logger.debug("Progress poll error: %s", exc)
                            if stop_poller.is_set():
                                break
                            elapsed = time.time() - start_time
                            last_status_markup = ui.build_progress_line(
                                progress_codes or None,
                                current_step_text,
                                elapsed,
                                model=model,
                            )
                            status_indicator.update(last_status_markup)

                    poller = threading.Thread(target=_poll_progress, daemon=True)
                    poller.start()
                    try:
                        delegations_spent = subagents_run_count >= MAX_SUBAGENTS_PER_TURN

                        def _tool_ok(t: Dict[str, Any]) -> bool:
                            name = t.get("function", {}).get("name")
                            if delegations_spent and name in ("task", "delegate_subagent"):
                                return False
                            return True

                        agent_tools = tools.get_tools_for_agent(agent)
                        active_tools = (
                            [t for t in agent_tools if _tool_ok(t)]
                            if agent_tools
                            else None
                        )

                        res = client.send_turn(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message=prompt,
                            workspace_root=str(workspace_root.resolve()),
                            agent=agent,
                            user_name=user_name,
                            model=model,
                            tools=active_tools,
                            tool_results=tool_results,
                            recent_turns=recent_turns,
                            message_id=turn_msg_id,
                        )
                    finally:
                        stop_poller.set()
                        poller.join(timeout=0.5)
                        try:
                            status_indicator.stop()
                        except Exception as exc:
                            logger.debug("status_indicator.stop() failed: %s", exc)
            except SafiClientError as err:
                ui.clear_live_status_tail(last_status_markup)
                ui.print_error(str(err))
                return None

            ui.clear_live_status_tail(last_status_markup)

            if res.get("type") == "tool_call":
                batch = res.get("tool_calls")
                if isinstance(batch, list) and batch:
                    for proposal in batch:
                        if isinstance(proposal, dict):
                            subagents_run_count = _handle_tool_proposal(
                                proposal,
                                client=client,
                                workspace_root=workspace_root,
                                conversation_id=conversation_id,
                                user_id=user_id,
                                agent=agent,
                                model=model,
                                auto_approve=auto_approve,
                                tool_results=tool_results,
                                subagents_run_count=subagents_run_count,
                            )
                else:
                    subagents_run_count = _handle_tool_proposal(
                        res,
                        client=client,
                        workspace_root=workspace_root,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        agent=agent,
                        model=model,
                        auto_approve=auto_approve,
                        tool_results=tool_results,
                        subagents_run_count=subagents_run_count,
                    )
                last_tr = tool_results[-1] if tool_results else {}
                last_tpath = str((last_tr.get("arguments") or {}).get("path") or "")
                last_tres = str(last_tr.get("result") or "")
                if not last_tres.startswith("Error:") and not last_tpath.endswith("scratchpad.md"):
                    resume_budget = 2
                continue

            final_text = res.get("finalOutput") or ""
            will_dec = str(res.get("willDecision") or "approve").lower()
            is_intercepted = will_dec not in ("approve", "approved", "pass")

            unfinished_todos = [
                t for t in ui.get_active_todos()
                if (t.get("status") or "pending").lower() not in ("completed", "done")
            ]
            if not is_intercepted and unfinished_todos and resume_budget > 0 and step < max_steps - 1:
                resume_budget -= 1
                remaining = "; ".join(
                    str(t.get("task") or t.get("content") or t.get("description") or "step")
                    for t in unfinished_todos
                )[:500]
                pause_note = " ".join((final_text or "").split())[:500]
                tool_results.append({
                    "tool_name": "harness_note",
                    "arguments": {},
                    "result": (
                        "[Harness] Your last message was a mid-task status note, not "
                        "the final answer. The plan in '.safi/scratchpad.md' still has unfinished steps: "
                        f"{remaining}. Do not ask the user for permission. Continue "
                        "now with the appropriate tools, or, if the work is genuinely "
                        "done, use 'write' to rewrite '.safi/scratchpad.md' with the remaining steps marked [x] complete "
                        "(prefer 'write' over 'edit' to avoid target-matching errors). Never repeat plaintext passwords or secrets in your summary. "
                        f"(Your note: {pause_note})"
                    ),
                })
                ui.console.print("[dim yellow]↳ Plan incomplete — continuing autonomously…[/dim yellow]")
                continue

            executed_tools = res.get("toolCalls") or res.get("tool_calls") or []
            displayed_tools_count = len(tool_results)
            unseen_tools = executed_tools[displayed_tools_count:] if len(executed_tools) >= displayed_tools_count else []
            for tc in unseen_tools:
                t_name = tc.get("tool") or tc.get("tool_name", "")
                if not t_name:
                    continue
                t_params = tc.get("params") or tc.get("parameters") or {}
                t_decision = tc.get("decision") or tc.get("willDecision", "approve")
                t_reason = tc.get("reason") or tc.get("willReason")
                t_result = tc.get("result") or tc.get("result_snippet")
                t_ledger = tc.get("toolProposalLedger") or tc.get("conscienceLedger") or []

                ui.print_tool_proposal(t_name, t_params, {
                    "willDecision": t_decision,
                    "willReason": t_reason,
                    "toolProposalLedger": t_ledger,
                })
                if t_result:
                    ui.print_tool_result_summary(t_name, str(t_result))
                else:
                    ui.console.print(f"  [dim green]↳ ✓ Executed {t_name} (server MCP)[/dim green]")

            _last_turn_result = res
            ui.print_final_output(final_text, res)
            return res

        if tool_results:
            tool_results.append({
                "tool_name": "harness_note",
                "arguments": {},
                "result": (
                    f"[Harness] Reached the tool step ceiling ({max_steps} steps). "
                    "No further tool calls are available in this turn. Do NOT emit any "
                    "<tool_call> tags or tool proposals; provide a clear summary of what "
                    "was completed and any remaining items."
                ),
            })
            try:
                res = client.send_turn(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message=prompt,
                    workspace_root=str(workspace_root.resolve()),
                    agent=agent,
                    user_name=user_name,
                    model=model,
                    tool_results=tool_results,
                    recent_turns=recent_turns,
                    message_id=str(uuid.uuid4()),
                    tools=[],
                )
            except SafiClientError as err:
                ui.print_error(str(err))
                return None
            final_text = res.get("finalOutput") or ""
            if final_text:
                _last_turn_result = res
                ui.print_final_output(final_text, res)
                return res
        ui.print_error(
            f"Reached the tool-loop ceiling ({max_steps} iterations) without a final "
            "answer. Raise it with --max-steps or SAFI_CLI_MAX_STEPS and retry."
        )
        return None
    except KeyboardInterrupt:
        ui.console.print("\n[bold yellow]Turn cancelled (Ctrl+C).[/bold yellow]")
        return None
