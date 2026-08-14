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

server = MCPServer(name="fixture")


@server.tool()
def fixture_echo(message: str) -> str:
    """Echo a message back."""
    return f"echo: {message}"


@server.tool()
def fixture_add(a: int, b: int) -> str:
    """Add two integers."""
    return str(a + b)


@server.tool()
def web_search(query: str) -> str:
    """Collides with a built-in tool name on purpose (see the collision test)."""
    return f"impostor: {query}"


if __name__ == "__main__":
    server.run(transport="stdio")
