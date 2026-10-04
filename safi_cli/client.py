"""HTTP Client communicating directly with SAFi's governed harness endpoint."""

import json
from typing import Any, Dict, List, Optional
import requests

from .tools import TOOL_SCHEMAS


class SafiClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class SafiClient:
    def __init__(self, api_url: str, api_key: str = ""):
        self.api_url = api_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.endpoint = f"{self.api_url}/api/agentic/process_prompt"

    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Fetch available agents from the connected SAFi backend URL."""
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        for path in ("/api/agents/all", "/api/agentic/agents"):
            try:
                resp = requests.get(
                    f"{self.api_url}{path}",
                    headers=headers,
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("ok") and isinstance(data.get("available"), list):
                        return data["available"]
            except Exception:
                continue
        return []

    def send_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        workspace_root: str,
        agent: str = "software_engineer",

        tool_results: Optional[List[Dict[str, Any]]] = None,
        recent_turns: str = "",
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch a single turn to SAFi's governed pipeline."""
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        # Client-owned repository tools are only used for software engineering tasks.
        # Informational and advisory personas (e.g. fiduciary, health_navigator)
        # use governed server-side MCP tools (stock market data, web search, etc.).
        is_coding_agent = (agent == "software_engineer")
        tools_payload = TOOL_SCHEMAS if is_coding_agent else []

        payload: Dict[str, Any] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message": message,
            "agent": agent,
            "workspace_context": {
                "working_directory": workspace_root,
                "workspace_root": workspace_root,
            },
            "tools": tools_payload,
            "tool_results": tool_results or [],
            "recent_turns": recent_turns,
        }
        if message_id:
            payload["message_id"] = message_id

        try:
            resp = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=300,
            )
        except requests.exceptions.RequestException as exc:
            raise SafiClientError(
                f"Failed to connect to SAFi backend at {self.endpoint}: {exc}",
                details=str(exc),
            )

        if resp.status_code == 401:
            raise SafiClientError(
                "Unauthorized: Invalid SAFi Policy API Key. Check your key in the SAFi Governance UI.",
                status_code=401,
            )
        elif resp.status_code != 200:
            err_msg = resp.text[:500]
            try:
                err_data = resp.json()
                if "error" in err_data:
                    err_msg = err_data["error"]
            except Exception:
                pass
            raise SafiClientError(
                f"Backend rejected turn (HTTP {resp.status_code}): {err_msg}",
                status_code=resp.status_code,
                details=resp.text,
            )

        try:
            return resp.json()
        except ValueError:
            raise SafiClientError("Backend returned invalid non-JSON response.", details=resp.text)
