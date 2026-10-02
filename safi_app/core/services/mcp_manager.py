"""
MCP Manager: the tool catalogue, the per-agent schemas, and dispatch.

Two kinds of tool arrive here and they are not the same thing:

  * BUILT-IN CONNECTORS (core/mcp_servers/*.py) are curated. Someone wrote the
    module, hand-wrote the schema, and shipped it in the image, so the tool list
    is reviewed at build time. Several of them act on a MEMBER's behalf using
    delegated per-user OAuth, which is why they take user_id.

  * DISCOVERED MCP SERVERS (core/mcp_runtime.py) are installed by the operator
    in the file MCP_SERVERS_JSON names, and their schemas come from a third
    party at runtime, reviewed by nobody. They authenticate with the
    deployment's own credential, which makes each one a service principal.

That difference decides what each is FOR, and it belongs in the docs an
organization reads: a shared or system resource (a company API, an internal
pricing service) is right for an MCP server; a member's own mailbox or files
belong on per-user authorization (the OAuth MCP path or a delegated
connector), or every read in the source system's audit log is attributed to
SAFi rather than to a person, and offboarding stops cutting access.

What is NOT different is the governance. A discovered server becomes a
connector like any other (tool_connectors.py), an organization allows it
(connector_governance.py), a policy grants it, Synderesis expands it into
allowed_tools, and the Will authorizes every individual call by exact name.
Discovery adds catalogue entries and changes no rule. See GOVERNANCE_BACKLOG 47b.

Session lifecycle lives in mcp_runtime, not here, and deliberately: a SAFi
orchestrator (and so an MCPManager) is built per cached agent profile, while MCP
sessions must be one per process.
"""
import asyncio
import logging
import json
import os
from typing import List, Dict, Any, Optional

from .. import mcp_runtime
from ..tool_connectors import (
    CONNECTOR_TOOLS,
    clear_discovered_connectors,
    register_discovered_connector,
)

log = logging.getLogger(__name__)


def coding_harness_declaration_only() -> frozenset:
    """Names the coding_harness connector declares but SAFi does not execute.

    Harness vocabulary minus the four repository tools implemented in
    core/mcp_servers/coding_harness.py. Kept as a helper rather than inlined so
    dispatch and the catalog agree on the split from one definition.
    """
    from ..mcp_servers.coding_harness import (
        CODING_HARNESS_TOOL_NAMES, SAFI_EXECUTED_TOOLS,
    )
    return frozenset(CODING_HARNESS_TOOL_NAMES) - SAFI_EXECUTED_TOOLS



def is_guest(user_id: str = "", email: str = "") -> bool:
    """A demo/sandbox account, created by the public demo login.

    Guests are made ADMIN of a throwaway organization (api/auth.py), which is
    fine for exploring the product and is NOT a basis for reaching a tool server
    the operator installed. Being an admin of a sandbox is not being an admin of
    this deployment, and an MCP server holds one real credential.
    """
    uid = (user_id or "").lower()
    mail = (email or "").lower()
    return uid.startswith("demo_") or mail.endswith("@demo.local")


def server_allows_org(server: str, org_id: Optional[str]) -> bool:
    """Whether an organization may use a given installed server.

    A server definition may carry `"orgs": ["<org-id>", ...]`. Absent means every
    organization, which is right for the single-tenant installs that are the
    common case and wrong to assume on a shared one, so the docs tell
    multi-tenant operators to set it.
    """
    allowed = mcp_runtime.orgs_for(server)
    if not allowed:
        return True
    return bool(org_id) and str(org_id) in allowed


def _caller_org(user_id: Optional[str]):
    """(org_id, is_guest) for the user a tool call is being made for.

    org_id is None when there is no identifiable caller, which is a real and
    legitimate state rather than an error: the public bot and the /evaluate
    gateway have no user. That is kept DISTINCT from being a guest, because the
    two deserve different answers. A guest is refused outright; an
    unattributable call is refused only by a server that restricts itself to
    named organizations, since membership cannot be shown either way.
    """
    if not user_id:
        return None, False
    if is_guest(user_id):
        return None, True
    try:
        from ...persistence import database as db
        row = db.get_user_details(user_id) or {}
    except Exception as e:
        log.warning("could not resolve the caller for a tool call: %s", e)
        return None, False
    if is_guest(user_id, row.get("email") or ""):
        return None, True
    return row.get("org_id"), False


def member_oauth_servers(user_id, org_id, role):
    """The OAuth tool servers this member may see and connect, with the same
    two flags the delegated connectors carry:

      allowed  the server's own orgs restriction admits this member's org
      usable   at least one agent this member can reach is granted the
               server's tools (by connector key or by function name)

    Connecting is the means to an agent's end, so a member with no agent that
    could ever call the tools gets no invitation to grant a token nothing will
    read. Admins are the exception, handled by the CALLER, because someone has
    to make the first connection that discovers the catalog before any policy
    can list its tools.
    """
    from ..tool_connectors import expand_connectors

    servers = []
    try:
        from ...persistence import database as db
        from ...role_config import ROLE_CONFIG
        agents = db.list_agents(
            user_id, org_id, role or ROLE_CONFIG["default_role"],
            ROLE_CONFIG["visibility_roles"],
        ) or []
    except Exception as e:
        log.warning("member agent lookup failed, offering no oauth servers: %s", e)
        agents = []

    granted = set()
    for agent in agents:
        tools = agent.get("tools") or []
        names = [t for t in tools if isinstance(t, str)]
        granted.update(names)
        granted.update(expand_connectors(names))

    summary = mcp_runtime.summary()["servers"]
    for key, entry in summary.items():
        if entry.get("auth") != "oauth":
            continue
        allowed = server_allows_org(key, org_id)
        server_tools = set(entry.get("tools") or ()) | {key}
        servers.append({
            "key": key,
            "label": entry.get("label") or key,
            "allowed": allowed,
            "usable": bool(granted & server_tools),
            "login": f"/api/mcp/auth/{key}/login",
        })
    return servers


def member_can_connect(user_id, org_id, role, server_key) -> bool:
    """Whether this member may run the sign-in flow for this server.

    Host-configured authority roles always may: the first connection is what discovers the catalog, and
    without it no policy can enable a tool for anyone. Everyone else needs an
    agent that is actually granted the server, which is the same rule the
    delegated connectors enforce on their login routes.
    """
    from ...role_config import ROLE_CONFIG
    if role in ROLE_CONFIG["organization_admin_roles"]:
        return True
    for server in member_oauth_servers(user_id, org_id, role):
        if server["key"] == server_key:
            return server["allowed"] and server["usable"]
    return False


def builtin_tool_names() -> frozenset:
    """Every function name the built-in connectors own.

    This is the reserved set discovery refuses to let a third-party server
    claim. Derived from CONNECTOR_TOOLS rather than written out again, because
    a second hand-maintained copy of these names is exactly the drift that made
    tool_connectors.py necessary in the first place.
    """
    return frozenset(fn for fns in CONNECTOR_TOOLS.values() for fn in fns)


def start_servers(config: Any) -> Dict[str, Any]:
    """Connect the operator's MCP servers and register them as connectors.

    Called once per process from create_app(). Never raises: a deployment with a
    broken server file must still start, minus those tools.
    """
    servers = (getattr(config, "MCP_CONFIG", None) or {}).get("mcp_servers") or {}
    if not servers:
        return {"servers": {}, "tool_count": 0}
    enriched = {}
    for name, params in servers.items():
        if isinstance(params, dict) and (params.get("auth") or "").lower() == "oauth":
            params = dict(params)
            try:
                from ...persistence import mcp_store
                params["cached_tools"] = mcp_store.list_cached_tools(name)
            except Exception:
                params["cached_tools"] = []
        enriched[name] = params
    servers = enriched

    try:
        summary = mcp_runtime.start(servers, reserved_tool_names=builtin_tool_names())
    except Exception as e:
        log.error("MCP discovery failed, continuing without MCP tools: %s", e)
        return {"servers": {}, "tool_count": 0}

    clear_discovered_connectors()
    for server, functions in mcp_runtime.connectors().items():
        if not register_discovered_connector(server, functions):
            # The only way this fails is a server key that shadows a built-in
            # connector. Loud, because the operator's tools are silently absent
            # until they rename it, and the Will will block every call.
            log.error(
                "MCP server '%s' collides with a built-in connector name and was "
                "NOT registered. Rename the server key; its tools are unavailable.",
                server,
            )
    return summary


def refresh_discovered_connectors() -> None:
    """Re-register the connector table from whatever is currently connected.

    Built from the runtime rather than from the database so the table can never
    claim a connector whose session did not actually come up: an agent
    authorized for tools that do not exist would be blocked at the Will with a
    confusing reason, which is worse than the tool simply being absent.
    """
    clear_discovered_connectors()
    for server, functions in mcp_runtime.connectors().items():
        if not register_discovered_connector(server, functions):
            log.error(
                "MCP server '%s' collides with a built-in connector name and was "
                "NOT registered. Its tools are unavailable until it is renamed.",
                server,
            )


def file_servers() -> Dict[str, Any]:
    """Re-read the operator's server file from disk.

    Deliberately not `Config.MCP_CONFIG`, which was evaluated once at import.
    The CLI edits this file while the app is running, so the whole point of
    reading it here is to see what it says NOW.
    """
    from ...config import _load_mcp_servers

    servers = _load_mcp_servers() or {}
    out = {}
    for name, params in servers.items():
        if not isinstance(params, dict) or not params.get("enabled", True):
            continue
        if (params.get("auth") or "").lower() == "oauth":
            # The catalog of an OAuth server cannot be discovered anonymously,
            # so it is served from the cache captured at the last sign-in.
            params = dict(params)
            try:
                from ...persistence import mcp_store
                params["cached_tools"] = mcp_store.list_cached_tools(name)
            except Exception as e:
                log.warning("cached tools unavailable for %s: %s", name, e)
                params["cached_tools"] = []
        out[name] = params
    return out


async def discover_after_connect(server_key: str, token: str) -> list:
    """Capture an OAuth server's catalog with the token that just arrived.

    Runs once per sign-in, in the callback. The result is cached in the
    database and the generation counter is bumped, so every worker republishes
    the tools without anyone else having to authenticate first.
    """
    url = mcp_runtime.url_of(server_key) or (file_servers().get(server_key) or {}).get("url", "")
    if not url:
        return []
    tools = await mcp_runtime.list_tools_with_token(url, token)
    from ...persistence import mcp_store
    mcp_store.replace_cached_tools(server_key, tools)
    mcp_store.bump_generation()
    # This worker republishes now rather than on its next request.
    mcp_runtime.sync_origin(file_servers(), reserved_tool_names=builtin_tool_names(),
                            origin=mcp_runtime.origin_of(server_key) or "file")
    refresh_discovered_connectors()
    return [t["name"] for t in tools]


def resync_if_stale(generation_getter) -> bool:
    """Re-read the operator's file when the CLI says it changed.

    Four gunicorn workers each hold their own MCP sessions and each read the
    file once at boot, so a CLI edit on the host has to reach all of them. The
    CLI bumps one counter; each worker notices on its next request. Cheaper than
    any IPC we would have to build and then operate.

    Returns True when a resync happened. Never raises: a deployment whose
    generation check fails should keep serving with the tools it already has.
    """
    global _generation
    try:
        current = generation_getter()
        if not current or current == _generation:
            return False
        mcp_runtime.sync_origin(
            file_servers(), reserved_tool_names=builtin_tool_names(), origin="file"
        )
        refresh_discovered_connectors()
        _generation = current
        return True
    except Exception as e:
        log.warning("MCP resync skipped: %s", e)
        return False


_generation = 0


class MCPManager:
    """Per-orchestrator view over the tool catalogue.

    Holds no connections. The live MCP sessions belong to the process, not to
    this object: SAFi instances are cached per (agent, models, policy) and built
    lazily per request, so sessions owned here would mean one set of subprocesses
    per cached agent.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.log = logging.getLogger(self.__class__.__name__)

    async def get_tools_for_agent(self, agent_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        The tool schemas this agent may be offered.

        Two lists matter and they are not the same. `tools` is what the agent
        was configured with; `allowed_tools` is what Synderesis stamped after
        intersecting that with the policy's ceiling, and it is what the Will
        enforces. The schemas built below come from the first, and are then
        filtered by the second.

        That filter is the point. Without it a policy that narrows an agent's
        tools still ADVERTISED the wider set, so the model was offered a tool it
        could never call, proposed it, and collected a violation. Never showing
        the model a tool the Will would refuse costs nothing and removes a whole
        class of avoidable blocked turns.
        """
        allowed_tools = agent_profile.get("tools", [])
        if not allowed_tools:
            return []

        tools = []

        if "coding_harness" in allowed_tools:
            tools.append({
                "name": "read",
                "description": (
                    "Read a UTF-8 text file from the workspace. Line numbers are "
                    "1-indexed; offset and limit count lines, so a large file can "
                    "be read in slices."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path, absolute or relative to the workspace root."},
                        "offset": {"type": "integer", "description": "First line to read (1-indexed, default 1)."},
                        "limit": {"type": "integer", "description": "Maximum lines to return (default 2000)."},
                    },
                    "required": ["path"],
                },
            })

            tools.append({
                "name": "grep",
                "description": (
                    "Search file contents with a regular expression and return "
                    "the matching file, line number and text. Binary files and "
                    "build directories are skipped."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Python regular expression to search for."},
                        "path": {"type": "string", "description": "File or directory to search (default the workspace root)."},
                        "include": {"type": "string", "description": "Glob filter on filenames, e.g. '*.py'."},
                        "limit": {"type": "integer", "description": "Maximum matches to return (default 100)."},
                    },
                    "required": ["pattern"],
                },
            })

            tools.append({
                "name": "glob",
                "description": (
                    "Find files by glob pattern and return workspace-relative "
                    "paths, e.g. '**/*.py'. Dotfiles and dependency directories "
                    "are excluded."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'safi_app/**/*.py'."},
                        "path": {"type": "string", "description": "Directory to search under (default the workspace root)."},
                    },
                    "required": ["pattern"],
                },
            })

            tools.append({
                "name": "list",
                "description": (
                    "List the entries of one directory, with directories listed "
                    "before files. Not recursive; use glob to search a tree."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path (default the workspace root)."},
                    },
                },
            })

            # The rest of the harness vocabulary. These are DECLARED so the Will
            # can authorize them and the picker can offer them, because the gate
            # matches names exactly and an undeclared name is a guaranteed
            # refusal. SAFi does not execute them: the client runs them on the
            # host and reports results back as tool messages. Descriptions say
            # so plainly, so the model does not expect SAFi to have done it.
            declared_only = [
                ("bash", "Run a shell command. Executed by the coding-agent "
                         "client on the host, not by SAFi.",
                 {"command": {"type": "string", "description": "Command line to run."}}, ["command"]),
                ("write", "Create or overwrite a file. Executed by the "
                          "coding-agent client, not by SAFi.",
                 {"filePath": {"type": "string"}, "content": {"type": "string"}},
                 ["filePath", "content"]),
                ("edit", "Replace an exact string in a file. Executed by the "
                         "coding-agent client, not by SAFi.",
                 {"filePath": {"type": "string"}, "oldString": {"type": "string"},
                  "newString": {"type": "string"}},
                 ["filePath", "oldString", "newString"]),
                ("patch", "Apply a diff to a file. Executed by the "
                          "coding-agent client, not by SAFi.",
                 {"filePath": {"type": "string"}}, ["filePath"]),
                ("webfetch", "Fetch a URL. Executed by the coding-agent "
                             "client, not by SAFi.",
                 {"url": {"type": "string"}}, ["url"]),
                ("websearch", "Search the web. Executed by the coding-agent "
                              "client, not by SAFi.",
                 {"query": {"type": "string"}}, ["query"]),
                ("task", "Delegate a unit of work to a subagent. Executed by "
                         "the coding-agent client, not by SAFi.",
                 {"description": {"type": "string"}, "prompt": {"type": "string"},
                  "subagent_type": {"type": "string"}},
                 ["description", "prompt"]),
                ("todowrite", "Record a task list. Executed by the "
                              "coding-agent client, not by SAFi.",
                 {"todos": {"type": "array", "items": {"type": "object"}}}, ["todos"]),
                ("skill", "Invoke a named skill. Executed by the coding-agent "
                          "client, not by SAFi.",
                 {"name": {"type": "string"}}, ["name"]),
                ("lsp", "Query a language server. Executed by the coding-agent "
                        "client, not by SAFi.",
                 {"operation": {"type": "string"}}, ["operation"]),
                ("question", "Ask the user a question. Executed by the "
                             "coding-agent client, not by SAFi.",
                 {"question": {"type": "string"}}, ["question"]),
            ]
            for name, desc, props, required in declared_only:
                tools.append({
                    "name": name,
                    "description": desc,
                    "input_schema": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                })

        if "get_stock_price" in allowed_tools:
             tools.append({
                "name": "get_stock_price",
                "description": "Get the current stock price and basic info for a given ticker symbol.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "The stock ticker symbol (e.g. AAPL)"}
                    },
                    "required": ["ticker"]
                }
            })
        
        if "get_company_news" in allowed_tools:
             tools.append({
                "name": "get_company_news",
                "description": "Get the latest news headlines for a company.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "The stock ticker symbol (e.g. MSFT)"}
                    },
                    "required": ["ticker"]
                }
            })

        if "get_earnings_history" in allowed_tools:
             tools.append({
                "name": "get_earnings_history",
                "description": "Get recent earnings history and upcoming calendar dates.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "The stock ticker symbol (e.g. MSFT)"}
                    },
                    "required": ["ticker"]
                }
            })

        if "get_analyst_recommendations" in allowed_tools:
             tools.append({
                "name": "get_analyst_recommendations",
                "description": "Get the latest analyst buy/sell/hold recommendations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "The stock ticker symbol (e.g. MSFT)"}
                    },
                    "required": ["ticker"]
                }
            })

        if "find_places" in allowed_tools:
             tools.append({
                "name": "find_places",
                "description": "Find places (e.g. healthcare providers, hospitals) near a location.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query (e.g. 'Cardiologist in Seattle')."}
                    },
                    "required": ["query"]
                }
            })

        if "web_search" in allowed_tools:
            tools.append({
                "name": "web_search",
                "description": "Search the internet for general information and up-to-date facts.",
                "input_schema": {
                    "type": "object",
                     "properties": {
                        "query": {"type": "string", "description": "One search query (e.g. 'symptoms of flu')."},
                        "queries": {"type": "array", "items": {"type": "string"},
                                    "description": "Multiple search queries; results are merged and deduplicated."}
                     }
                 }
             })
            tools.append({
                "name": "web_news",
                "description": "Search the internet specifically for the latest news articles.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The news topic (e.g. 'latest FDA approvals')."}
                    },
                    "required": ["query"]
                }
            })

        # The sharepoint connector (7 tools) was retired 2026-08-15, absorbed
        # by the Graph gateway (scripts/graph_gateway.py), the last of the
        # three delegated built-ins to go. Its upload had no successor: the
        # gateways are read-only until tool calls can be held for human review.

        # --- DISCOVERED MCP SERVERS ---
        # Same rule as the built-ins above: advertise a tool if the agent was
        # granted its connector (the server key) or the function by name. The
        # second form is what lets a policy narrow within a server.
        for name, spec in mcp_runtime.tools().items():
            if name in allowed_tools or spec["server"] in allowed_tools:
                tools.append({
                    "name": name,
                    "description": spec["description"],
                    "input_schema": spec["input_schema"],
                })

        # The policy ceiling, applied once at the end so it covers built-in and
        # discovered tools identically. A profile with no `allowed_tools` key was
        # not built by the compiler (tests, direct construction), and is left
        # alone rather than silently emptied.
        authorized = agent_profile.get("allowed_tools")
        if isinstance(authorized, list):
            permitted = set(authorized)
            tools = [t for t in tools if t["name"] in permitted]

        return tools

    def list_all_tools(self, org_id: Optional[str] = None, guest: bool = False) -> List[Dict[str, Any]]:
        """
        The catalogue a tool picker renders, grouped by category.

        `org_id` scopes GUI-installed servers to the organization that installed
        them. Omit it only where there is no organization to scope to.
        """
        return [
            {
                "category": "Finance & Market Data",
                "tools": [
                    {
                        "name": "get_stock_price",
                        "label": "Stock Price",
                        "description": "Get current stock price and basic info.",
                        "icon": "chart-bar"
                    },
                    {
                        "name": "get_company_news",
                        "label": "Company News",
                        "description": "Latest news headlines for a company.",
                        "icon": "newspaper"
                    },
                    {
                        "name": "get_earnings_history",
                        "label": "Earnings History",
                        "description": "Recent earnings and calednar.",
                        "icon": "calendar"
                    },
                    {
                        "name": "get_analyst_recommendations",
                        "label": "Analyst Ratings",
                        "description": "Buy/Sell/Hold recommendations.",
                        "icon": "users"
                    }
                ]
            },
            {
                "category": "Location & Maps",
                "tools": [
                    {
                        "name": "find_places",
                        "label": "Find Places",
                        "description": "Find places near a location (Google Maps).",
                        "icon": "location-marker"
                    }
                ]
            },
            {
                "category": "Web Search",
                "tools": [
                    {
                        "name": "web_search",
                        "label": "Web & News Search",
                        "description": "Search the internet for up-to-date information and news.",
                        "icon": "globe"
                    }
                ]
            },
            {
                # Read-only repository inspection. The picker offers these as
                # individual functions rather than as one "coding_harness" card,
                # because the policy step decides tool by tool which of them an
                # agent may use — the same rule discovered MCP servers follow.
                # Saving stores the connector name, which expand_connectors
                # turns back into these four.
                "category": "Coding Harness",
                "tools": [
                    {
                        "name": "read",
                        "label": "Read File",
                        "description": "Read a text file from the workspace, by line offset.",
                        "icon": "file-text"
                    },
                    {
                        "name": "grep",
                        "label": "Search File Contents",
                        "description": "Regex-search file contents and return matching lines.",
                        "icon": "search"
                    },
                    {
                        "name": "glob",
                        "label": "Find Files",
                        "description": "Find files by glob pattern, e.g. **/*.py.",
                        "icon": "folder-search"
                    },
                    {
                        "name": "list",
                        "label": "List Directory",
                        "description": "List the entries of one directory.",
                        "icon": "folder"
                    },
                    {
                        "name": "bash",
                        "label": "Shell Command",
                        "description": "Run a shell command (executed by the agent client).",
                        "icon": "terminal"
                    },
                    {
                        "name": "write",
                        "label": "Write File",
                        "description": "Create or overwrite a file (executed by the agent client).",
                        "icon": "file-plus"
                    },
                    {
                        "name": "edit",
                        "label": "Edit File",
                        "description": "Replace an exact string in a file (executed by the agent client).",
                        "icon": "edit"
                    },
                    {
                        "name": "patch",
                        "label": "Apply Patch",
                        "description": "Apply a diff to a file (executed by the agent client).",
                        "icon": "git-pull-request"
                    },
                    {
                        "name": "webfetch",
                        "label": "Fetch URL",
                        "description": "Fetch a URL (executed by the agent client).",
                        "icon": "download"
                    },
                    {
                        "name": "websearch",
                        "label": "Web Search",
                        "description": "Search the web (executed by the agent client).",
                        "icon": "globe"
                    },
                    {
                        "name": "task",
                        "label": "Subagent Task",
                        "description": "Delegate work to a subagent (executed by the agent client).",
                        "icon": "users"
                    },
                    {
                        "name": "todowrite",
                        "label": "Task List",
                        "description": "Record a task list (executed by the agent client).",
                        "icon": "list-checks"
                    },
                    {
                        "name": "skill",
                        "label": "Skill",
                        "description": "Invoke a named skill (executed by the agent client).",
                        "icon": "sparkles"
                    },
                    {
                        "name": "lsp",
                        "label": "Language Server",
                        "description": "Query a language server (executed by the agent client).",
                        "icon": "code"
                    },
                    {
                        "name": "question",
                        "label": "Ask User",
                        "description": "Ask the user a question (executed by the agent client).",
                        "icon": "help-circle"
                    }
                ]
            }
        ] + self._discovered_categories(org_id, guest)

    @staticmethod
    def known_connectors(org_id: Optional[str] = None, guest: bool = False) -> set:
        """Every connector name this caller can be offered.

        Built-ins are deployment-wide. Installed MCP servers are NOT: a built-in
        that touches member data is gated by the org connector allow-list AND by
        that member's own OAuth, while an MCP server has neither and holds one
        shared credential. Treating them alike let any organization — and a
        guest, who admins a sandbox org — reach any installed server.

        Pass org_id=None only where there is no caller to scope to (background
        jobs, tests); it returns the deployment-wide view.
        """
        connectors = set(CONNECTOR_TOOLS)
        if guest:
            return connectors
        for server in mcp_runtime.connectors():
            if org_id is None or server_allows_org(server, org_id):
                connectors.add(server)
        return connectors

    @staticmethod
    def _discovered_categories(org_id: Optional[str] = None, guest: bool = False) -> List[Dict[str, Any]]:
        """One category per connected server, one card per TOOL.

        Built-in connectors are offered as a bundle because their contents were
        reviewed when they shipped. A server the operator installed is different:
        its tools arrive from a third party at runtime, and the point of the
        policy step is that an editor decides tool by tool which of them an agent
        may use. Offering the server as a single checkbox would make that
        decision unavailable.

        Individual tool names need nothing special downstream: expand_connectors
        passes an unknown name through unchanged and the Will matches exactly,
        so a policy listing three of a server's nine tools authorizes three.
        """
        if guest:
            return []
        categories: List[Dict[str, Any]] = []
        discovered = mcp_runtime.tools()
        for server, entry in mcp_runtime.summary()["servers"].items():
            names = entry.get("tools") or []
            if not names or (org_id is not None and not server_allows_org(server, org_id)):
                continue
            categories.append({
                "category": entry.get("label") or server,
                "tools": [
                    {
                        "name": name,
                        "label": name,
                        "description": (discovered.get(name) or {}).get("description", ""),
                        "icon": "puzzle",
                    }
                    for name in names
                ],
            })
        return categories

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], user_id: Optional[str] = None) -> str:
        """
        Run one approved tool call.

        Built-in connectors dispatch to the in-process implementations in
        core/mcp_servers/ below; anything discovered from an operator-installed
        MCP server goes over the real protocol at the end (core/mcp_runtime.py).

        Reached only after WillGate.evaluate_tool_intent approved this exact
        name, so nothing here re-checks agent-level authorization.
        """
        self.log.info(f"Executing tool '{tool_name}' with args {arguments}")
        
        if tool_name == "read":
            from ..mcp_servers.coding_harness import read_file
            return await read_file(
                arguments.get("path", ""),
                arguments.get("offset", 1),
                arguments.get("limit", 2000),
            )

        if tool_name == "grep":
            from ..mcp_servers.coding_harness import grep
            return await grep(
                arguments.get("pattern", ""),
                arguments.get("path", "."),
                arguments.get("include"),
                arguments.get("limit", 100),
            )

        if tool_name == "glob":
            from ..mcp_servers.coding_harness import glob_files
            return await glob_files(
                arguments.get("pattern", ""), arguments.get("path", "."))

        if tool_name == "list":
            from ..mcp_servers.coding_harness import list_directory
            return await list_directory(arguments.get("path", "."))

        # The remainder of the coding harness vocabulary is DECLARED by the
        # coding_harness connector but executed by the coding-agent client, not by
        # SAFi. Say so explicitly: a bare "not found" reads as a bug, and worse
        # would leave the caller believing the command had been refused for a
        # governance reason when it simply has no local executor.
        if tool_name in coding_harness_declaration_only():
            return json.dumps({
                "error": (
                    f"Tool '{tool_name}' is provided by the coding-agent client, "
                    "which executes it and returns the result. SAFi governs and "
                    "records the call but does not run it."
                ),
                "executed_by": "client",
            })

        if tool_name == "get_stock_price":
            from ..mcp_servers.fiduciary import get_stock_price
            return await get_stock_price(arguments["ticker"])
            
        if tool_name == "get_company_news":
            from ..mcp_servers.fiduciary import get_company_news
            return await get_company_news(arguments["ticker"])

        if tool_name == "get_earnings_history":
            from ..mcp_servers.fiduciary import get_earnings_history
            return await get_earnings_history(arguments["ticker"])

        if tool_name == "get_analyst_recommendations":
            from ..mcp_servers.fiduciary import get_analyst_recommendations
            return await get_analyst_recommendations(arguments["ticker"])

        if tool_name == "find_places":
            from ..mcp_servers.google_maps import find_places
            return await find_places(arguments["query"])

        if tool_name in ["web_search", "web_news"]:
            from ..mcp_servers.web_search import search_web, get_news
            if tool_name == "web_search":
                return await search_web(arguments.get("queries", arguments.get("query", "")))
            if tool_name == "web_news":
                return await get_news(arguments["query"])

        # -- DISCOVERED MCP SERVERS --
        # Dispatch-time authorization, and not a duplicate of the Will's. The Will
        # asks whether THIS AGENT may call this tool; this asks whether the
        # caller's ORGANIZATION may reach this server at all. The catalogue and
        # the save guard apply the same rule, but a filter on a picker is not a
        # check, and an agent created before a restriction was added would
        # otherwise keep working.
        if mcp_runtime.owns(tool_name):
            server = mcp_runtime.server_of(tool_name)
            org_id, guest = _caller_org(user_id)
            if guest:
                return json.dumps({
                    "error": f"Tool '{tool_name}' is not available to demo accounts."
                })
            if mcp_runtime.orgs_for(server) and not server_allows_org(server, org_id):
                return json.dumps({
                    "error": (
                        f"Tool '{tool_name}' is restricted to specific organizations"
                        + (" and this turn has no organization." if org_id is None
                           else " and this one is not among them.")
                    )
                })
        # Last, so a built-in always wins a name contest. Two credential models
        # live behind this branch and they are opposites: a static server runs
        # with the deployment's own credential (a service principal, so no
        # member identity is passed), while an OAuth server (MCP authorization
        # spec) runs every call as the requesting user with an audience-bound
        # token, which is what restores per-person attribution.
        if mcp_runtime.owns(tool_name):
            server = mcp_runtime.server_of(tool_name)
            if mcp_runtime.auth_mode_of(server) == "oauth":
                # No user means no identity to run as: the public bot and
                # /evaluate have no way to hold a token.
                if not user_id:
                    return json.dumps({"error": (
                        f"Tool '{tool_name}' requires a signed-in user's "
                        "authorization and this turn has none."
                    )})
                from . import mcp_oauth
                definition = file_servers().get(server) or {}
                token = mcp_oauth.access_token_for(user_id, server, definition)
                if not token:
                    # The link, not directions: the old text pointed members at
                    # a tab only admins can see. The agent relays this message, so
                    # it carries the absolute sign-in URL, which the chat renders
                    # as a link the member can actually click.
                    from ...config import Config
                    login_url = (f"{Config.WEB_BASE_URL.rstrip('/')}"
                                 f"/api/mcp/auth/{server}/login")
                    return json.dumps({"error": (
                        f"Tool '{tool_name}' needs the user's authorization. "
                        f"Tell the user to connect their account by opening this "
                        f"link, then asking again: {login_url}"
                    )})
                return await mcp_runtime.call_with_token(
                    mcp_runtime.url_of(server), tool_name, arguments, token
                )
            return await mcp_runtime.call(tool_name, arguments)

        return json.dumps({"error": f"Tool '{tool_name}' not found."})
