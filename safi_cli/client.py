"""HTTP Client communicating directly with SAFi's governed agentic endpoint."""

import logging
import os
import socket
import ssl
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .context import truncate_tool_results
from .schema import SchemaError, normalize_turn_response
from .tools import TOOL_SCHEMAS, get_tools_for_agent

logger = logging.getLogger("safi.client")


def _json_or_none(resp: "requests.Response"):
    """Parse a response body as JSON, returning None on failure."""
    try:
        return resp.json()
    except ValueError as exc:
        logger.debug("Non-JSON response from %s %s: %s", resp.request.method, resp.url, exc)
        return None


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
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

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
        except Exception as exc:
            logger.debug("Could not fetch peer cert from %s: %s", self.api_url, exc)
        return None

    def _allow_cert_refresh(self) -> bool:
        """Only allow overwriting an existing pinned appliance cert if explicitly opted in."""
        val = os.environ.get("SAFI_TRUST_ON_REINSTALL", "")
        return val.strip().lower() in ("1", "true", "yes", "on")

    def _ensure_appliance_cert(self, force_refresh: bool = False) -> None:
        if not self.api_url.startswith("https://"):
            return
        if self.default_ca.exists():
            if not (force_refresh and self._allow_cert_refresh()):
                self.session.verify = str(self.default_ca)
                return

        pem = self._fetch_peer_cert()
        if pem:
            try:
                self.default_ca.parent.mkdir(parents=True, exist_ok=True)
                self.default_ca.write_text(pem, encoding="ascii")
                try:
                    os.chmod(self.default_ca, 0o600)
                except OSError:
                    pass
                self.session.verify = str(self.default_ca)
            except Exception as exc:
                logger.warning("Could not persist appliance cert at %s: %s", self.default_ca, exc)

    def _get_json(self, path: str, timeout: int = 5) -> Optional[Any]:
        """GET a JSON document, retrying once after a cert refresh on SSL errors."""
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        url = f"{self.api_url}{path}"
        for attempt in (1, 2):
            try:
                resp = self.session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return _json_or_none(resp)
                logger.debug("GET %s returned HTTP %s", path, resp.status_code)
                return None
            except requests.exceptions.SSLError:
                if attempt == 1 and self._allow_cert_refresh():
                    self._ensure_appliance_cert(force_refresh=True)
                    continue
                logger.debug("SSL failure on GET %s (attempt %d)", path, attempt)
                return None
            except Exception as exc:
                logger.debug("Request to %s failed: %s", path, exc)
                return None
        return None

    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Fetch available agents from the connected SAFi backend URL."""
        data = self._get_json("/api/agents/all")
        if isinstance(data, dict) and data.get("ok") and isinstance(data.get("available"), list):
            return data["available"]
        return []

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Fetch available models for the Intellect faculty from the connected SAFi backend."""
        data = self._get_json("/api/models")
        if isinstance(data, dict) and data.get("ok") and isinstance(data.get("models"), list):
            return data["models"]
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

        if tools is not None:
            tools_payload = tools
        else:
            tools_payload = get_tools_for_agent(agent)

        ws_context: Dict[str, Any] = {
            "working_directory": workspace_root,
            "workspace_root": workspace_root,
        }
        try:
            sp_path = Path(workspace_root) / ".safi" / "scratchpad.md"
            if sp_path.is_file():
                raw_sp = sp_path.read_text(encoding="utf-8", errors="replace").strip()
                if raw_sp:
                    # Enforce 6,000 char anti-bloat limit
                    max_sp_chars = int(os.environ.get("SAFI_SCRATCHPAD_MAX_CHARS", "6000"))
                    if len(raw_sp) > max_sp_chars:
                        raw_sp = raw_sp[:max_sp_chars] + f"\n... [scratchpad truncated to {max_sp_chars:,} characters]"
                    ws_context["scratchpad"] = raw_sp
        except Exception as exc:
            logger.warning("Could not attach workspace scratchpad context: %s", exc)

        payload: Dict[str, Any] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message": message,
            "agent": agent,
            "workspace_context": ws_context,
            "tools": tools_payload,
            "tool_results": truncate_tool_results(tool_results or []),
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
            if self._allow_cert_refresh():
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
            else:
                raise SafiClientError(
                    f"SSL certificate verification failed for {self.endpoint}. "
                    f"If the appliance was reinstalled, remove {self.default_ca} or set SAFI_TRUST_ON_REINSTALL=1.",
                    details=str(exc),
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
            err_data = _json_or_none(resp)
            if err_data and "error" in err_data:
                err_msg = err_data["error"]
            raise SafiClientError(
                f"Backend rejected turn (HTTP {resp.status_code}): {err_msg}",
                status_code=resp.status_code,
                details=resp.text,
            )

        try:
            data = resp.json()
        except ValueError:
            raise SafiClientError("Backend returned invalid non-JSON response.", details=resp.text)
        try:
            return normalize_turn_response(data)
        except SchemaError as exc:
            raise SafiClientError(
                f"Backend returned a malformed turn response: {exc}",
                status_code=200,
                details=str(data)[:500],
            )

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
        except Exception as exc:
            logger.debug("Progress poll for %s failed: %s", message_id, exc)
            return None
        return None

    def compress_conversation(
        self,
        conversation_id: str,
        user_id: str,
        agent: str = "software_engineer",
        model: Optional[str] = None,
        action: str = "compress",
        clear_agent_memory: bool = False,
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
        if clear_agent_memory or action in ("clear", "reset"):
            payload["clear_agent_memory"] = True
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
            err_data = _json_or_none(resp) or {}
            return {
                "ok": False,
                "error": err_data.get("error", f"Server returned HTTP {resp.status_code}"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_agent_memory(
        self,
        conversation_id: str,
        user_id: str,
        agent: str = "software_engineer",
    ) -> Dict[str, Any]:
        """Clear both conversation memory summary and accumulated agent work context."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        payload = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "agent": agent,
            "action": "clear",
            "clear_agent_memory": True,
        }
        try:
            resp = self.session.post(
                f"{self.api_url}/api/agentic/compress",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"ok": False}
        except Exception as exc:
            logger.warning("Compress request failed: %s", exc)
            return {"ok": False}
