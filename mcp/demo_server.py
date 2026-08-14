#!/usr/bin/env python3
"""A tiny MCP server, so the tool pipeline can be seen working end to end.

Install it from the host:

    docker compose exec app python scripts/safi_mcp.py add \\
        --command python --args "/app/mcp/demo_server.py" --key demo --label "Demo Server"

Then enable `demo_echo` (and not `demo_word_count`) in a policy's Tools &
Guardrails step, assign that policy to an agent, and watch the agent gain
exactly one of the two.

WHY IT LIVES HERE
-----------------
This directory is mounted into the container; `safi_app/` is copied into the
image. A demo server under the copied path would be replaced on every
`docker compose up --build`, and a server whose file has vanished reports
"Connection closed", which says nothing about what happened. Anything the
operator points a server definition at has to live on a mount for the same
reason the definitions do.

The tools are deliberately dull. The point of the demo is the governance path,
not the tool: a policy enabling one of these and not the other is the whole
demonstration.
"""
from mcp.server import MCPServer

server = MCPServer(name="safi-demo")


@server.tool()
def demo_echo(message: str) -> str:
    """Echo a message back, unchanged. Harmless, and useful for proving a call
    reached the server and came back."""
    return f"echo: {message}"


@server.tool()
def demo_word_count(text: str) -> str:
    """Count the words in a piece of text.

    Exists so a policy can enable one tool of this server and not the other,
    which is the thing worth seeing.
    """
    return f"{len(text.split())} words"


if __name__ == "__main__":
    server.run(transport="stdio")
