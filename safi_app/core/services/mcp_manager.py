"""
MCP Manager Service
Handles connections to local and remote MCP servers.
"""
import asyncio
import logging
import json
import os
from typing import List, Dict, Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.active_sessions: Dict[str, ClientSession] = {}
        self.available_tools: List[Dict[str, Any]] = []

    async def initialize(self):
        """Starts connections to all configured MCP servers."""
        server_configs = self.config.get("mcp_servers", {})
        
        for name, params in server_configs.items():
            if params.get("enabled", True):
                try:
                    await self._connect_to_server(name, params)
                except Exception as e:
                    self.log.error(f"Failed to connect to MCP server '{name}': {e}")

    async def _connect_to_server(self, name: str, params: Dict[str, Any]):
        """Connects to a single MCP server via Stdio."""
        command = params.get("command")
        args = params.get("args", [])
        env = params.get("env", None)

        if not command:
            self.log.error(f"MCP Server '{name}' missing 'command'.")
            return

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env
        )

        # We verify construction but don't hold the context manager here in this simple snippet.
        # In a real app, we need to manage the lifecycle carefully.
        # For this PoC, we will create a tailored client wrapper for each request 
        # OR keep a persistent connection. 
        
        # MCP python SDK is context-manager heavy. 
        # We might need a structural change to hold connections open.
        # For now, let's assume we reconnect or hold a long-running task.
        pass

    async def get_tools_for_agent(self, agent_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Returns a list of tool schemas allowed for this agent.
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

        return tools

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """
        Returns a list of all available tools for selection in the UI.
        Categorized by domain.
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
            }
        ]

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Executes a named tool. 
        For the PoC, we will route directly to the local python implementation 
        instead of full stdio IPC to save complexity in the first pass, 
        UNLESS the plan strictly requires stdio. 
        
        The plan said "standalone MCP server", so let's try to shell out to it 
        or import it as a library if possible.
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

        return json.dumps({"error": f"Tool '{tool_name}' not found."})
