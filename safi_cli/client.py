"""HTTP Client communicating directly with SAFi's governed agentic endpoint."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from .tools import TOOL_SCHEMAS


class SafiClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class SafiClient:
    def __init__(self, api_url: str, api_key: str = "", verify_ssl: Optional[bool | str] = None):
        self.api_url = api_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.endpoint = f"{self.api_url}/api/agentic/process_prompt"

        self.session = requests.Session()
        # Resolve SSL verification (appliance CA cert if saved, or explicit parameter, or env)
        self.default_ca = Path.home() / ".config" / "safi" / "appliance.crt"
        if verify_ssl is not None:
            self.session.verify = verify_ssl
        else:
            ca_env = os.environ.get("SAFI_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
            if ca_env:
                self.session.verify = ca_env
            else:
                self._ensure_appliance_cert()

    def _fetch_peer_cert(self) -> Optional[str]:
        if not self.api_url.startswith("https://"):
            return None
        try:
            import socket
            import ssl
            from urllib.parse import urlparse
            parsed = urlparse(self.api_url)
            host = parsed.hostname
            port = parsed.port or 443
            if not host:
                return None
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=4) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    der = ssock.getpeercert(True)
                    if der:
                        return ssl.DER_cert_to_PEM_cert(der)
        except Exception:
            pass
        return None

    def _ensure_appliance_cert(self, force_refresh: bool = False) -> None:
        if not self.api_url.startswith("https://"):
            return
        if not force_refresh and self.default_ca.exists():
            self.session.verify = str(self.default_ca)
            return

        pem = self._fetch_peer_cert()
        if pem:
            try:
                self.default_ca.parent.mkdir(parents=True, exist_ok=True)
                self.default_ca.write_text(pem, encoding="ascii")
                self.session.verify = str(self.default_ca)
            except Exception:
                pass


    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Fetch available agents from the connected SAFi backend URL."""
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        for path in ("/api/agents/all", "/api/agentic/agents"):
            try:
                resp = self.session.get(
                    f"{self.api_url}{path}",
                    headers=headers,
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("ok") and isinstance(data.get("available"), list):
                        return data["available"]
            except requests.exceptions.SSLError:
                self._ensure_appliance_cert(force_refresh=True)
                try:
                    resp = self.session.get(
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
            except Exception:
                continue
        return []

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Fetch available models for the Intellect faculty from the connected SAFi backend."""
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        for path in ("/api/agentic/models", "/api/models"):
            try:
                resp = self.session.get(
                    f"{self.api_url}{path}",
                    headers=headers,
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("ok") and isinstance(data.get("models"), list):
                        return data["models"]
            except requests.exceptions.SSLError:
                self._ensure_appliance_cert(force_refresh=True)
                try:
                    resp = self.session.get(
                        f"{self.api_url}{path}",
                        headers=headers,
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and data.get("ok") and isinstance(data.get("models"), list):
                            return data["models"]
                except Exception:
                    continue
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
        user_name: Optional[str] = None,
        model: Optional[str] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        recent_turns: str = "",
        message_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Dispatch a single turn to SAFi's governed pipeline."""
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        # Client-owned repository tools are only used for software engineering tasks.
        # Informational and advisory personas (e.g. fiduciary, health_navigator)
        # use governed server-side MCP tools (stock market data, web search, etc.).
        if tools is not None:
            tools_payload = tools
        else:
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
        if model:
            payload["intellect_model"] = model
            payload["model"] = model
        if user_name:
            payload["user_name"] = user_name
        if message_id:
            payload["message_id"] = message_id

        try:
            resp = self.session.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=600,
            )
        except requests.exceptions.SSLError as exc:
            # If the appliance was reinstalled and generated a fresh certificate,
            # refresh ~/.config/safi/appliance.crt and retry once automatically.
            self._ensure_appliance_cert(force_refresh=True)
            try:
                resp = self.session.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=600,
                )
            except requests.exceptions.RequestException as retry_exc:
                raise SafiClientError(
                    f"Failed to connect to SAFi backend at {self.endpoint}: {retry_exc}",
                    details=str(retry_exc),
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

    def get_turn_progress(self, message_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch real-time reasoning progress for an in-flight message."""
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        params = {}
        if user_id:
            params["user_id"] = user_id
        try:
            resp = self.session.get(
                f"{self.api_url}/api/agentic/progress/{message_id}",
                headers=headers,
                params=params,
                timeout=2.0,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            return None
        return None

    def compress_conversation(
        self,
        conversation_id: str,
        user_id: str,
        agent: str = "software_engineer",
        model: Optional[str] = None,
        action: str = "compress",
    ) -> Dict[str, Any]:
        """Compress or manage the conversation's memory summary."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        payload = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "agent": agent,
            "action": action,
        }
        if model:
            payload["model"] = model
        try:
            resp = self.session.post(
                f"{self.api_url}/api/agentic/compress",
                headers=headers,
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json()
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            return {
                "ok": False,
                "error": err_data.get("error", f"Server returned HTTP {resp.status_code}"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
