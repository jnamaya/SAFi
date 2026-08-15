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
pricing service) is right for an MCP server; a member's own mailbox or drive
belongs on a delegated-OAuth connector, or every read in the source system's
audit log is attributed to SAFi rather than to a person, and offboarding stops
cutting access.

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
        agents = db.list_agents(user_id, org_id, role or "member") or []
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

    Admins always may: the first connection is what discovers the catalog, and
    without it no policy can enable a tool for anyone. Everyone else needs an
    agent that is actually granted the server, which is the same rule the
    delegated connectors enforce on their login routes.
    """
    if (role or "").lower() == "admin":
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
    broken server file must still start, minus those tools. Returns the
    discovery summary for the boot log.
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

    Called after the operator's file changes the live set. Built
    from the runtime rather than from the database so the table can never claim
    a connector whose session did not actually come up: an agent authorized for
    tools that do not exist would be blocked at the Will with a confusing
    reason, which is worse than the tool simply being absent.
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
    # This worker republishes immediately rather than on its next request.
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
        Returns a list of tool schemas allowed for this agent.

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
        # 1. Check what Tools this agent is allowed to use (from profile)
        allowed_tools = agent_profile.get("tools", [])
        if not allowed_tools:
            return []

        # 2. In a real impl, we would fetch tools from connected sessions.
        # For this PoC, we will manually define the Fiduciary tools if the agent has them.
        tools = []
        
        # Fallback/Hardcoded for PoC until full dynamic discovery is built
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

        # --- WEB SEARCH ---
        if "web_search" in allowed_tools:
            tools.append({
                "name": "web_search",
                "description": "Search the internet for general information and up-to-date facts.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query (e.g. 'symptoms of flu')."}
                    },
                    "required": ["query"]
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

        # --- GOOGLE DRIVE ---
        if "google_drive" in allowed_tools:
            tools.append({
                "name": "google_list_files",
                "description": "List files in user's Google Drive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Optional search term to filter by name."}
                    }
                }
            })
            tools.append({
                "name": "google_read_file",
                "description": "Read content of a Google Drive file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "The ID of the file to read."}
                    },
                    "required": ["file_id"]
                }
            })
            tools.append({
                "name": "google_upload_file",
                "description": "Create/Upload a file to Google Drive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Filename."},
                        "content": {"type": "string", "description": "Text content of the file."}
                    },
                    "required": ["name", "content"]
                }
            })

        # --- MICROSOFT SHAREPOINT ---
        if "sharepoint" in allowed_tools:
            tools.append({
                "name": "sharepoint_search",
                "description": "Search files in SharePoint/OneDrive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."}
                    },
                    "required": ["query"]
                }
            })
            tools.append({
                "name": "sharepoint_read",
                "description": "Read content of a SharePoint file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string", "description": "The ID of the item."}
                    },
                    "required": ["item_id"]
                }
            })
            tools.append({
                "name": "sharepoint_upload",
                "description": "Upload a file to SharePoint root.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Filename."},
                        "content": {"type": "string", "description": "Text content."}
                    },
                    "required": ["name", "content"]
                }
            })
            tools.append({
                "name": "sharepoint_search_sites",
                "description": "Find SharePoint Sites (e.g. Teams, Projects) by name.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for site name/title."}
                    },
                    "required": ["query"]
                }
            })
            tools.append({
                "name": "sharepoint_search_site_files",
                "description": "Search for files within a specific SharePoint Site.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string", "description": "The ID of the SharePoint Site."},
                        "query": {"type": "string", "description": "Search query for file name/content."}
                    },
                    "required": ["site_id", "query"]
                }
            })
            tools.append({
                "name": "sharepoint_list_folders",
                "description": "List contents of a SharePoint folder (defaults to root).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "folder_path": {"type": "string", "description": "OPTIONAL: Path to folder (e.g. 'Documents/MyProject'). Defaults to root."}
                    }
                }
            })
            tools.append({
                "name": "sharepoint_get_tree",
                "description": "Get a simplified folder tree structure of the drive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_depth": {"type": "integer", "description": "Depth of recursion (defualt 2)."}
                    }
                }
            })

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
        # discovered tools identically. A profile with no `allowed_tools` key
        # was not built by the compiler (tests, direct construction), and is
        # left alone rather than silently emptied.
        authorized = agent_profile.get("allowed_tools")
        if isinstance(authorized, list):
            permitted = set(authorized)
            tools = [t for t in tools if t["name"] in permitted]

        return tools

    def list_all_tools(self, org_id: Optional[str] = None, guest: bool = False) -> List[Dict[str, Any]]:
        """
        Returns a list of all available tools for selection in the UI.
        Categorized by domain.

        `org_id` scopes GUI-installed servers to the organization that installed
        them. Omit it only where there is no organization to scope to.
        """
        return [
            # --- FINANCE (Fiduciary) ---
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
            # --- GEO (Google Maps) ---
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
             # --- OFFICE & PRODUCTIVITY ---
            {
                "category": "Office & Productivity",
                "tools": [
                    {
                        "name": "google_drive",
                        "label": "Google Drive",
                        "description": "Read/Write Access to Google Drive",
                        "icon": "cloud"
                    },
                    {
                        "name": "sharepoint",
                        "label": "OneDrive / SharePoint",
                        "description": "Read/Write Access to OneDrive & SharePoint",
                        "icon": "office-building"
                    }
                ]
            },
            # --- WEB SEARCH ---
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
            }
        ] + self._discovered_categories(org_id, guest)

    @staticmethod
    def known_connectors(org_id: Optional[str] = None, guest: bool = False) -> set:
        """Every connector name this caller can be offered.

        Built-ins are deployment-wide. Installed MCP servers are NOT, and the
        reasoning that briefly made them so was wrong: a built-in that touches
        member data is gated by the org connector allow-list AND by that
        member's own OAuth, while an MCP server has neither and holds one shared
        credential. On a multi-tenant deployment that meant any organization
        could reach any installed server, and a guest is an admin of a sandbox
        organization, so a guest could too.

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
        passes an unknown name through unchanged, and the Will matches exactly,
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
        Executes a named tool.

        Built-in connectors dispatch to the in-process implementations in
        core/mcp_servers/ below; anything discovered from an operator-installed
        MCP server goes over the real protocol at the end (core/mcp_runtime.py).

        Reached only after WillGate.evaluate_tool_intent approved this exact
        name, so nothing here re-checks authorization.
        """
        self.log.info(f"Executing tool '{tool_name}' with args {arguments}")
        
        # -- FIDUCIARY DIRECT IMPLEMENTATION (PoC bridge) --
        if tool_name == "get_stock_price":
            # We can import the new server code dynamically
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

        # -- GOOGLE MAPS IMPLEMENTATION --
        if tool_name == "find_places":
            from ..mcp_servers.google_maps import find_places
            return await find_places(arguments["query"])

        # -- WEB SEARCH IMPLEMENTATION --
        if tool_name in ["web_search", "web_news"]:
            from ..mcp_servers.web_search import search_web, get_news
            if tool_name == "web_search":
                return await search_web(arguments["query"])
            if tool_name == "web_news":
                return await get_news(arguments["query"])

        # -- GOOGLE DRIVE --
        if tool_name.startswith("google_"):
            from ..mcp_servers import google_drive
            if tool_name == "google_list_files":
                return await google_drive.list_files(arguments.get("query"))
            if tool_name == "google_read_file":
                return await google_drive.read_file(arguments["file_id"])
            if tool_name == "google_upload_file":
                 return await google_drive.upload_file(arguments["name"], arguments["content"])

        # -- SHAREPOINT --
        if tool_name.startswith("sharepoint_"):
            from ..mcp_servers import sharepoint
            if tool_name == "sharepoint_search":
                return await sharepoint.search_drive(arguments["query"])
            if tool_name == "sharepoint_read":
                return await sharepoint.read_item(arguments["item_id"])
            if tool_name == "sharepoint_upload":
                return await sharepoint.upload_item(arguments["name"], arguments["content"])
            if tool_name == "sharepoint_search_sites":
                return await sharepoint.search_sites(arguments["query"])
            if tool_name == "sharepoint_search_site_files":
                return await sharepoint.search_site_drive(arguments["site_id"], arguments["query"])
            if tool_name == "sharepoint_list_folders":
                return await sharepoint.list_folders(arguments.get("folder_path", "root"))
            if tool_name == "sharepoint_get_tree":
                return await sharepoint.get_tree(arguments.get("max_depth", 2))

        # -- DISCOVERED MCP SERVERS --
        #
        # Dispatch-time authorization, and not a duplicate of the Will's. The
        # Will asks whether THIS AGENT may call this tool; this asks whether the
        # caller's ORGANIZATION may reach this server at all. The catalogue and
        # the save guard both apply the same rule, but a filter on a picker is
        # not a check, and an agent created before a restriction was added would
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
                # Per-user authorization: the call runs as the person who asked.
                # No user means no identity to run as — the public bot and
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
                    # The link, not directions: the old text sent members to a
                    # tab only admins can see. The agent relays this message, so
                    # it carries the absolute sign-in URL, which the chat
                    # renders as a link the member can actually click.
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
