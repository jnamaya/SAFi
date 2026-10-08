import argparse
import glob
import os
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

from . import config, tools, ui
from .client import SafiClient, SafiClientError


DEFAULT_MAX_STEPS = 25
_last_turn_result: Optional[Dict[str, Any]] = None


def run_subagent_task(
    client: SafiClient,
    args: Dict[str, Any],
    workspace_root: Path,
    parent_conv_id: str,
    user_id: str,
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

    ui.print_subagent_start(subagent_type, description)

    # Monotonic Confinement: Map role to strictly permitted tools and instructions
    if subagent_type == "researcher":
        allowed_tool_names = ("read", "grep", "glob", "list")
        role_prompt = (
            "You are a focused, read-only Research Subagent for SAFi. "
            "Your objective is to inspect repository files, search patterns, and return a concise, factual summary of findings. "
            "Do NOT propose write, edit, delete, or bash commands. Be specific with file paths and line numbers."
        )
    elif subagent_type == "tester":
        allowed_tool_names = ("bash", "read")
        role_prompt = (
            "You are a focused Test Runner Subagent for SAFi. "
            "Run relevant test commands using 'bash', inspect results, and report pass/fail status and failure causes."
        )
    elif subagent_type == "code_reviewer":
        allowed_tool_names = ("read", "grep", "list")
        role_prompt = (
            "You are a Code Review Subagent for SAFi. "
            "Inspect files to identify bugs, potential edge cases, security flaws, or architectural discrepancies."
        )
    else:
        allowed_tool_names = ("read", "grep", "glob", "list")
        role_prompt = f"You are a specialized subagent for SAFi focused on: {subagent_type}."

    child_tools = [t for t in tools.TOOL_SCHEMAS if t["function"]["name"] in allowed_tool_names]
    # Database enforces CONVERSATION_ID_MAX_LEN = 36. Keep prefix for lineage while guaranteeing <= 36 chars.
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
                agent="software_engineer",
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
            t_name = res.get("tool_name", "")
            t_args = res.get("parameters") or {}

            # Strict role sub-policy enforcement
            if t_name not in allowed_tool_names:
                blocked_msg = f"Rejected: Subagent role '{subagent_type}' is restricted and not permitted to execute '{t_name}'."
                ui.print_subagent_step(subagent_type, t_name, t_args, "Blocked by role sub-policy")
                child_tool_results.append({
                    "tool_name": t_name,
                    "arguments": t_args,
                    "result": blocked_msg,
                })
                continue

            t_out = tools.execute_tool(t_name, t_args, workspace_root)
            last_snippet = t_out[:200]
            ui.print_subagent_step(subagent_type, t_name, t_args, t_out)
            child_tool_results.append({
                "tool_name": t_name,
                "arguments": t_args,
                "result": t_out,
            })
            continue

        # Terminal answer reached
        final_out = res.get("finalOutput") or ""
        ui.print_subagent_done(subagent_type, final_out, steps=step + 1)
        return f"Subagent ({subagent_type}) findings for '{description}':\n{final_out}"

    fallback_out = f"Subagent ({subagent_type}) reached iteration limit ({max_steps}). Summary: {last_snippet}"
    ui.print_subagent_done(subagent_type, fallback_out, steps=max_steps)
    return fallback_out


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

    try:
        for step in range(max_steps):
            turn_msg_id = str(uuid.uuid4())
            try:
                with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Governing turn...[/]", spinner="dots") as status_indicator:
                    stop_poller = threading.Event()
                    start_time = time.time()

                    def _poll_progress():
                        current_step_text = "Governing turn"
                        while not stop_poller.wait(0.3):
                            try:
                                progress_data = client.get_turn_progress(turn_msg_id, user_id=user_id)
                                if isinstance(progress_data, dict):
                                    raw_step = progress_data.get("latest_step")
                                    if raw_step:
                                        current_step_text = raw_step.rstrip(".…").strip()
                            except Exception:
                                pass
                            elapsed = time.time() - start_time
                            step_lower = current_step_text.lower()
                            if step_lower.startswith("drafting"):
                                model_suffix = f" with {model}" if model else ""
                                status_indicator.update(
                                    f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Drafting response{model_suffix}...[/] [dim]({elapsed:.1f}s)[/]"
                                )
                            else:
                                status_indicator.update(
                                    f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]{current_step_text}...[/] [dim]({elapsed:.1f}s)[/]"
                                )

                    poller = threading.Thread(target=_poll_progress, daemon=True)
                    poller.start()
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
                            message_id=turn_msg_id,
                        )
                    finally:
                        stop_poller.set()
                        poller.join(timeout=0.3)
            except SafiClientError as err:
                ui.print_error(str(err))
                return None

            # Handle tool call proposal
            if res.get("type") == "tool_call":
                tool_name = res.get("tool_name", "")
                args = res.get("parameters") or {}
                will_decision = res.get("willDecision", "approved")
                will_reason = res.get("willReason")

                ui.print_tool_proposal(tool_name, args, res)

                # If WillGate blocked the proposal, SAFi does not expect client execution
                if will_decision not in ("approve", "approved"):
                    tool_results.append({
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": f"The Will Gatekeeper rejected '{tool_name}' ({will_reason}).",
                    })
                    continue

                # Subagent delegation (task / delegate_subagent)
                if tool_name in ("task", "delegate_subagent"):
                    subagents_run_count += 1
                    result_str = run_subagent_task(
                        client=client,
                        args=args,
                        workspace_root=workspace_root,
                        parent_conv_id=conversation_id,
                        user_id=user_id,
                        model=model,
                        max_steps=6,
                    )
                    # If the agent has run 2 or more subagents in this turn, advise it to finalize
                    if subagents_run_count >= 2:
                        result_str += (
                            "\n\n[System note: Delegation budget reached (2 subagents executed). "
                            "Please synthesize the available findings into your final answer now "
                            "instead of delegating further.]"
                        )
                    tool_results.append({
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": result_str,
                    })
                    continue

                # Interactive developer clarification tool (question / ask_user)
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
                    continue

                # Plan & task list tracking tool (todowrite)
                if tool_name in ("todowrite", "todo_write"):
                    todos = args.get("todos") or []
                    ui.render_todo_list(todos)
                    total = len(todos)
                    completed = sum(1 for t in todos if (t.get("status") or "").lower() in ("completed", "done"))
                    pct = int((completed / total) * 100) if total > 0 else 0
                    res_msg = f"Recorded plan with {total} task(s) ({completed}/{total} completed • {pct}%)."
                    ui.print_tool_result_summary(tool_name, res_msg)
                    tool_results.append({
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": res_msg,
                    })
                    continue

                # Server-executed tool (e.g. fiduciary stock tools, web search)
                if res.get("executed_by") == "server" or "result" in res:
                    result_str = str(res.get("result", ""))
                    ui.print_tool_result_summary(tool_name, result_str)
                    tool_results.append({
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": result_str,
                    })
                    continue

                # Permission check for mutating/shell tools
                allowed = ui.prompt_user_permission(tool_name, args, auto_approve=auto_approve)
                if not allowed:
                    result_str = f"Execution of '{tool_name}' was declined by the developer."
                else:
                    result_str = tools.execute_tool(tool_name, args, workspace_root)
                    ui.print_tool_result_summary(tool_name, result_str)

                tool_results.append({
                    "tool_name": tool_name,
                    "arguments": args,
                    "result": result_str,
                })
                continue

            # Terminal answer reached
            final_text = res.get("finalOutput") or ""

            # Display any server-executed tool calls not already displayed step-by-step
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

        ui.print_error(f"Reached maximum tool loop iterations ({max_steps}).")
        return None
    except KeyboardInterrupt:
        ui.console.print("\n[bold yellow]Turn cancelled (Ctrl+C).[/bold yellow]")
        return None


DEFAULT_AGENTS = {
    "software_engineer": {
        "title": "Software Engineer",
        "description": "Direct, audited repository engineering & software development",
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

    # Check Policy API key for target_agent
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
    new_conv = config.resolve_session_id(str(workspace_root), new_session=True)
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
    return "Cloud Provider"


def discover_models(client: SafiClient) -> List[Dict[str, Any]]:
    """Discover available AI models from the SAFi backend policy, caching results."""
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
                })
        for m in DEFAULT_MODELS:
            if m["id"] not in seen:
                seen.add(m["id"])
                merged.append(m)
        AVAILABLE_MODELS = merged
    return AVAILABLE_MODELS


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
            title="Available Intellect AI Models",
            box=box.ROUNDED,
            border_style=ui.COLOR_BRAND_600,
        )
        table.add_column("#", style=f"bold {ui.COLOR_WARN}", width=3, justify="right")
        table.add_column("Model ID", style=f"bold {ui.COLOR_BRAND_400}")
        table.add_column("Label / Name", style="bold white")
        table.add_column("Provider", style="dim")
        table.add_column("Status", justify="center")

        resolved_active = current_model or config.resolve_intellect_model(current_agent) or "(policy default)"

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
        ui.console.print(f"[dim]Current Intellect model:[/] [bold white]{resolved_active}[/]")
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
            choice = input("\nSelect Intellect model: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.console.print("[dim]Model selection cancelled.[/dim]")
            return current_model
        finally:
            if readline and old_completer:
                readline.set_completer(old_completer)

        if not choice:
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
    ui.console.print(
        f"[bold {ui.COLOR_PASS}]✓ Switched Intellect AI model to:[/] [bold {ui.COLOR_BRAND_400}]{target_model}[/]"
        + (f" [dim](for persona '{current_agent}')[/dim]" if current_agent else "")
    )
    return target_model


COMMAND_OPTIONS = [
    ("agents", "Switch Agent", "Select an agent (software_engineer, fiduciary, etc.)"),
    ("new", "New Session", "Start a fresh conversation session with a new session ID"),
    ("clear", "Clear Screen", "Clear the terminal screen and reprint the session header"),
    ("config", "View Configuration", "Show backend URL, active session, and Policy API keys"),
    ("help", "Help & Docs", "Show command descriptions and syntax"),
    ("exit", "Exit CLI", "Exit SAFi interactive assistant"),
    ("audit", "Conscience Audit", "View full conscience audit ledger and rationales for the last turn"),
    ("models", "Intellect Model", "Select the LLM powering the agent's Intellect faculty"),
    ("compress", "Compress Context", "Compact conversation history and save tokens"),
    ("skills", "Project Skills", "List custom project skills defined in .safi/skills/"),
    ("user", "User Profile", "View or set your display name"),
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
    resolved_model = current_model or config.resolve_intellect_model(current_agent) or "(policy default)"
    ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]● SAFi CLI Configuration[/]")
    ui.console.print(f"  [dim]Backend URL:[/]     {client.api_url}")
    ui.console.print(f"  [dim]Workspace:[/]       {workspace_root}")
    ui.console.print(f"  [dim]Active Agent:[/]    [bold {ui.COLOR_BRAND_500}]{current_agent}[/]")
    ui.console.print(f"  [dim]Intellect Model:[/] [bold {ui.COLOR_BRAND_400}]{resolved_model}[/]")
    ui.console.print(f"  [dim]Active Session:[/]  [dim]{current_conv}[/]")
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
    from rich.table import Table
    from rich import box

    table = Table(title="Available Slash Commands", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
    table.add_column("Command", style=f"bold {ui.COLOR_BRAND_400}")
    table.add_column("Description", style="dim white")

    commands = [
        ("/", "Open interactive command menu"),
        ("/agents", "Interactive agent selector & Policy API key status"),
        ("/agent <name>", "Switch directly to an agent (e.g. /agent fiduciary)"),
        ("/models", "Select the LLM powering the Intellect faculty"),
        ("/model <name>", "Switch directly to an Intellect LLM (e.g. /model gpt-4o)"),
        ("/compress", "Compact conversation history and save tokens (OpenCode style)"),
        ("/audit", "View detailed conscience audit ledger & rationales for the last turn"),
        ("/skills", "List custom project skills defined in .safi/skills/"),
        ("/user <name>", "View or update your user display name"),
        ("/new", "Start a fresh conversation session with a new session ID"),
        ("/clear", "Clear the terminal screen and reprint the session header"),
        ("/config", "View backend URL, active model, and Policy API key status"),
        ("/help", "Show this help menu"),
        ("exit, quit, :q", "Exit SAFi CLI"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    ui.console.print(table)


def prompt_command_menu(
    current_agent: str,
    client: SafiClient,
    workspace_root: Path,
    current_conv: str,
    current_model: Optional[str] = None,
    user_id: str = "cli_user",
) -> tuple[str, str, bool]:
    """Display the interactive slash command menu when the user types '/'."""
    from rich.table import Table
    from rich import box

    table = Table(title="SAFi Command Menu", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
    table.add_column("#", style=f"bold {ui.COLOR_WARN}", width=3, justify="right")
    table.add_column("Command", style=f"bold {ui.COLOR_BRAND_400}")
    table.add_column("Action", style="bold white")
    table.add_column("Description", style="dim")

    for idx, (cmd, action, desc) in enumerate(COMMAND_OPTIONS, 1):
        table.add_row(str(idx), f"/{cmd}", action, desc)

    ui.console.print()
    ui.console.print(table)

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
        return current_agent, current_conv, False
    finally:
        if readline and old_completer:
            readline.set_completer(old_completer)

    if not choice:
        return current_agent, current_conv, False

    choice_clean = choice.lstrip("/").lower().strip()

    # Map number choice to command
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
        return new_agent, new_conv, False

    elif choice_clean == "new":
        new_conv = config.resolve_session_id(str(workspace_root), new_session=True)
        ui.reset_session_telemetry()
        ui.clear_active_todos()
        ui.console.print(f"[bold {ui.COLOR_PASS}]Started new conversation session:[/] [dim]{new_conv}[/]")
        return current_agent, new_conv, False

    elif choice_clean == "clear":
        os.system("cls" if os.name == "nt" else "clear")
        ui.print_banner(str(workspace_root), current_agent, client.api_url, intellect_model=current_model)
        return current_agent, current_conv, False

    elif choice_clean in ("config", "keys"):
        show_config(client, workspace_root, current_agent, current_conv, current_model=current_model)
        return current_agent, current_conv, False

    elif choice_clean in ("audit", "ledger"):
        if _last_turn_result:
            ui.print_audit_details(_last_turn_result)
        else:
            ui.console.print(f"[{ui.COLOR_WARN}]No recent turn audit available yet. Run a prompt first.[/]")
        return current_agent, current_conv, False

    elif choice_clean in ("models", "model"):
        prompt_switch_model(
            current_model=current_model,
            client=client,
            current_agent=current_agent,
        )
        return current_agent, current_conv, False

    elif choice_clean in ("compress", "summarize", "compact"):
        with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Compressing conversation tokens...[/]", spinner="dots"):
            comp_res = client.compress_conversation(
                current_conv,
                user_id=user_id,
                agent=current_agent,
                model=current_model,
                action="compress",
            )
        ui.print_compression_result(comp_res)
        return current_agent, current_conv, False

    elif choice_clean in ("skills", "skill"):
        from .skills import discover_skills
        local_skills = discover_skills(workspace_root)
        s_table = Table(title="Custom Project Skills (.safi/skills/)", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
        s_table.add_column("Command", style=f"bold {ui.COLOR_BRAND_400}")
        s_table.add_column("Description", style="white")
        s_table.add_column("Path", style="dim")
        if local_skills:
            for s_name, s_obj in local_skills.items():
                s_table.add_row(f"/{s_name}", s_obj.description, str(s_obj.file_path.relative_to(workspace_root)))
            ui.console.print(s_table)
        else:
            ui.console.print(f"[dim]No custom skills found in {workspace_root / '.safi' / 'skills'}. Create a .md file there to add skills![/dim]")
        return current_agent, current_conv, False

    elif choice_clean in ("user", "name"):
        try:
            curr = config.resolve_user_name() or "Unset"
            new_name = input(f"Enter user name (currently '{curr}'): ").strip()
            if new_name:
                config.save_user_name(new_name)
                ui.console.print(f"[bold {ui.COLOR_PASS}]✓ User name updated to:[/] [magenta]{new_name}[/]")
        except (KeyboardInterrupt, EOFError):
            pass
        return current_agent, current_conv, False

    elif choice_clean in ("help", "?"):
        print_help()
        return current_agent, current_conv, False

    elif choice_clean in ("exit", "quit", ":q"):
        ui.console.print("[dim]Goodbye.[/dim]")
        return current_agent, current_conv, True

    else:
        ui.console.print(f"[bold {ui.COLOR_FAIL}]Unknown command:[/] '{choice}'. Type [bold]/[/] to see options.")
        return current_agent, current_conv, False


SLASH_COMMANDS = [
    "/agents",
    "/agent",
    "/models",
    "/model",
    "/compress",
    "/skills",
    "/audit",
    "/ledger",
    "/user",
    "/name",
    "/new",
    "/clear",
    "/config",
    "/keys",
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

    # 1. Slash commands & arguments
    if line_clean.startswith("/"):
        tokens = line_clean.split()

        # If user is still typing the command itself (no space typed yet or cursor on first token)
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

        # Auto-complete Agent personas: /agent <tab> or /agents <tab> or /switch <tab>
        if cmd in ("/agent", "/agents", "/switch"):
            agent_keys = list(AVAILABLE_AGENTS.keys())
            exact = [k for k in agent_keys if k.startswith(text)]
            sub = [k for k in agent_keys if text.lower() in k.lower() and k not in exact]
            return exact + sub

        # Auto-complete Models: /model <tab> or /models <tab>
        if cmd in ("/model", "/models"):
            model_ids = [m["id"] for m in AVAILABLE_MODELS if "id" in m]
            exact = [m for m in model_ids if m.startswith(text)]
            sub = [m for m in model_ids if text.lower() in m.lower() and m not in exact]
            return exact + sub

        # Auto-complete Compress subcommands: /compress <tab>
        if cmd in ("/compress", "/compact", "/summarize"):
            subcommands = ["compress", "show", "clear", "status", "view"]
            return [sc for sc in subcommands if sc.startswith(text)]

        return []

    # 2. General workspace file path auto-completion
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

    # Use whitespace only as delimiters so slashes, hyphens, and paths are not truncated
    try:
        readline.set_completer_delims(" \t\n")
    except Exception:
        pass

    # Bind Tab key for completion (GNU readline on Linux, libedit on macOS)
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
    current_model = model or config.resolve_intellect_model(current_agent)
    ui.print_banner(
        str(workspace_root),
        current_agent,
        client.api_url,
        user_name=current_user_name,
        intellect_model=current_model,
    )
    ui.console.print(
        f"[dim]Commands: [bold {ui.COLOR_BRAND_400}]/[/] menu  •  [bold {ui.COLOR_BRAND_400}]/compress[/] compact tokens  •  [bold {ui.COLOR_BRAND_400}]/models[/] intellect model  •  [bold {ui.COLOR_BRAND_400}]/agents[/] switch agent  •  [bold {ui.COLOR_BRAND_400}]/new[/] fresh session[/dim]\n"
    )

    # Setup readline history & auto-completer
    config.ensure_config_dir()
    hist_file = str(config.HISTORY_FILE)
    if readline and os.path.exists(hist_file):
        try:
            readline.read_history_file(hist_file)
        except OSError:
            pass

    if readline:
        setup_readline_completer(client, workspace_root)

    current_conv = conversation_id
    try:
        while True:
            try:
                prompt_label = ui.get_input_prompt(agent=current_agent, user_name=current_user_name)
                line = input(prompt_label).strip()
            except (KeyboardInterrupt, EOFError):
                ui.console.print("\n[dim]Session terminated.[/dim]")
                break

            if not line:
                continue
            if line.lower() in ("exit", "quit", ":q", "/exit", "/quit"):
                ui.console.print("[dim]Goodbye.[/dim]")
                break

            if line.lower() in ("/", "/menu", "/commands", "menu"):
                current_agent, current_conv, should_exit = prompt_command_menu(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                    current_conv=current_conv,
                    current_model=current_model,
                    user_id=user_id,
                )
                current_model = config.resolve_intellect_model(current_agent, current_model)
                if should_exit:
                    break
                continue

            if line.lower() == "/new":
                current_conv = config.resolve_session_id(str(workspace_root), new_session=True)
                ui.reset_session_telemetry()
                ui.clear_active_todos()
                ui.console.print(f"[bold green]Started new conversation session:[/] [cyan]{current_conv}[/]")
                continue

            if line.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                ui.print_banner(
                    str(workspace_root),
                    current_agent,
                    client.api_url,
                    user_name=current_user_name,
                    intellect_model=current_model,
                )
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

            if line.lower().startswith(("/compress", "/summarize", "/compact")):
                parts = line.split(maxsplit=1)
                sub_arg = parts[1].strip().lower() if len(parts) > 1 else "compress"
                if sub_arg in ("show", "view", "get", "status"):
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Fetching active memory summary...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="get")
                    if comp_res.get("summary"):
                        ui.print_compression_result({"ok": True, "compressed": False, "summary": comp_res["summary"], "message": "Showing active memory summary."})
                    else:
                        ui.console.print("[dim]ℹ️ No active memory summary exists for this session yet. Run /compress to generate one.[/dim]")
                elif sub_arg in ("clear", "reset"):
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Clearing memory summary...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="clear")
                    ui.record_compression_reset()
                    ui.console.print(f"[bold {ui.COLOR_PASS}]✓ Compacted memory summary cleared.[/]")
                else:
                    with ui.console.status(f"[bold {ui.COLOR_BRAND_400}]● SAFi[/] [dim]Compressing conversation tokens...[/]", spinner="dots"):
                        comp_res = client.compress_conversation(current_conv, user_id=user_id, agent=current_agent, model=current_model, action="compress")
                    if comp_res.get("ok") and comp_res.get("compressed"):
                        ui.record_compression_telemetry(
                            tokens_before=comp_res.get("tokens_before", 0),
                            tokens_after=comp_res.get("tokens_after", 0),
                            tokens_saved=comp_res.get("tokens_saved", 0),
                            reduction_pct=comp_res.get("reduction_pct", 0.0),
                            intellect_model=current_model,
                        )
                    ui.print_compression_result(comp_res)
                continue

            if line.lower().strip() in ("/agents", "/agent", "/switch", "/list-agents"):
                current_agent, current_conv = prompt_switch_agent(
                    current_agent=current_agent,
                    client=client,
                    workspace_root=workspace_root,
                )
                current_model = config.resolve_intellect_model(current_agent)
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
                current_model = config.resolve_intellect_model(current_agent)
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

            if line.lower() in ("/help", "/?", "help", "?"):
                print_help()
                continue

            # Local project skills (.safi/skills/<name>.md) or slash command dispatch
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
                    from rich.table import Table
                    from rich import box
                    s_table = Table(title="Custom Project Skills (.safi/skills/)", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
                    s_table.add_column("Command", style=f"bold {ui.COLOR_BRAND_400}")
                    s_table.add_column("Description", style="white")
                    s_table.add_column("Path", style="dim")
                    if local_skills:
                        for s_name, s_obj in local_skills.items():
                            s_table.add_row(f"/{s_name}", s_obj.description, str(s_obj.file_path.relative_to(workspace_root)))
                        ui.console.print(s_table)
                    else:
                        ui.console.print(f"[dim]No custom skills found in {workspace_root / '.safi' / 'skills'}. Create a .md file there to add skills![/dim]")
                    continue
                else:
                    ui.console.print(f"[bold {ui.COLOR_FAIL}]Unknown command:[/] '{line}'. Type [bold]/[/] to see options.")
                    continue


            if sys.stdout.isatty():
                cols = shutil.get_terminal_size((80, 24)).columns
                prompt_vis_len = len(f" SAFi [{current_agent}] › ")
                total_len = prompt_vis_len + len(line)
                lines_count = max(1, ((total_len - 1) // cols) + 1) if cols > 0 else 1
                for _ in range(lines_count):
                    sys.stdout.write("\033[F\033[2K")
                sys.stdout.flush()

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
        if readline:
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
    parser.add_argument("-a", "--agent", default="software_engineer", help="Agent persona (default: software_engineer).")
    parser.add_argument(
        "-m",
        "--model",
        help="LLM model powering the Intellect faculty (e.g. claude-3-5-sonnet, claude-haiku-5-5, gpt-4o, gemini-3.5-flash-lite).",
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
        help="Save default Intellect AI model to ~/.config/safi/config.json and exit.",
    )
    parser.add_argument("--user-name", help="Display name of the user for the agent to address.")
    parser.add_argument("--set-user", help="Save the default user display name to ~/.config/safi/config.json and exit.")

    args = parser.parse_args()

    # Save user / model / key / URL commands
    if args.set_user:
        config.save_user_name(args.set_user.strip())
        ui.console.print(f"[bold green]✓ Saved user name '{args.set_user.strip()}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_model:
        target_save_agent = args.agent if args.agent != "software_engineer" else None
        config.save_intellect_model(args.set_model.strip(), target_save_agent)
        agent_note = f" for '{args.agent}'" if target_save_agent else " globally"
        ui.console.print(
            f"[bold green]✓ Saved default Intellect AI model '{args.set_model.strip()}'{agent_note} to {config.CONFIG_FILE}[/]"
        )
        sys.exit(0)

    if args.set_key:
        config.save_agent_api_key(args.agent, args.set_key.strip())
        ui.console.print(f"[bold green]✓ Saved Policy API key for '{args.agent}' to {config.CONFIG_FILE}[/]")
        sys.exit(0)

    if args.set_url:
        new_url = args.set_url.strip().rstrip("/")
        config.save_config({"api_url": new_url})
        ui.console.print(f"[bold green]✓ Saved API URL to {config.CONFIG_FILE}[/]")
        test_client = SafiClient(new_url)
        discovered = discover_agents(test_client)
        ui.console.print(f"[dim]Backend {new_url}: discovered {len(discovered)} available agent persona(s).[/dim]")
        sys.exit(0)

    # Resolve settings for the targeted agent and backend URL
    api_url = config.resolve_api_url(args.api_url)
    target_agent = args.agent
    api_key = config.resolve_agent_api_key(target_agent, args.api_key)
    user_name = config.resolve_user_name(args.user_name)
    intellect_model = config.resolve_intellect_model(target_agent, args.model)

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

    workspace_root = Path(args.workspace).resolve()
    conv_id = config.resolve_session_id(str(workspace_root), new_session=args.new)
    user_id = f"cli_{os.getlogin() if hasattr(os, 'getlogin') else 'user'}"
    auto_approve = not args.require_approval

    if args.prompt:
        # Single-shot command
        ui.print_banner(str(workspace_root), args.agent, api_url, user_name=user_name, intellect_model=intellect_model)
        run_agent_turn(
            client=client,
            prompt=args.prompt,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=args.agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )
    else:
        # Interactive mode
        interactive_repl(
            client=client,
            workspace_root=workspace_root,
            conversation_id=conv_id,
            user_id=user_id,
            agent=args.agent,
            user_name=user_name,
            model=intellect_model,
            auto_approve=auto_approve,
            max_steps=args.max_steps,
        )


if __name__ == "__main__":
    main()
