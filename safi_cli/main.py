import argparse
import glob
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


DEFAULT_MAX_STEPS = int(os.environ.get("SAFI_CLI_MAX_STEPS", "100"))
_last_turn_result: Optional[Dict[str, Any]] = None


def _collect_multiline(initial: str) -> str:
    """Join backslash-continued input lines so users can compose/paste multi-line prompts."""
    return prompt_input.collect_multiline(initial)


MAX_SUBAGENTS_PER_TURN = 3

_MUTATION_VERBS_RE = re.compile(
    r"\b(?:"
    r"convert|rewrite|implement|refactor|migrate|modify|edit|write|create|"
    r"delete|remove|patch|upgrade|redesign|replace|modernize|"
    r"generate the|apply the|make the change|build the page|update the"
    r")\b",
    re.IGNORECASE,
)
_READ_ONLY_DISCLAIMERS = (
    "do not modify", "do not edit", "do not change", "do not write", "do not alter",
    "do not implement", "without modifying", "without editing", "without changing",
    "read-only", "read only", "no edits", "non-destructive",
)


def _looks_like_mutation_request(text: str) -> bool:
    """True when a delegation prompt asks the subagent to change files."""
    low = (text or "").lower()
    if any(d in low for d in _READ_ONLY_DISCLAIMERS):
        return False
    return bool(_MUTATION_VERBS_RE.search(low))


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

    if (
        subagent_type not in ("tester", "code_reviewer")
        and not ({"edit", "write"} & set(allowed_tool_names))
        and _looks_like_mutation_request(f"{description}\n{prompt}")
    ):
        refusal = (
            f"Refused: subagent type '{subagent_type}' is read-only and cannot modify files, "
            "so this delegation cannot complete the requested change. Do not delegate "
            "implementation to subagents. Make the change yourself now with the 'edit' tool "
            "(existing files) or 'write' (new files), then continue the task."
        )
        ui.print_subagent_done(subagent_type, refusal, steps=0)
        return refusal

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
    """Execute a local tool while displaying a live animated spinner with elapsed seconds."""
    stop_event = threading.Event()
    start_time = time.time()
    last_status_markup = ui.build_tool_status_line(tool_name, args, 0.0)

    try:
        with ui.console.status(last_status_markup, spinner="dots") as status_indicator:
            def _ticker():
                nonlocal last_status_markup
                while not stop_event.wait(0.2):
                    elapsed = time.time() - start_time
                    last_status_markup = ui.build_tool_status_line(tool_name, args, elapsed)
                    status_indicator.update(last_status_markup)

            t = threading.Thread(target=_ticker, daemon=True)
            t.start()
            try:
                return tools.execute_tool(tool_name, args, workspace_root, agent=agent)
            finally:
                stop_event.set()
                t.join(timeout=0.3)
                try:
                    status_indicator.stop()
                except Exception:
                    pass
    finally:
        ui.clear_live_status_tail(last_status_markup)


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

    if tool_name in ("todowrite", "todo_write"):
        todos = args.get("todos") or []
        ui.render_todo_list(todos)
        total = len(todos)
        completed = sum(1 for t in todos if (t.get("status") or "").lower() in ("completed", "done"))
        pct = int((completed / total) * 100) if total > 0 else 0
        in_prog = [t for t in todos if (t.get("status") or "").lower() in ("in_progress", "running")]
        curr_item = in_prog[0].get("task") if in_prog else (todos[0].get("task") if todos else "first step")
        res_msg = (
            f"Recorded plan with {total} task(s) ({completed}/{total} completed • {pct}%). "
            f"Now execute the current task ('{curr_item}') using action tools (read, write, edit, bash). "
            f"DO NOT call todowrite again until you have executed real tool actions."
        )
        ui.print_tool_result_summary(tool_name, res_msg)
        tool_results.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": res_msg,
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
        ui.advance_active_todo(tool_name, args, is_success=(not is_err))
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
):
    """Run an agentic loop until SAFi produces a final governed response."""
    global _last_turn_result
    tool_results = []
    subagents_run_count = 0
    recent_turns = ""

    ui.clear_completed_todos()
    ui.print_user_prompt(prompt, agent=agent, user_name=user_name)

    resume_budget = 3

    try:
        for step in range(max_steps):
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
                            except Exception:
                                if stop_poller.is_set():
                                    break
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
                        plan_recorded = any(tr.get("tool_name") in ("todowrite", "todo_write") for tr in tool_results)
                        delegations_spent = subagents_run_count >= MAX_SUBAGENTS_PER_TURN

                        def _tool_ok(t: Dict[str, Any]) -> bool:
                            name = t.get("function", {}).get("name")
                            if plan_recorded and name in ("todowrite", "todo_write"):
                                return False
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
                        except Exception:
                            pass
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
                resume_budget = 3
                continue

            final_text = res.get("finalOutput") or ""

            unfinished_todos = [
                t for t in ui.get_active_todos()
                if (t.get("status") or "pending").lower() not in ("completed", "done")
            ]
            if unfinished_todos and resume_budget > 0 and step < max_steps - 1:
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
                        "the final answer. The plan still has unfinished steps: "
                        f"{remaining}. Do not ask the user for permission. Continue "
                        "now with the appropriate tools, or, if the work is genuinely "
                        f"done, mark the remaining steps complete. (Your note: {pause_note})"
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
            ui.mark_active_todos_completed()
            ui.print_final_output(final_text, res)
            return res

        if tool_results:
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
                ui.mark_active_todos_completed()
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


DEFAULT_AGENTS = {
    "software_engineer": {
        "title": "Software Engineer",
        "description": "Direct, audited repository engineering & software development",
    },
    "sysadmin": {
        "title": "Systems Administrator",
        "description": "Governed, evidence-based operations across servers, network, identity & cloud",
    },
    "fiduciary": {
        "title": "The Fiduciary",
        "description": "Market-aware financial analyst, portfolio educator & data-driven guide",
    },
    "health_navigator": {
        "title": "Health Navigator",
        "description": "Evidence-based health literature, clinical navigation & wellness guide",
    },
    "socratic_tutor": {
        "title": "Socratic Tutor",
        "description": "Pedagogical inquiry, conceptual reasoning & critical thinking coach",
    },
    "bible_scholar": {
        "title": "Bible Scholar",
        "description": "Scriptural hermeneutics, historical-grammatical exegesis & theology",
    },
    "safi_steward": {
        "title": "SAFi Steward",
        "description": "Platform administration, policy governance & compliance stewardship",
    },
}

AVAILABLE_AGENTS = dict(DEFAULT_AGENTS)


def discover_agents(client: Optional[SafiClient] = None) -> Dict[str, Dict[str, Any]]:
    """Discover available agents dynamically from the server URL, falling back to local defaults."""
    if not client:
        return AVAILABLE_AGENTS

    try:
        if hasattr(client, "get_available_agents") and callable(client.get_available_agents):
            remote_list = client.get_available_agents()
            if isinstance(remote_list, list) and remote_list:
                discovered = {}
                for item in remote_list:
                    if not isinstance(item, dict):
                        continue
                    k = item.get("key") or item.get("agent_key")
                    if not k:
                        continue
                    discovered[k] = {
                        "title": item.get("name") or item.get("title") or k.replace("_", " ").title(),
                        "description": item.get("description") or "",
                        "is_custom": item.get("is_custom", False),
                    }
                if discovered:
                    AVAILABLE_AGENTS.clear()
                    AVAILABLE_AGENTS.update(discovered)
    except Exception:
        pass

    return AVAILABLE_AGENTS


def prompt_switch_agent(
    current_agent: str,
    client: SafiClient,
    workspace_root: Path,
    requested_agent: Optional[str] = None,
) -> tuple[str, str]:
    """Interactively select or switch to an agent persona, prompting for its Policy API key if not yet configured."""
    from rich.table import Table
    from rich import box

    discover_agents(client)
    agent_keys = list(AVAILABLE_AGENTS.keys())
    target_agent = None

    if requested_agent:
        req = requested_agent.strip().lower()
        if req in AVAILABLE_AGENTS:
            target_agent = req
        else:
            if req.isdigit() and 1 <= int(req) <= len(agent_keys):
                target_agent = agent_keys[int(req) - 1]
            else:
                for k, v in AVAILABLE_AGENTS.items():
                    if req in v["title"].lower() or req in k:
                        target_agent = k
                        break
        if not target_agent:
            ui.console.print(f"[bold red]Unknown agent persona:[/] [yellow]'{requested_agent}'[/]. Use [bold]/[/] to see available options.")
            return current_agent, config.resolve_session_id(str(workspace_root))

    if not target_agent:
        backend_tag = f" ({client.api_url})" if getattr(client, "api_url", None) else ""
        table = Table(title=f"Available SAFi Agent Personas{backend_tag}", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
        table.add_column("#", style=f"bold {ui.COLOR_WARN}", width=3, justify="right")
        table.add_column("Agent Key", style=f"bold {ui.COLOR_BRAND_400}")
        table.add_column("Title", style="bold white")
        table.add_column("Policy API Key", style="dim")
        table.add_column("Description", style="dim")

        for idx, (k, v) in enumerate(AVAILABLE_AGENTS.items(), 1):
            active_marker = f" [bold {ui.COLOR_BRAND_500}](active)[/]" if k == current_agent else ""
            key_val = config.resolve_agent_api_key(k)
            key_status = f"[{ui.COLOR_PASS}]✓ Configured[/]" if key_val else f"[{ui.COLOR_WARN}]⚠️  Key Needed[/]"
            table.add_row(str(idx), f"{k}{active_marker}", v["title"], key_status, v["description"])

        ui.console.print(table)
        old_completer = readline.get_completer() if readline else None
        if readline:
            def agent_sub_completer(text: str, state: int) -> Optional[str]:
                matches = [k for k in agent_keys if k.startswith(text)] + [k for k in agent_keys if text.lower() in k.lower() and not k.startswith(text)]
                if state < len(matches):
                    return matches[state]
                return None
            readline.set_completer(agent_sub_completer)

        try:
            choice = input("\nSelect an agent [# or name] (or press Enter to cancel): ").strip()
        except (KeyboardInterrupt, EOFError):
            return current_agent, config.resolve_session_id(str(workspace_root))
        finally:
            if readline and old_completer:
                readline.set_completer(old_completer)

        if not choice:
            return current_agent, config.resolve_session_id(str(workspace_root))

        choice_lower = choice.lower()
        if choice.isdigit() and 1 <= int(choice) <= len(agent_keys):
            target_agent = agent_keys[int(choice) - 1]
        elif choice_lower in AVAILABLE_AGENTS:
            target_agent = choice_lower
        else:
            for k, v in AVAILABLE_AGENTS.items():
                if choice_lower in v["title"].lower() or choice_lower in k:
                    target_agent = k
                    break

        if not target_agent:
            ui.console.print(f"[bold red]Invalid selection:[/] '{choice}'.")
            return current_agent, config.resolve_session_id(str(workspace_root))

    agent_info = AVAILABLE_AGENTS.get(target_agent, {})
    agent_title = agent_info.get("title", target_agent)
    agent_key_val = config.resolve_agent_api_key(target_agent)

    if not agent_key_val:
        ui.console.print(f"\n[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]")
        ui.console.print("[dim]Each agent is governed by a separate domain policy and requires its own Policy API Key.[/dim]")
        try:
            entered_key = input(f"Enter Policy API Key for {target_agent} (from SAFi Governance Portal): ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("[dim]Switch cancelled.[/dim]")
            return current_agent, config.resolve_session_id(str(workspace_root))

        if not entered_key:
            ui.console.print(f"[dim]Agent switch cancelled: no API key provided for {target_agent}.[/dim]")
            return current_agent, config.resolve_session_id(str(workspace_root))

        config.save_agent_api_key(target_agent, entered_key)
        agent_key_val = entered_key
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")

    client.api_key = agent_key_val
    new_conv = config.resolve_session_id(str(workspace_root), new_session=True, agent=target_agent)
    config.set_workspace_agent(str(workspace_root), target_agent, new_conv)
    ui.console.print(f"[bold green]✓ Switched active agent to:[/] [bold cyan]{target_agent}[/] ([green]{agent_title}[/])")
    ui.console.print(f"[dim]Started fresh session:[/] [cyan]{new_conv}[/]")
    return target_agent, new_conv


DEFAULT_MODELS = [
    {"id": "claude-3-5-sonnet", "label": "Claude 3.5 Sonnet", "provider": "Anthropic"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku", "provider": "Anthropic"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "provider": "Anthropic"},
    {"id": "gpt-4o", "label": "GPT-4o", "provider": "OpenAI"},
    {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "provider": "OpenAI"},
    {"id": "gpt-6-luna", "label": "GPT Luna", "provider": "OpenAI"},
    {"id": "gemini-3.5-flash-lite", "label": "Gemini Flash Lite", "provider": "Google"},
    {"id": "gemini-3.8-flash", "label": "Gemini Flash", "provider": "Google"},
    {"id": "deepseek-v4-flash", "label": "DeepSeek Flash", "provider": "DeepSeek"},
    {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B", "provider": "Groq"},
    {"id": "mistral-small-2603", "label": "Mistral Small", "provider": "Mistral"},
]

AVAILABLE_MODELS: List[Dict[str, Any]] = list(DEFAULT_MODELS)


def _infer_provider(model_id: str) -> str:
    m = model_id.lower()
    if "claude" in m or "anthropic" in m:
        return "Anthropic"
    if "gpt" in m or "openai" in m or "o1" in m or "o3" in m:
        return "OpenAI"
    if "gemini" in m or "gemma" in m:
        return "Google"
    if "deepseek" in m:
        return "DeepSeek"
    if "mistral" in m:
        return "Mistral"
    if "qwen" in m:
        return "Alibaba / Cerebras"
    if "groq" in m:
        return "Groq"
    if "glm" in m or "zhipu" in m:
        return "Zhipu (Z.ai)"
    return "Cloud Provider"


def discover_models(client: SafiClient, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Discover available AI models from the SAFi backend policy, updating cache."""
    global AVAILABLE_MODELS
    remote = client.get_available_models()
    if remote:
        seen = set()
        merged = []
        for m in remote:
            m_id = m.get("id") or m.get("model_id") or ""
            if m_id and m_id not in seen:
                seen.add(m_id)
                merged.append({
                    "id": m_id,
                    "label": m.get("label") or m.get("name") or m_id,
                    "provider": m.get("provider") or _infer_provider(m_id),
                    "active": bool(m.get("active")),
                    "local": bool(m.get("local")),
                })
        for m in DEFAULT_MODELS:
            if m["id"] not in seen:
                seen.add(m["id"])
                merged.append(m)
        AVAILABLE_MODELS = merged
    return AVAILABLE_MODELS


SERVING_MODEL_ALIASES = frozenset({"@serving", "serving", "auto", "@local", "@active"})


def is_serving_alias(value: Optional[str]) -> bool:
    """True when a model preference is the 'follow the served model' sentinel."""
    return bool(value) and value.strip().lower() in SERVING_MODEL_ALIASES


def serving_model_id(models: List[Dict[str, Any]]) -> Optional[str]:
    """Id of the served model within an available-models list, else None."""
    local_models = [m for m in (models or []) if str(m.get("provider") or "").lower() == "local"]
    for m in local_models:
        if m.get("active"):
            return m.get("id") or None
    if local_models:
        return local_models[0].get("id") or None
    return None


def discover_serving_model(client: SafiClient, force_refresh: bool = False) -> Optional[str]:
    """Fetch the available models and return the served local model's id."""
    return serving_model_id(discover_models(client, force_refresh=force_refresh))


def resolve_model_preference(
    client: SafiClient,
    agent: Optional[str] = None,
    explicit: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[str]:
    """Concrete Intellect model id for this session."""
    resolved = config.resolve_intellect_model(agent, explicit)
    if resolved and not is_serving_alias(resolved):
        return resolved
    serving = discover_serving_model(client, force_refresh=force_refresh)
    if serving:
        return serving
    if is_serving_alias(resolved):
        ui.console.print(
            f"[bold {ui.COLOR_WARN}]⚠ No locally-served model found on {client.api_url}; "
            "using the backend policy default.[/]"
        )
    return None


def prompt_switch_model(
    current_model: Optional[str],
    client: SafiClient,
    requested_model: Optional[str] = None,
    current_agent: Optional[str] = None,
) -> Optional[str]:
    """Interactively or directly select the LLM powering the Intellect faculty."""
    from rich.table import Table
    from rich import box

    models = discover_models(client)
    target_model = None

    if requested_model:
        req = requested_model.strip()
        for m in models:
            if req.lower() == m["id"].lower() or req.lower() == m["label"].lower():
                target_model = m["id"]
                break
        if not target_model:
            target_model = req
    else:
        table = Table(
            title="Available AI Models",
            box=box.ROUNDED,
            border_style=ui.COLOR_BRAND_600,
        )
        table.add_column("#", style=f"bold {ui.COLOR_WARN}", width=3, justify="right")
        table.add_column("Model ID", style=f"bold {ui.COLOR_BRAND_400}")
        table.add_column("Label / Name", style="bold white")
        table.add_column("Provider", style="dim")
        table.add_column("Status", justify="center")

        pref = config.resolve_intellect_model(current_agent)
        if not current_model and is_serving_alias(pref):
            pref = serving_model_id(models)
        resolved_active = current_model or pref or "(policy default)"

        for idx, m in enumerate(models, 1):
            is_active = (current_model and m["id"].lower() == current_model.lower()) or (
                not current_model and idx == 1
            )
            status_text = f"[bold {ui.COLOR_PASS}]✓ Active[/]" if is_active else ""
            table.add_row(
                str(idx),
                m["id"],
                m["label"],
                m.get("provider", "LLM"),
                status_text,
            )

        ui.console.print(table)
        ui.console.print(f"[dim]Current model:[/] [bold white]{resolved_active}[/]")
        ui.console.print("[dim]Enter number, model ID (or custom model name), or press Enter to cancel.[/dim]")

        old_completer = readline.get_completer() if readline else None
        if readline:
            model_ids = [m["id"] for m in models if "id" in m]
            def model_sub_completer(text: str, state: int) -> Optional[str]:
                matches = [m for m in model_ids if m.startswith(text)] + [m for m in model_ids if text.lower() in m.lower() and not m.startswith(text)]
                if state < len(matches):
                    return matches[state]
                return None
            readline.set_completer(model_sub_completer)

        try:
            choice = input("\nSelect model: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("[dim]Model selection cancelled.[/dim]")
            return current_model
        finally:
            if readline and old_completer:
                readline.set_completer(old_completer)

        if not choice:
            return current_model

        if choice.lower() in ("exit", "quit", "cancel", ":q", "/cancel"):
            ui.console.print("[dim]Model selection cancelled.[/dim]")
            return current_model

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                target_model = models[idx]["id"]
            else:
                ui.console.print(f"[bold {ui.COLOR_FAIL}]Invalid model number:[/] {choice}")
                return current_model
        else:
            choice_lower = choice.lower()
            for m in models:
                if choice_lower == m["id"].lower() or choice_lower in m["label"].lower():
                    target_model = m["id"]
                    break
            if not target_model:
                target_model = choice

    config.save_intellect_model(target_model, current_agent)
    if is_serving_alias(target_model):
        serving = serving_model_id(models)
        ui.console.print(
            f"[bold {ui.COLOR_PASS}]✓ AI now follows the served model:[/] "
            f"[bold {ui.COLOR_BRAND_400}]{serving or 'backend policy default'}[/]"
            + (f" [dim](for persona '{current_agent}')[/dim]" if current_agent else "")
        )
        return serving
    ui.console.print(
        f"[bold {ui.COLOR_PASS}]✓ Switched model to:[/] [bold {ui.COLOR_BRAND_400}]{target_model}[/]"
        + (f" [dim](for persona '{current_agent}')[/dim]" if current_agent else "")
    )
    return target_model


COMMAND_OPTIONS = [
    ("agents", "Switch Agent", "Select an agent (software_engineer, fiduciary, etc.)"),
    ("new", "New Session", "Start fresh conversation session without clearing screen"),
    ("clear", "Clear & Reset", "Wipe screen and start fresh session with cleared memory"),
    ("config", "View Configuration", "Show backend URL, active session, and Policy API keys"),
    ("help", "Help & Docs", "Show command descriptions and syntax"),
    ("exit", "Exit CLI", "Exit SAFi interactive assistant"),
    ("audit", "Governance Audit", "View full governance audit ledger and rationales for the last turn"),
    ("models", "Select Model", "Select the AI model powering the agent"),
    ("memory", "Working Memory", "View active memory or compact tokens (/memory compress)"),
    ("skills", "Project Skills", "List custom project skills defined in .safi/skills/"),
    ("user", "User Profile", "View or set your display name"),
    ("usage", "Session Usage", "Show session token, cost, and compaction totals"),
    ("last", "Last Tool Output", "Page through the full output of the most recent tool result"),
    ("compact-ui", "Toggle Audit Line", "Hide or show the compact governance audit line on responses"),
    ("sessions", "Manage Sessions", "List, name, or resume stored conversation sessions"),
]


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

    table = Table(title="Policy API Keys by Persona", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
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
        except Exception:
            pass
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
        except Exception:
            pass
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
        if _last_turn_result:
            ui.print_audit_details(_last_turn_result)
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
                ui.console.print("[dim]ℹ️ No active memory summary exists for this session yet. Run /memory compress to distill one, or continue chatting.[/dim]")
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
                except Exception:
                    pass
            exact = [c for c in commands if c.startswith(text)]
            sub = [c for c in commands if text.lower() in c.lower() and c not in exact]
            return exact + sub

        cmd = tokens[0].lower() if tokens else ""

        if cmd in ("/agent", "/agents", "/switch"):
            agent_keys = list(AVAILABLE_AGENTS.keys())
            exact = [k for k in agent_keys if k.startswith(text)]
            sub = [k for k in agent_keys if text.lower() in k.lower() and k not in exact]
            return exact + sub

        if cmd in ("/model", "/models"):
            model_ids = [m["id"] for m in AVAILABLE_MODELS if "id" in m]
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
        except Exception:
            return []

    return []


def setup_readline_completer(client: Optional[SafiClient] = None, workspace_root: Optional[Path] = None):
    """Configure readline auto-completion for slash commands, agent names, model names, and file paths."""
    if not readline:
        return

    try:
        readline.set_completer_delims(" \t\n")
    except Exception:
        pass

    try:
        if "libedit" in (getattr(readline, "__doc__", "") or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-query-items 0")
            readline.parse_and_bind("set page-completions off")
    except Exception:
        pass

    try:
        discover_agents(client)
    except Exception:
        pass

    cached: List[str] = []

    def cli_completer(text: str, state: int) -> Optional[str]:
        nonlocal cached
        if state == 0:
            try:
                line = readline.get_line_buffer()
                cached = _compute_completions(line, text, client, workspace_root)
            except Exception:
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
    ui.print_banner(
        str(workspace_root),
        current_agent,
        client.api_url,
        user_name=current_user_name,
        intellect_model=current_model,
    )
    ui.console.print(
        f"[dim]Commands: [bold {ui.COLOR_BRAND_400}]/[/] menu  •  [bold {ui.COLOR_BRAND_400}]/memory[/] memory & compact  •  [bold {ui.COLOR_BRAND_400}]/models[/] switch model  •  [bold {ui.COLOR_BRAND_400}]/agents[/] switch agent  •  [bold {ui.COLOR_BRAND_400}]/new[/] fresh session[/dim]"
    )
    rich_input = prompt_input.using_prompt_toolkit()
    if rich_input:
        ui.console.print(
            f"[dim]Tip: [bold {ui.COLOR_BRAND_400}]Enter[/] sends  •  "
            f"[bold {ui.COLOR_BRAND_400}]Alt+Enter[/] / [bold {ui.COLOR_BRAND_400}]Ctrl+J[/] add a line  •  "
            f"multi-line pastes just work.[/dim]\n"
        )
    else:
        ui.console.print(
            f"[dim]Tip: end a line with [bold {ui.COLOR_BRAND_400}]\\[/] to continue on the next line (multi-line prompts).[/dim]\n"
        )

    config.ensure_config_dir()
    hist_file = str(config.HISTORY_FILE)

    if readline:
        setup_readline_completer(client, workspace_root)
        if not rich_input and os.path.exists(hist_file):
            try:
                readline.read_history_file(hist_file)
            except OSError:
                pass

    current_conv = conversation_id
    try:
        while True:
            try:
                raw_line = prompt_input.read_prompt(
                    agent_label=current_agent,
                    completions_fn=None,
                    history_path=hist_file if rich_input else None,
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
                except Exception:
                    pass
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
                except Exception:
                    pass
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

            if line.lower() in ("/audit", "/ledger"):
                if _last_turn_result:
                    ui.print_audit_details(_last_turn_result)
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
                        ui.console.print("[dim]ℹ️ No active memory summary exists for this session yet. Run /memory compress to distill one, or continue chatting.[/dim]")
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

            if line.lower().strip() in ("/models", "/model", "/list-models"):
                current_model = prompt_switch_model(
                    current_model=current_model,
                    client=client,
                    current_agent=current_agent,
                )
                continue

            if line.lower().startswith(("/model ", "/models ")):
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
                    )
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
                lines_count = 0
                for idx_l, l_str in enumerate(input_lines):
                    prefix_len = prompt_vis_len if idx_l == 0 else len("  … ")
                    total_len = prefix_len + len(l_str)
                    lines_count += max(1, ((total_len - 1) // cols) + 1) if cols > 0 else 1
                for _ in range(lines_count):
                    sys.stdout.write("\033[F\033[2K")
                sys.stdout.flush()

            if is_serving_alias(config.resolve_intellect_model(current_agent)):
                current_model = resolve_model_preference(client, current_agent, force_refresh=True)

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
            )

    finally:
        try:
            config.set_workspace_agent(str(workspace_root), current_agent, current_conv)
        except Exception:
            pass
        if readline and not rich_input:
            try:
                readline.write_history_file(hist_file)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        prog="safi",
        description="SAFi (The Self-alignment Framework Interface) — The governance engine for AI agents.",
    )
    parser.add_argument("prompt", nargs="?", help="Task prompt. If omitted, starts interactive REPL mode.")
    parser.add_argument("-k", "--api-key", help="SAFi Policy API Key (defaults to SAFI_API_KEY env or config).")
    parser.add_argument("-u", "--api-url", help="SAFi backend URL (default: http://localhost:5000).")
    parser.add_argument("-a", "--agent", default=None, help="Agent persona (default: last used in workspace, or software_engineer).")
    parser.add_argument(
        "-m",
        "--model",
        help="AI model powering the agent (e.g. claude-3-5-sonnet, gpt-4o, gemini-2.5-flash). Use '@serving' to always follow the model the appliance is serving.",
    )

    parser.add_argument("-w", "--workspace", default=".", help="Workspace path (default: current directory).")
    parser.add_argument(
        "--confirm",
        "--require-approval",
        dest="require_approval",
        action="store_true",
        help="Prompt for developer confirmation before executing tools (default is auto-approve governed tools).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        dest="auto_approve",
        action="store_true",
        default=True,
        help="Auto-approve tool execution without prompting (enabled by default).",
    )
    parser.add_argument("-n", "--new", action="store_true", help="Start a new conversation session.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"Maximum tool loop iterations per turn (default: {DEFAULT_MAX_STEPS}).",
    )
    parser.add_argument("--set-key", help="Save the given API key to ~/.config/safi/config.json and exit.")
    parser.add_argument("--set-url", help="Save the given backend URL to ~/.config/safi/config.json and exit.")
    parser.add_argument(
        "--set-model",
        help="Save default AI model to ~/.config/safi/config.json and exit. Pass '@serving' to always follow the model the appliance is serving.",
    )
    parser.add_argument("--user-name", help="Display name of the user for the agent to address.")
    parser.add_argument("--set-user", help="Save the default user display name to ~/.config/safi/config.json and exit.")

    args = parser.parse_args()

    if args.set_user:
        config.save_user_name(args.set_user.strip())
        ui.console.print(f"[bold green]✓ Saved user name '{args.set_user.strip()}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_model:
        target_save_agent = args.agent if args.agent and args.agent != "software_engineer" else None
        config.save_intellect_model(args.set_model.strip(), target_save_agent)
        agent_note = f" for '{args.agent}'" if target_save_agent else " globally"
        ui.console.print(
            f"[bold green]✓ Saved default AI model '{args.set_model.strip()}'{agent_note} to {config.CONFIG_FILE}[/]"
        )
        sys.exit(0)

    if args.set_key:
        target_key_agent = args.agent or "software_engineer"
        config.save_agent_api_key(target_key_agent, args.set_key.strip())
        ui.console.print(f"[bold green]✓ Saved Policy API key for '{target_key_agent}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_url:
        new_url = args.set_url.strip().rstrip("/")
        config.save_config({"api_url": new_url})
        ui.console.print(f"[bold green]✓ Saved API URL to {config.CONFIG_FILE}[/]")
        test_client = SafiClient(new_url)
        discovered = discover_agents(test_client)
        ui.console.print(f"[dim]Backend {new_url}: discovered {len(discovered)} available agent persona(s).[/dim]")
        sys.exit(0)

    workspace_root = Path(args.workspace).resolve()
    target_agent = args.agent or config.get_workspace_agent(str(workspace_root)) or "software_engineer"

    api_url = config.resolve_api_url(args.api_url)
    api_key = config.resolve_agent_api_key(target_agent, args.api_key)
    user_name = config.resolve_user_name(args.user_name)

    client = SafiClient(api_url, api_key or "")
    discover_agents(client)

    if not api_key:
        agent_title = AVAILABLE_AGENTS.get(target_agent, {}).get("title", target_agent)
        ui.console.print(
            f"[bold yellow]🔑 No Policy API Key found for '{agent_title}' ({target_agent}).[/]\n"
            f"[dim]Each agent persona is governed by its own domain policy and requires its own Policy API Key.[/dim]"
        )
        try:
            api_key = input(f"Enter Policy API Key for {target_agent} (from SAFi Governance Portal): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(1)
        if not api_key:
            ui.print_error(
                f"No SAFi Policy API key provided for '{target_agent}'.\n\n"
                "You can also set it via:\n"
                f"  • export SAFI_API_KEY_{target_agent.upper()}=sk-safi-...\n"
                f"  • safi --set-key sk-safi-... -a {target_agent}"
            )
            sys.exit(1)
        config.save_agent_api_key(target_agent, api_key)
        client.api_key = api_key
        ui.console.print(f"[bold green]✓ Saved Policy API Key for {target_agent} to {config.CONFIG_FILE}[/]")
        discover_agents(client)

    intellect_model = resolve_model_preference(client, target_agent, args.model)

    conv_id = config.resolve_session_id(str(workspace_root), new_session=args.new, agent=target_agent)
    config.set_workspace_agent(str(workspace_root), target_agent, conv_id)
    user_id = config.resolve_user_id()
    if args.new:
        try:
            client.clear_agent_memory(conv_id, user_id=user_id, agent=target_agent)
        except Exception:
            pass
    auto_approve = not args.require_approval

    if args.prompt:
        ui.print_banner(str(workspace_root), target_agent, api_url, user_name=user_name, intellect_model=intellect_model)
        run_agent_turn(
            client=client,
            prompt=args.prompt,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=target_agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )
    else:
        interactive_repl(
            client=client,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=target_agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )


if __name__ == "__main__":
    main()
