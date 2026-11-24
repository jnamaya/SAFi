from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_CALL_TIMEOUT = float(os.environ.get("SAFI_MCP_CALL_TIMEOUT", "60"))

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _positive_float(raw: Any, fallback: float, server_name: str) -> float:
    if raw is None or raw == "":
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        log.error("MCP server '%s': call_timeout %r is not a number; using %.0fs.",
                  server_name, raw, fallback)
        return fallback
    if value <= 0:
        log.error("MCP server '%s': call_timeout %r is not positive; using %.0fs.",
                  server_name, raw, fallback)
        return fallback
    return value


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def describe_exception(exc: BaseException, transport: str = "") -> str:
    leaves: List[str] = []

    def walk(e: BaseException) -> None:
        subs = getattr(e, "exceptions", None)
        if subs:
            for sub in subs:
                walk(sub)
        else:
            leaves.append(f"{type(e).__name__}: {e}".strip())

    walk(exc)
    seen, ordered = set(), []
    for leaf in leaves:
        if leaf not in seen:
            seen.add(leaf)
            ordered.append(leaf)

    message = "; ".join(ordered) or f"{type(exc).__name__}: {exc}"
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered or "server returned an error response" in lowered:
        message += (
            ". This server may require credentials. Servers needing a token must "
            "be installed in the operator's MCP_SERVERS_JSON file, where the "
            "secret can be supplied from the environment."
        )
    elif "not found" in lowered or "404" in lowered:
        message += ". The endpoint may be wrong or the server may no longer be hosted."
    elif transport == "stdio" and "closed" in lowered:
        message += (
            ". The command exited immediately. Check that the file or binary it "
            "names still exists on this host and runs on its own; a server "
            "pointing at a path inside a container is lost when the container "
            "is rebuilt."
        )
    return message


def _render_result(result: Any) -> str:
    if result is None:
        return "Tool returned no result."

    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
            continue
        parts.append(f"[{getattr(block, 'type', 'content')} block omitted]")

    structured = getattr(result, "structured_content", None)
    if not parts and structured is not None:
        try:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
        except Exception:
            parts.append(str(structured))

    body = "\n".join(p for p in parts if p) or str(result)
    if getattr(result, "is_error", False):
        return f"ERROR: {body}"
    return body


class _Runtime:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stops: Dict[str, asyncio.Event] = {}
        self._sessions: Dict[str, Any] = {}
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._servers: Dict[str, Dict[str, Any]] = {}
        self._origins: Dict[str, str] = {}
        self._started = False


    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="safi-mcp", daemon=True)
        self._thread.start()

    def _connect_one(
        self, name: str, params: Dict[str, Any], reserved_tool_names, origin: str
    ) -> Dict[str, Any]:
        self._ensure_loop()
        ready = threading.Event()
        timeout = float(params.get("connect_timeout") or DEFAULT_CONNECT_TIMEOUT)
        self._origins[name] = origin
        asyncio.run_coroutine_threadsafe(
            self._supervise(name, params, ready, reserved_tool_names), self._loop
        )
        if not ready.wait(timeout):
            log.error(
                "MCP server '%s' did not become ready within %.0fs; "
                "its tools are absent.", name, timeout
            )
            self._servers.setdefault(name, {"label": name, "tools": []})
            self._servers[name]["error"] = f"timeout after {timeout:.0f}s"
        return self._servers.get(name, {"label": name, "tools": [], "error": "unknown"})

    def register_offline(self, name: str, params: Dict[str, Any],
                         reserved_tool_names=(), origin: str = "file") -> Dict[str, Any]:
        with self._lock:
            return self._register_offline_locked(name, params, reserved_tool_names, origin)

    def _register_offline_locked(self, name, params, reserved_tool_names=(), origin="file"):
        if True:
            if name in self._stops or name in self._servers:
                self._drop(name)
            entry: Dict[str, Any] = {
                "label": params.get("label") or name,
                "tools": [],
                "error": None,
                "orgs": [str(o) for o in (params.get("orgs") or []) if o],
                "auth": "oauth",
                "url": params.get("url") or "",
            }
            self._servers[name] = entry
            self._origins[name] = origin
            reserved = set(reserved_tool_names or ())
            for tool in params.get("cached_tools") or []:
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                if tool_name in reserved or tool_name in self._tools:
                    log.error("MCP server '%s': tool '%s' collides and was skipped.",
                              name, tool_name)
                    continue
                self._tools[tool_name] = {
                    "server": name,
                    "name": tool_name,
                    "title": tool_name,
                    "description": tool.get("description") or "",
                    "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
                }
                entry["tools"].append(tool_name)
            return entry

    def auth_mode_of(self, server: str) -> str:
        return (self._servers.get(server) or {}).get("auth") or ""

    def url_of(self, server: str) -> str:
        return (self._servers.get(server) or {}).get("url") or ""

    def probe(self, params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        self._ensure_loop()

        async def _run() -> Dict[str, Any]:
            transport = (params.get("transport") or "stdio").lower()
            try:
                async with self._open_transport(transport, params) as streams:
                    from mcp import ClientSession

                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        names = [
                            getattr(t, "name", "") for t in (getattr(listed, "tools", None) or [])
                        ]
                        return {"ok": True, "tools": [n for n in names if n], "error": None}
            except BaseException as e:
                return {"ok": False, "tools": [], "error": describe_exception(e, transport)}

        future = asyncio.run_coroutine_threadsafe(_run(), self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            return {
                "ok": False,
                "tools": [],
                "error": f"The server did not answer within {timeout:.0f}s.",
            }

    def probe_many(
        self, specs: Dict[str, Dict[str, Any]], timeout: float = 12.0
    ) -> Dict[str, Dict[str, Any]]:
        if not specs:
            return {}
        self._ensure_loop()

        async def _one(params: Dict[str, Any]) -> Dict[str, Any]:
            transport = (params.get("transport") or "stdio").lower()
            try:
                async with self._open_transport(transport, params) as streams:
                    from mcp import ClientSession

                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        names = [
                            getattr(t, "name", "") for t in (getattr(listed, "tools", None) or [])
                        ]
                        return {"ok": True, "tools": [n for n in names if n], "error": None}
            except BaseException as e:
                return {"ok": False, "tools": [], "error": describe_exception(e, transport)}

        async def _gather() -> Dict[str, Dict[str, Any]]:
            keys = list(specs)
            tasks = [
                asyncio.wait_for(_one(specs[k]), timeout=timeout) for k in keys
            ]
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            out: Dict[str, Dict[str, Any]] = {}
            for key, result in zip(keys, settled):
                if isinstance(result, BaseException):
                    out[key] = {
                        "ok": False,
                        "tools": [],
                        "error": f"The server did not answer within {timeout:.0f}s.",
                    }
                else:
                    out[key] = result
            return out

        future = asyncio.run_coroutine_threadsafe(_gather(), self._loop)
        try:
            return future.result(timeout=timeout + 10)
        except Exception:
            future.cancel()
            return {k: {"ok": False, "tools": [], "error": "Probe timed out."} for k in specs}

    def add_server(
        self, name: str, params: Dict[str, Any], reserved_tool_names=(), origin: str = "db"
    ) -> Dict[str, Any]:
        with self._lock:
            if name in self._stops:
                self._drop(name)
            return self._connect_one(name, params, reserved_tool_names, origin)

    def _drop(self, name: str) -> None:
        stop = self._stops.get(name)
        if stop is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(stop.set)
        for tool_name, spec in list(self._tools.items()):
            if spec["server"] == name:
                del self._tools[tool_name]
        self._servers.pop(name, None)
        self._sessions.pop(name, None)
        self._origins.pop(name, None)

    def remove_server(self, name: str) -> None:
        with self._lock:
            self._drop(name)

    def sync_db_servers(self, desired: Dict[str, Dict[str, Any]], reserved_tool_names=()) -> None:
        self.sync_origin(desired, reserved_tool_names, origin="db")

    def sync_origin(
        self, desired: Dict[str, Dict[str, Any]], reserved_tool_names=(), origin: str = "db"
    ) -> None:
        with self._lock:
            current = {n for n, o in self._origins.items() if o == origin}
            for name in current - set(desired):
                log.info("MCP server '%s' removed; disconnecting.", name)
                self._drop(name)
            for name, params in desired.items():
                if (params.get("auth") or "").lower() == "oauth":
                    self._register_offline_locked(name, params, reserved_tool_names, origin)
                    continue
                if name in current and self._servers.get(name, {}).get("error") is None:
                    continue
                if name in self._stops:
                    self._drop(name)
                log.info("MCP server '%s' installed; connecting.", name)
                self._connect_one(name, params, reserved_tool_names, origin)

    def start(self, servers: Dict[str, Dict[str, Any]], reserved_tool_names) -> Dict[str, Any]:
        with self._lock:
            if self._started:
                return self.summary()
            self._started = True

            servers = servers or {}
            if not servers:
                return self.summary()

            self._ensure_loop()

            waits: List[Tuple[str, threading.Event, float]] = []
            for name, params in servers.items():
                if not isinstance(params, dict):
                    log.error("MCP server '%s': definition is not an object, skipped.", name)
                    continue
                if not params.get("enabled", True):
                    log.info("MCP server '%s': disabled in config, skipped.", name)
                    continue
                if (params.get("auth") or "").lower() == "oauth":
                    self._register_offline_locked(name, params, reserved_tool_names, "file")
                    entry = self._servers.get(name, {})
                    log.info(
                        "MCP server '%s' registered (per-user sign-in): %d cached tool(s).",
                        name, len(entry.get("tools") or []),
                    )
                    continue
                ready = threading.Event()
                timeout = float(params.get("connect_timeout") or DEFAULT_CONNECT_TIMEOUT)
                self._origins[name] = "file"
                asyncio.run_coroutine_threadsafe(
                    self._supervise(name, params, ready, reserved_tool_names), self._loop
                )
                waits.append((name, ready, timeout))

            for name, ready, timeout in waits:
                if not ready.wait(timeout):
                    log.error(
                        "MCP server '%s' did not become ready within %.0fs; "
                        "its tools are absent from this boot.", name, timeout
                    )
                    self._servers.setdefault(name, {"label": name, "tools": []})
                    self._servers[name]["error"] = f"timeout after {timeout:.0f}s"

            return self.summary()

    async def _supervise(
        self, name: str, params: Dict[str, Any], ready: threading.Event, reserved_tool_names
    ) -> None:
        stop = asyncio.Event()
        self._stops[name] = stop
        entry: Dict[str, Any] = {
            "label": params.get("label") or name,
            "tools": [],
            "error": None,
            "orgs": [str(o) for o in (params.get("orgs") or []) if o],
            "call_timeout": _positive_float(
                params.get("call_timeout"), DEFAULT_CALL_TIMEOUT, name
            ),
        }
        self._servers[name] = entry
        try:
            transport = (params.get("transport") or "stdio").lower()
            async with self._open_transport(transport, params) as streams:
                read_stream, write_stream = streams[0], streams[1]
                from mcp import ClientSession

                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self._sessions[name] = session
                    self._publish(name, entry, listed, reserved_tool_names)
                    log.info(
                        "MCP server '%s' connected over %s: %d tool(s) discovered (%s).",
                        name, transport, len(entry["tools"]),
                        ", ".join(entry["tools"]) or "none",
                    )
                    ready.set()
                    await stop.wait()
        except BaseException as e:
            entry["error"] = describe_exception(e, (params.get("transport") or "stdio").lower())
            log.error("MCP server '%s' failed: %s", name, entry["error"])
        finally:
            self._sessions.pop(name, None)
            self._stops.pop(name, None)
            ready.set()

    def _open_transport(self, transport: str, params: Dict[str, Any]):
        if transport in ("http", "streamable_http", "streamable-http"):
            from mcp.client.streamable_http import streamable_http_client

            url = _expand(params.get("url") or "")
            if not url:
                raise ValueError("http transport requires 'url'")
            return streamable_http_client(url)

        if transport == "sse":
            from mcp.client.sse import sse_client

            url = _expand(params.get("url") or "")
            if not url:
                raise ValueError("sse transport requires 'url'")
            return sse_client(url)

        if transport != "stdio":
            raise ValueError(f"unknown transport '{transport}'")

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        command = params.get("command")
        if not command:
            raise ValueError("stdio transport requires 'command'")
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "TMPDIR": "/tmp",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        user_env = _expand(params.get("env")) or {}
        blocked_keys = {
            "SAFI_ENCRYPTION_KEY", "DB_PASSWORD", "DATABASE_URL",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
            "GOOGLE_API_KEY", "SECRET_KEY", "JWT_SECRET", "ADMIN_PASSWORD",
        }
        for k, v in user_env.items():
            if k not in blocked_keys:
                clean_env[k] = str(v)

        return stdio_client(
            StdioServerParameters(
                command=str(command),
                args=[str(a) for a in (params.get("args") or [])],
                env=clean_env,
                cwd=params.get("cwd") or None,
            )
        )

    def _publish(self, server: str, entry: Dict[str, Any], listed: Any, reserved_tool_names) -> None:
        reserved = set(reserved_tool_names or ())
        for tool in getattr(listed, "tools", None) or []:
            tool_name = getattr(tool, "name", None)
            if not tool_name:
                continue
            if tool_name in reserved:
                log.error(
                    "MCP server '%s': tool '%s' collides with a built-in tool name "
                    "and was skipped. Built-ins win.", server, tool_name
                )
                continue
            if tool_name in self._tools:
                log.error(
                    "MCP server '%s': tool '%s' is already provided by server '%s' "
                    "and was skipped. First registration wins.",
                    server, tool_name, self._tools[tool_name]["server"],
                )
                continue
            schema = getattr(tool, "input_schema", None)
            if hasattr(schema, "model_dump"):
                schema = schema.model_dump(exclude_none=True)
            self._tools[tool_name] = {
                "server": server,
                "name": tool_name,
                "title": getattr(tool, "title", None) or tool_name,
                "description": getattr(tool, "description", None) or "",
                "input_schema": schema or {"type": "object", "properties": {}},
            }
            entry["tools"].append(tool_name)

    def shutdown(self) -> None:
        with self._lock:
            loop = self._loop
            if loop is None:
                self._started = False
                return
            for stop in list(self._stops.values()):
                loop.call_soon_threadsafe(stop.set)
            loop.call_soon_threadsafe(loop.stop)
            if self._thread:
                self._thread.join(timeout=10)
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None
            self._thread = None
            self._sessions.clear()
            self._tools.clear()
            self._servers.clear()
            self._stops.clear()
            self._origins.clear()
            self._started = False


    def is_running(self) -> bool:
        return self._loop is not None and bool(self._sessions)

    def tools(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tools)

    def tools_for_server(self, server: str) -> List[str]:
        return list((self._servers.get(server) or {}).get("tools") or [])

    def orgs_for(self, server: str) -> List[str]:
        return list((self._servers.get(server) or {}).get("orgs") or [])

    def origin_of(self, server: str) -> str:
        return self._origins.get(server, "")

    def connectors(self) -> Dict[str, Tuple[str, ...]]:
        return {
            name: tuple(entry.get("tools") or ())
            for name, entry in self._servers.items()
            if entry.get("tools")
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "servers": {
                name: {
                    "label": entry.get("label") or name,
                    "tools": list(entry.get("tools") or []),
                    "error": entry.get("error"),
                    "auth": entry.get("auth") or "",
                    "orgs": list(entry.get("orgs") or []),
                }
                for name, entry in self._servers.items()
            },
            "tool_count": len(self._tools),
        }


    def owns(self, tool_name: str) -> bool:
        return tool_name in self._tools

    async def call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        spec = self._tools.get(tool_name)
        if spec is None:
            return f"ERROR: tool '{tool_name}' is not provided by any connected MCP server."
        session = self._sessions.get(spec["server"])
        loop = self._loop
        if session is None or loop is None:
            return (
                f"ERROR: the MCP server '{spec['server']}' providing '{tool_name}' "
                "is not connected."
            )

        timeout = float(
            (self._servers.get(spec["server"]) or {}).get("call_timeout")
            or DEFAULT_CALL_TIMEOUT
        )
        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool_name, arguments or {}), loop
        )
        try:
            result = await asyncio.wait_for(
                asyncio.wrap_future(future), timeout=timeout
            )
        except asyncio.TimeoutError:
            future.cancel()
            return f"ERROR: tool '{tool_name}' timed out after {timeout:.0f}s."
        except BaseException as e:
            return f"ERROR: tool '{tool_name}' failed: {describe_exception(e)}"
        return _render_result(result)


_runtime = _Runtime()


def start(servers: Dict[str, Dict[str, Any]], reserved_tool_names=()) -> Dict[str, Any]:
    return _runtime.start(servers, reserved_tool_names)


def shutdown() -> None:
    _runtime.shutdown()


def is_running() -> bool:
    return _runtime.is_running()


def tools() -> Dict[str, Dict[str, Any]]:
    return _runtime.tools()


def tools_for_server(server: str) -> List[str]:
    return _runtime.tools_for_server(server)


def origin_of(server: str) -> str:
    return _runtime.origin_of(server)


def orgs_for(server: str) -> List[str]:
    return _runtime.orgs_for(server)


def server_of(tool_name: str) -> str:
    return (_runtime.tools().get(tool_name) or {}).get("server", "")


def probe(params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    return _runtime.probe(params, timeout)


def register_offline(name: str, params: Dict[str, Any], reserved_tool_names=(), origin: str = "file"):
    return _runtime.register_offline(name, params, reserved_tool_names, origin)


def auth_mode_of(server: str) -> str:
    return _runtime.auth_mode_of(server)


def url_of(server: str) -> str:
    return _runtime.url_of(server)


async def call_with_token(url: str, tool_name: str, arguments: Dict[str, Any],
                          token: str, timeout: float = DEFAULT_CALL_TIMEOUT) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    try:
        async with streamable_http_client(url, http_client=http_client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments or {}), timeout=timeout
                )
                return _render_result(result)
    except asyncio.TimeoutError:
        return f"ERROR: tool '{tool_name}' timed out after {timeout:.0f}s."
    except BaseException as e:
        message = describe_exception(e, "http")
        lowered = message.lower()
        if "401" in lowered or "unauthorized" in lowered or "server returned an error response" in lowered:
            return (
                f"ERROR: the server refused '{tool_name}'. Either your "
                "authorization has expired (reconnect the account in Settings), "
                "or it was granted without a scope this tool needs (an operator "
                "must widen the server's scopes, then reconnect), or the "
                "arguments were invalid."
            )
        return f"ERROR: tool '{tool_name}' failed: {message}"


async def list_tools_with_token(url: str, token: str, timeout: float = 20.0):
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with streamable_http_client(url, http_client=http_client) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            listed = await asyncio.wait_for(session.list_tools(), timeout=timeout)
            out = []
            for tool in getattr(listed, "tools", None) or []:
                schema = getattr(tool, "input_schema", None)
                if hasattr(schema, "model_dump"):
                    schema = schema.model_dump(exclude_none=True)
                out.append({
                    "name": getattr(tool, "name", ""),
                    "description": getattr(tool, "description", None) or "",
                    "input_schema": schema or {"type": "object", "properties": {}},
                })
            return [t for t in out if t["name"]]


def probe_many(specs: Dict[str, Dict[str, Any]], timeout: float = 12.0) -> Dict[str, Dict[str, Any]]:
    return _runtime.probe_many(specs, timeout)


def add_server(name: str, params: Dict[str, Any], reserved_tool_names=(), origin: str = "db"):
    return _runtime.add_server(name, params, reserved_tool_names, origin)


def remove_server(name: str) -> None:
    _runtime.remove_server(name)


def sync_db_servers(desired: Dict[str, Dict[str, Any]], reserved_tool_names=()) -> None:
    _runtime.sync_db_servers(desired, reserved_tool_names)


def sync_origin(desired: Dict[str, Dict[str, Any]], reserved_tool_names=(), origin: str = "db") -> None:
    _runtime.sync_origin(desired, reserved_tool_names, origin)


def connectors() -> Dict[str, Tuple[str, ...]]:
    return _runtime.connectors()


def summary() -> Dict[str, Any]:
    return _runtime.summary()


def owns(tool_name: str) -> bool:
    return _runtime.owns(tool_name)


async def call(tool_name: str, arguments: Dict[str, Any]) -> str:
    return await _runtime.call(tool_name, arguments)
