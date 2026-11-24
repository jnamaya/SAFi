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


def agentic_declaration_only() -> frozenset:
    from ..mcp_servers.coding_tools import (
        CODING_HARNESS_TOOL_NAMES, SAFI_EXECUTED_TOOLS,
    )
    return frozenset(CODING_HARNESS_TOOL_NAMES) - SAFI_EXECUTED_TOOLS


coding_harness_declaration_only = agentic_declaration_only


def is_guest(user_id: str = "", email: str = "") -> bool:
    uid = (user_id or "").lower()
    mail = (email or "").lower()
    return uid.startswith("demo_") or mail.endswith("@demo.local")


def server_allows_org(server: str, org_id: Optional[str]) -> bool:
    allowed = mcp_runtime.orgs_for(server)
    if not allowed:
        return True
    return bool(org_id) and str(org_id) in allowed


def _caller_org(user_id: Optional[str]):
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
    from ...role_config import ROLE_CONFIG
    if role in ROLE_CONFIG["organization_admin_roles"]:
        return True
    for server in member_oauth_servers(user_id, org_id, role):
        if server["key"] == server_key:
            return server["allowed"] and server["usable"]
    return False


def builtin_tool_names() -> frozenset:
    return frozenset(fn for fns in CONNECTOR_TOOLS.values() for fn in fns)


def start_servers(config: Any) -> Dict[str, Any]:
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
            log.error(
                "MCP server '%s' collides with a built-in connector name and was "
                "NOT registered. Rename the server key; its tools are unavailable.",
                server,
            )
    return summary


def refresh_discovered_connectors() -> None:
    clear_discovered_connectors()
    for server, functions in mcp_runtime.connectors().items():
        if not register_discovered_connector(server, functions):
            log.error(
                "MCP server '%s' collides with a built-in connector name and was "
                "NOT registered. Its tools are unavailable until it is renamed.",
                server,
            )


def file_servers() -> Dict[str, Any]:
    from ...config import _load_mcp_servers

    servers = _load_mcp_servers() or {}
    out = {}
    for name, params in servers.items():
        if not isinstance(params, dict) or not params.get("enabled", True):
            continue
        if (params.get("auth") or "").lower() == "oauth":
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
    url = mcp_runtime.url_of(server_key) or (file_servers().get(server_key) or {}).get("url", "")
    if not url:
        return []
    tools = await mcp_runtime.list_tools_with_token(url, token)
    from ...persistence import mcp_store
    mcp_store.replace_cached_tools(server_key, tools)
    mcp_store.bump_generation()
    mcp_runtime.sync_origin(file_servers(), reserved_tool_names=builtin_tool_names(),
                            origin=mcp_runtime.origin_of(server_key) or "file")
    refresh_discovered_connectors()
    return [t["name"] for t in tools]


def resync_if_stale(generation_getter) -> bool:
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

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.log = logging.getLogger(self.__class__.__name__)

    async def get_tools_for_agent(self, agent_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        allowed_tools = agent_profile.get("tools", [])
        if not allowed_tools:
            return []

        tools = []

        _CODING_CONNECTORS = (
            "agentic_coding", "coding_harness",
            "software_engineer_tools", "sysadmin_tools", "security_engineer_tools",
        )
        _coding_declared = [c for c in _CODING_CONNECTORS if c in allowed_tools]
        _emit_coding = bool(_coding_declared)
        _coding_names = None
        if _emit_coding:
            active_funcs = set()
            for c in _coding_declared:
                if c in CONNECTOR_TOOLS:
                    active_funcs.update(CONNECTOR_TOOLS[c])
            _coding_names = frozenset(active_funcs) if active_funcs else None
        def _want(name: str) -> bool:
            return _coding_names is None or name in _coding_names

        if _emit_coding and _want("read"):
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

            if _want("grep"):
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

            if _want("glob"):
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

            if _want("list"):
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
                ("delete", "Delete a file or directory. Executed by the "
                           "coding-agent client, not by SAFi.",
                 {"path": {"type": "string"}, "filePath": {"type": "string"}},
                 []),
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
                ("m365_admin", "Govern and manage Microsoft 365 and Entra ID (Azure AD). Executed by the client.",
                 {"action": {"type": "string"}, "params": {"type": "object"}, "tenant": {"type": "string"}}, ["action"]),
                ("azure_admin", "Govern and operate Azure cloud resources. Executed by the client.",
                 {"action": {"type": "string"}, "params": {"type": "object"}, "subscription": {"type": "string"}}, ["action"]),
                ("cloud_status", "Inspect configured cloud environments for M365 and Azure. Executed by the client.",
                 {}, []),
            ]
            for name, desc, props, required in declared_only:
                if not _want(name):
                    continue
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


        for name, spec in mcp_runtime.tools().items():
            if name in allowed_tools or spec["server"] in allowed_tools:
                tools.append({
                    "name": name,
                    "description": spec["description"],
                    "input_schema": spec["input_schema"],
                })

        authorized = agent_profile.get("allowed_tools")
        if isinstance(authorized, list):
            permitted = set(authorized)
            tools = [t for t in tools if t["name"] in permitted]

        return tools

    def list_all_tools(
        self,
        org_id: Optional[str] = None,
        guest: bool = False,
        policy_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        pid_lower = str(policy_id or "").lower()
        if "sysadmin" in pid_lower or "systems_admin" in pid_lower:
            harness_category = "Sysadmin Tools"
        elif "security_engineer" in pid_lower:
            harness_category = "Security Engineering Tools"
        else:
            harness_category = "Agentic Tools"

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
                "category": harness_category,
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
                        "name": "delete",
                        "label": "Delete File",
                        "description": "Delete a file or directory (executed by the agent client).",
                        "icon": "trash"
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
                    },
                    {
                        "name": "m365_admin",
                        "label": "Microsoft 365 & Entra ID Admin",
                        "description": "Govern and manage Microsoft 365 users, licenses, and sign-in logs.",
                        "icon": "cloud"
                    },
                    {
                        "name": "azure_admin",
                        "label": "Azure Cloud Admin",
                        "description": "Govern and operate Azure resource groups, VMs, and cloud inventory.",
                        "icon": "server"
                    },
                    {
                        "name": "cloud_status",
                        "label": "Cloud Tenancy Status",
                        "description": "Inspect configured Microsoft 365 and Azure cloud connectivity.",
                        "icon": "activity"
                    }
                ]
            }
        ] + self._discovered_categories(org_id, guest)

    @staticmethod
    def known_connectors(org_id: Optional[str] = None, guest: bool = False) -> set:
        connectors = set(CONNECTOR_TOOLS)
        if guest:
            return connectors
        for server in mcp_runtime.connectors():
            if org_id is None or server_allows_org(server, org_id):
                connectors.add(server)
        return connectors

    @staticmethod
    def _discovered_categories(org_id: Optional[str] = None, guest: bool = False) -> List[Dict[str, Any]]:
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
        self.log.info(f"Executing tool '{tool_name}' with args {arguments}")
        
        if tool_name == "read":
            from ..mcp_servers.coding_tools import read_file
            return await read_file(
                arguments.get("path", ""),
                arguments.get("offset", 1),
                arguments.get("limit", 2000),
            )

        if tool_name == "grep":
            from ..mcp_servers.coding_tools import grep
            return await grep(
                arguments.get("pattern", ""),
                arguments.get("path", "."),
                arguments.get("include"),
                arguments.get("limit", 100),
            )

        if tool_name == "glob":
            from ..mcp_servers.coding_tools import glob_files
            return await glob_files(
                arguments.get("pattern", ""), arguments.get("path", "."))

        if tool_name == "list":
            from ..mcp_servers.coding_tools import list_directory
            return await list_directory(arguments.get("path", "."))

        if tool_name in agentic_declaration_only():
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
        if mcp_runtime.owns(tool_name):
            server = mcp_runtime.server_of(tool_name)
            if mcp_runtime.auth_mode_of(server) == "oauth":
                if not user_id:
                    return json.dumps({"error": (
                        f"Tool '{tool_name}' requires a signed-in user's "
                        "authorization and this turn has none."
                    )})
                from . import mcp_oauth
                definition = file_servers().get(server) or {}
                token = mcp_oauth.access_token_for(user_id, server, definition)
                if not token:
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
