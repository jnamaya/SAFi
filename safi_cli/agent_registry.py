"""Agent and model discovery/selection shared by the REPL and entrypoint."""

import glob
import logging
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

logger = logging.getLogger("safi.main")


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
    except Exception as exc:
        logger.warning("Agent discovery from backend failed: %s", exc)

    return AVAILABLE_AGENTS


def prompt_switch_agent(
    current_agent: str,
    client: SafiClient,
    workspace_root: Path,
    requested_agent: Optional[str] = None,
) -> tuple[str, str]:
    """Interactively select or switch to an agent, prompting for its Policy API key if not yet configured."""
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
            ui.console.print(f"[bold red]Unknown agent:[/] [yellow]'{requested_agent}'[/]. Use [bold]/[/] to see available options.")
            return current_agent, config.resolve_session_id(str(workspace_root))

    if not target_agent:
        backend_tag = f" ({client.api_url})" if getattr(client, "api_url", None) else ""
        table = Table(title=f"Available SAFi Agents{backend_tag}", box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
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


SERVING_MODEL_ALIASES = frozenset({"local", "@local", "serving", "@serving", "auto", "@active"})


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
        if is_serving_alias(req):
            target_model = "local"
        else:
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
        ui.console.print("[dim]Enter number, model ID, or type [bold cyan]local[/] to follow the served model.[/dim]")

        old_completer = readline.get_completer() if readline else None
        if readline:
            model_ids = [m["id"] for m in models if "id" in m] + ["local"]
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
            if is_serving_alias(choice_lower):
                target_model = "local"
            else:
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
            f"[bold {ui.COLOR_PASS}]✓ AI now follows the local served model:[/] "
            f"[bold {ui.COLOR_BRAND_400}]{serving or 'backend policy default'}[/]"
            + (f" [dim](for agent '{current_agent}')[/dim]" if current_agent else "")
        )
        return serving
    ui.console.print(
        f"[bold {ui.COLOR_PASS}]✓ Switched model to:[/] [bold {ui.COLOR_BRAND_400}]{target_model}[/]"
        + (f" [dim](for agent '{current_agent}')[/dim]" if current_agent else "")
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
    ("setup-key", "Deploy SSH Key", "Deploy SSH public key to Linux or Windows target server"),
]


