"""
The MCP client runtime: persistent sessions to operator-installed MCP servers.

Everything here is transport and lifecycle. Governance lives where it already
lived before this module existed: an MCP server becomes a CONNECTOR
(tool_connectors.py), an organization allows it (connector_governance.py), a
policy grants it, and the Will authorizes each call by exact name. Discovery
adds catalogue entries and nothing else. See GOVERNANCE_BACKLOG 47b.

WHY A DEDICATED THREAD AND ITS OWN EVENT LOOP
---------------------------------------------
Flask[async] runs each async view through asgiref, so a request's event loop
does not outlive the request. An MCP session cannot survive that: its streams,
its task group and (for stdio) its subprocess transport are bound to the loop
that created them, and awaiting them from a different loop is an error. Holding
sessions open therefore needs a loop this process owns for its whole lifetime,
which is what start() creates: one daemon thread running one loop, with every
session living on it. Request-side code never touches that loop directly. It
submits a coroutine with run_coroutine_threadsafe and awaits the result on its
own loop through wrap_future, so nothing blocks a worker thread.

WHY EACH SERVER PARKS ON AN EVENT
---------------------------------
The SDK exposes transports and sessions as async context managers, so the only
way to hold one open is to stay inside the `async with` body. Each server gets
one supervisor task that enters the transport, initializes the session,
publishes its tools, and then waits on a shutdown event. Setting that event
unwinds the context managers in the correct order.

TRUST, STATED PLAINLY
---------------------
A stdio server is an arbitrary command this process executes. The server list
comes from a file on disk, so only whoever controls the deployment can add one:
no request path can define, edit or reach a server definition, and no
organization admin can install one through the browser. This is the same trust
level as SAFI_EXTENSIONS_DIR, where the developer guide already says installing
an extension equals installing the package.

FAILURE IS ALWAYS "TOOL ABSENT"
-------------------------------
A server that will not start, will not initialize, or answers nothing is logged
and skipped. It never degrades to "present but unguarded": a tool that is not
discovered is not in the catalogue, is not expanded into any profile, and is
therefore blocked by the Will's allow-list if a model names it anyway.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# How long to wait for a server to connect and answer tools/list at boot, and
# how long a single tool call may run. Both are per server and overridable in
# the server definition.
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_CALL_TIMEOUT = 60.0

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Substitute ${VAR} from the process environment.

    Secrets belong in the environment, not in the server file: the file is
    committed or copied often enough that a token in it will eventually end up
    somewhere it should not be. An unset variable expands to empty rather than
    raising, and the server then fails its own auth loudly, which is a better
    error than a KeyError at boot with no context.
    """
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def describe_exception(exc: BaseException, transport: str = "") -> str:
    """Flatten an ExceptionGroup into something a person can act on.

    The SDK's transports run inside anyio task groups, so almost every
    connection failure arrives as `ExceptionGroup: unhandled errors in a
    TaskGroup (1 sub-exception)`, sometimes nested two deep. `str(e)` on that
    tells an admin nothing at all, while the leaf underneath is invariably the
    actual answer: a 404 on the wrong path, DNS that does not resolve, or an
    auth challenge.

    Leaves are collected in order and de-duplicated, then a hint is appended for
    the three failures that are common and opaque: an auth challenge (what an
    anonymous connection to a server wanting OAuth looks like), a 404, and a
    stdio server whose command died on startup. `transport` is optional and only
    selects the last of those.
    """
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
        # What a stdio server that died on startup looks like. The SDK reports
        # the pipe closing and says nothing about why, which is useless to an
        # operator: the usual cause is that the command is not there at all, or
        # exited immediately. A file the definition points at can disappear
        # without the definition changing, which is exactly how this is met.
        message += (
            ". The command exited immediately. Check that the file or binary it "
            "names still exists on this host and runs on its own; a server "
            "pointing at a path inside a container is lost when the container "
            "is rebuilt."
        )
    return message


def _render_result(result: Any) -> str:
    """Flatten an MCP CallToolResult into the plain string the orchestrator
    feeds back to the Intellect as a tool observation."""
    if result is None:
        return "Tool returned no result."

    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
            continue
        # Non-text blocks (images, audio, embedded resources) are described
        # rather than dropped: the model needs to know something came back.
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
    """Process-wide owner of the MCP loop, sessions and discovered tools.

    One instance, module-level. Not a per-request object: SAFi orchestrator
    instances are cached per (agent, models, policy) and built lazily per
    request (api/conversations.py), so anything owning sessions per instance
    would spawn a duplicate set of subprocesses for every cached agent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stops: Dict[str, asyncio.Event] = {}
        self._sessions: Dict[str, Any] = {}
        # tool name -> {"server", "name", "title", "description", "input_schema"}
        self._tools: Dict[str, Dict[str, Any]] = {}
        # server key -> {"label", "tools": [names], "error": str | None}
        self._servers: Dict[str, Dict[str, Any]] = {}
        # server key -> "file" | "db". Only db-sourced servers are subject to
        # sync_db_servers; the operator's file always wins and is never dropped.
        self._origins: Dict[str, str] = {}
        self._started = False

    # ---------- lifecycle ----------

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_loop(self) -> None:
        """Create the thread and loop if they do not exist yet.

        Separate from start() because servers can now arrive after boot: an
        install through the GUI must connect on a deployment where the file was
        empty and no loop was ever needed.
        """
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="safi-mcp", daemon=True)
        self._thread.start()

    def _connect_one(
        self, name: str, params: Dict[str, Any], reserved_tool_names, origin: str
    ) -> Dict[str, Any]:
        """Connect a single server and wait for it to publish. Never raises."""
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

    def probe(self, params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        """Connect, list tools, disconnect. Registers nothing.

        Exists so an admin finds out at install time whether a server actually
        answers, instead of after an approval round-trip. Roughly half of the
        public registry's hosted entries do not connect anonymously (auth
        required, moved endpoint, dead host), so discovering that immediately is
        most of the usability of the feature.

        This contacts an unapproved server, which is deliberate and harmless:
        approval gates whether agents may USE a server, and a probe sends only
        an initialize and a tools/list. Nothing of the publisher's runs here.
        """
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
        """Probe many servers at once, concurrently, on the runtime loop.

        Sequential probing is unusable for this: measured against the public
        registry, most hosted entries do not answer, and each failure costs the
        full timeout. Thirty servers one after another is minutes; gathered on
        one loop it is the slowest single probe.
        """
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
        """Connect a server that arrived after boot. Replaces one of the same name."""
        with self._lock:
            if name in self._stops:
                self._drop(name)
            return self._connect_one(name, params, reserved_tool_names, origin)

    def _drop(self, name: str) -> None:
        """Unwind one server and forget its tools. Caller holds the lock."""
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
        """Make the servers from one origin match `desired`, leaving the other
        origin alone.

        The two origins are independent on purpose. A row in a table must not be
        able to unplug something the operator put in the deployment's own file,
        and re-reading the file must not drop what an organization installed
        through the GUI. Syncing them separately is what keeps that true without
        either side needing to know about the other.
        """
        with self._lock:
            current = {n for n, o in self._origins.items() if o == origin}
            for name in current - set(desired):
                log.info("MCP server '%s' removed; disconnecting.", name)
                self._drop(name)
            for name, params in desired.items():
                if name in current and self._servers.get(name, {}).get("error") is None:
                    continue
                if name in self._stops:
                    self._drop(name)
                log.info("MCP server '%s' installed; connecting.", name)
                self._connect_one(name, params, reserved_tool_names, origin)

    def start(self, servers: Dict[str, Dict[str, Any]], reserved_tool_names) -> Dict[str, Any]:
        """Connect every enabled server and return a discovery summary.

        Called once at boot from create_app(). Idempotent: a second call is a
        no-op returning the existing summary, so an import-order surprise or a
        test that calls it twice cannot spawn a second set of subprocesses.
        """
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
                ready = threading.Event()
                timeout = float(params.get("connect_timeout") or DEFAULT_CONNECT_TIMEOUT)
                self._origins[name] = "file"
                asyncio.run_coroutine_threadsafe(
                    self._supervise(name, params, ready, reserved_tool_names), self._loop
                )
                waits.append((name, ready, timeout))

            for name, ready, timeout in waits:
                if not ready.wait(timeout):
                    # Not fatal and not retried here: the supervisor may still
                    # come up, and if it does its tools simply appear late. What
                    # must not happen is boot blocking on a wedged server.
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
        """Own one server for the life of the process: connect, publish, park."""
        stop = asyncio.Event()
        self._stops[name] = stop
        entry: Dict[str, Any] = {"label": params.get("label") or name, "tools": [], "error": None}
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
            # BaseException, not Exception: an ExceptionGroup raised by the
            # SDK's task groups is not always an Exception subclass, and
            # catching too narrowly here would let a connection failure escape
            # into the runtime loop instead of being reported on the server.
            entry["error"] = describe_exception(e, (params.get("transport") or "stdio").lower())
            log.error("MCP server '%s' failed: %s", name, entry["error"])
        finally:
            self._sessions.pop(name, None)
            self._stops.pop(name, None)
            ready.set()

    def _open_transport(self, transport: str, params: Dict[str, Any]):
        """Return the SDK's async context manager for the configured transport."""
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
        # The child inherits nothing by default. An MCP server that needs a
        # token gets it named explicitly in `env`, so reading the file tells you
        # exactly what the subprocess can see.
        return stdio_client(
            StdioServerParameters(
                command=str(command),
                args=[str(a) for a in (params.get("args") or [])],
                env=_expand(params.get("env")) or None,
                cwd=params.get("cwd") or None,
            )
        )

    def _publish(self, server: str, entry: Dict[str, Any], listed: Any, reserved_tool_names) -> None:
        """Record discovered tools, refusing any name that is already spoken for.

        Precedence is built-ins, then first server to claim a name. A third
        party must never be able to redefine `web_search` or take over another
        server's tool: the model would call the same name and reach different
        code, which is the one failure mode nobody would spot in an audit
        record.
        """
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
        """Unwind every session and stop the loop. Tests use this; the process
        exiting is the normal path."""
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

    # ---------- read side ----------

    def is_running(self) -> bool:
        return self._loop is not None and bool(self._sessions)

    def tools(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tools)

    def tools_for_server(self, server: str) -> List[str]:
        return list((self._servers.get(server) or {}).get("tools") or [])

    def origin_of(self, server: str) -> str:
        """"file" (the operator's), "db" (installed through the GUI), or ""."""
        return self._origins.get(server, "")

    def connectors(self) -> Dict[str, Tuple[str, ...]]:
        """server key -> its tool names, the connector-bundle shape."""
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
                }
                for name, entry in self._servers.items()
            },
            "tool_count": len(self._tools),
        }

    # ---------- call side ----------

    def owns(self, tool_name: str) -> bool:
        return tool_name in self._tools

    async def call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a discovered tool and return its result as text.

        Reached only after the Will approved the call by exact name. The bridge
        across loops is the two lines below: submit to the loop that owns the
        session, then await the result on the caller's own loop so no worker
        thread blocks.
        """
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

        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool_name, arguments or {}), loop
        )
        try:
            result = await asyncio.wait_for(
                asyncio.wrap_future(future), timeout=DEFAULT_CALL_TIMEOUT
            )
        except asyncio.TimeoutError:
            future.cancel()
            return f"ERROR: tool '{tool_name}' timed out after {DEFAULT_CALL_TIMEOUT:.0f}s."
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


def probe(params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    return _runtime.probe(params, timeout)


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
