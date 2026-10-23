"""Isolated subagent execution: role confinement and live-status tool runner."""

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from . import tools, ui
from .client import SafiClient

logger = logging.getLogger("safi.subagents")


MAX_SUBAGENTS_PER_TURN = 3


def run_subagent_task(
    client: SafiClient,
    args: Dict[str, Any],
    workspace_root: Path,
    parent_conv_id: str,
    user_id: str,
    parent_agent: str = "software_engineer",
    model: Optional[str] = None,
    max_steps: int = 6,
) -> str:
    """Execute an isolated child subagent turn loop under strict role confinement."""
    description = (
        args.get("description")
        or args.get("task")
        or args.get("summary")
        or "Subagent task"
    )
    prompt = (
        args.get("prompt")
        or args.get("goal")
        or args.get("instruction")
        or description
    )
    subagent_type = (
        args.get("subagent_type")
        or args.get("role")
        or "researcher"
    ).strip().lower()

    if subagent_type == "researcher":
        allowed_tool_names = ("read", "grep", "glob", "list", "git_status", "git_diff")
        role_prompt = (
            "You are a focused, read-only Research Subagent for SAFi. "
            "Your objective is to inspect repository files, search patterns, and return a concise, factual summary of findings. "
            "Do NOT propose write, edit, delete, or bash commands. Be specific with file paths and line numbers."
        )
    elif subagent_type == "tester":
        allowed_tool_names = ("bash", "read", "grep", "list")
        role_prompt = (
            "You are a focused Test Runner Subagent for SAFi. "
            "Run relevant test commands using 'bash', inspect results, and report pass/fail status and failure causes."
        )
    elif subagent_type == "code_reviewer":
        allowed_tool_names = ("read", "grep", "glob", "list", "git_status", "git_diff")
        role_prompt = (
            "You are a Code Review Subagent for SAFi. "
            "Inspect files and diffs to identify bugs, potential edge cases, security flaws, or architectural discrepancies."
        )
    else:
        allowed_tool_names = ("read", "grep", "glob", "list", "git_status", "git_diff")
        role_prompt = f"You are a specialized subagent for SAFi focused on: {subagent_type}."

    # Mutation policy is enforced authoritatively by the server's Will gate plus
    # the role tool filtering above: read-only subagents simply have no mutating
    # tools available, so a heuristic client-side regex refusal is unnecessary.
    ui.print_subagent_start(subagent_type, description)

    child_tools = [t for t in tools.TOOL_SCHEMAS if t["function"]["name"] in allowed_tool_names]
    sub_suffix = f"_sub_{uuid.uuid4().hex[:6]}"
    max_parent_prefix_len = 36 - len(sub_suffix)
    child_conv_id = f"{parent_conv_id[:max_parent_prefix_len]}{sub_suffix}"
    child_initial_message = f"{role_prompt}\n\nTask: {description}\n\nGoal: {prompt}"

    child_tool_results = []
    last_snippet = "No tools run"

    for step in range(max_steps):
        child_msg_id = str(uuid.uuid4())
        step_prompt = child_initial_message if step == 0 else (
            f"{child_initial_message}\n\n"
            f"[Directive: Review the collected tool results and continue towards completing the goal. "
            f"If you have gathered sufficient evidence, synthesize and return your final answer.]"
        )
        try:
            res = client.send_turn(
                user_id=user_id,
                conversation_id=child_conv_id,
                message=step_prompt,
                workspace_root=str(workspace_root.resolve()),
                agent=parent_agent,
                model=model,
                tool_results=child_tool_results,
                tools=child_tools,
                message_id=child_msg_id,
            )
        except Exception as exc:
            err = f"Subagent error: {exc}"
            ui.print_subagent_done(subagent_type, err, steps=step + 1)
            return err

        if res.get("type") == "tool_call":
            batch = res.get("tool_calls")
            proposals = batch if (isinstance(batch, list) and batch) else [res]
            for prop in proposals:
                if not isinstance(prop, dict):
                    continue
                t_name = prop.get("tool_name") or prop.get("tool") or ""
                t_args = prop.get("parameters") or prop.get("params") or prop.get("arguments") or {}

                if t_name not in allowed_tool_names:
                    blocked_msg = f"Rejected: Subagent role '{subagent_type}' is restricted and not permitted to execute '{t_name}'."
                    ui.print_subagent_step(subagent_type, t_name, t_args, "Blocked by role sub-policy")
                    child_tool_results.append({
                        "tool_name": t_name,
                        "arguments": t_args,
                        "result": blocked_msg,
                    })
                    continue

                t_out = _execute_tool_with_live_status(t_name, t_args, workspace_root, agent=subagent_type)
                last_snippet = t_out[:200]
                ui.print_subagent_step(subagent_type, t_name, t_args, t_out)
                child_tool_results.append({
                    "tool_name": t_name,
                    "arguments": t_args,
                    "result": t_out,
                })
            continue

        final_out = res.get("finalOutput") or ""
        ui.print_subagent_done(subagent_type, final_out, steps=step + 1)
        return f"Subagent ({subagent_type}) findings for '{description}':\n{final_out}"

    fallback_out = f"Subagent ({subagent_type}) reached iteration limit ({max_steps}). Summary: {last_snippet}"
    ui.print_subagent_done(subagent_type, fallback_out, steps=max_steps)
    return fallback_out


def _execute_tool_with_live_status(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    agent: Optional[str] = None,
) -> str:
    """Execute a local tool while displaying a live animated spinner with elapsed seconds and streaming output."""
    stop_event = threading.Event()
    start_time = time.time()
    latest_line: Optional[str] = None
    last_status_markup = ui.build_tool_status_line(tool_name, args, 0.0)

    def _on_output(line: str) -> None:
        nonlocal latest_line
        if line and line.strip():
            latest_line = line.strip()

    try:
        with ui.console.status(last_status_markup, spinner="dots") as status_indicator:
            def _ticker():
                nonlocal last_status_markup
                while not stop_event.wait(0.2):
                    elapsed = time.time() - start_time
                    last_status_markup = ui.build_tool_status_line(
                        tool_name, args, elapsed, latest_output=latest_line
                    )
                    status_indicator.update(last_status_markup)

            t = threading.Thread(target=_ticker, daemon=True)
            t.start()
            try:
                return tools.execute_tool(
                    tool_name, args, workspace_root, agent=agent, on_output=_on_output
                )
            finally:
                stop_event.set()
                t.join(timeout=0.3)
                try:
                    status_indicator.stop()
                except Exception as exc:
                    logger.debug("status_indicator.stop() failed: %s", exc)
    finally:
        ui.clear_live_status_tail(last_status_markup)
