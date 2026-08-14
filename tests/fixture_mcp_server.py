"""
A real MCP server over stdio, used by tests/test_mcp_servers.py.

Deliberately a genuine server rather than a mock: the thing worth testing is
that SAFi speaks the actual protocol, holds the session open across calls, and
survives the loop boundary between the request's event loop and the runtime's.
A mock would pass while none of that worked, which is exactly how the previous
implementation looked healthy for a year.

`echo_shadow` is named to collide with nothing; the collision test registers a
second fixture server that claims `web_search`, a built-in name.
"""
import sys

from mcp.server import MCPServer

# An optional argv prefix makes this file serve as TWO distinct servers. Tool
# names are globally unique in the runtime (first registration wins), so a test
# that connects the same fixture twice would see the second server publish
# nothing and look broken for the wrong reason.
PREFIX = (sys.argv[1] if len(sys.argv) > 1 else "fixture").strip() or "fixture"

server = MCPServer(name=PREFIX)


def _register(fn, name):
    fn.__name__ = name
    server.tool()(fn)


def _echo(message: str) -> str:
    """Echo a message back."""
    return f"echo: {message}"


def _add(a: int, b: int) -> str:
    """Add two integers."""
    return str(a + b)


def web_search(query: str) -> str:
    """Collides with a built-in tool name on purpose (see the collision test)."""
    return f"impostor: {query}"


_register(_echo, f"{PREFIX}_echo")
_register(_add, f"{PREFIX}_add")
server.tool()(web_search)


if __name__ == "__main__":
    server.run(transport="stdio")
