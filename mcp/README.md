# Operator MCP server definitions

`servers.json` in this directory is the declarative list of MCP tool servers for
this deployment. It is **mounted into the container** at `/app/mcp/servers.json`,
so declarations survive image rebuilds.

> **Note on SAFi v1.5.0+**: Dynamic runtime installation of third-party MCP
> servers (`scripts/safi_mcp.py add`) is **disabled** to harden container
> security and protect the supply chain.
> - **Enterprise Tools**: Native gateways for Google Workspace and Microsoft Graph
>   ship pre-configured as isolated services under `gateways/` (start with
>   `docker compose --profile gateways up -d`).
> - **Workstation / File Operations**: Run client-side via `safi_cli`, governed by
>   the SAFi policy engine.
> - **Built-in Connectors**: Internal tools live in `safi_app/core/mcp_servers/`.

`servers.json` is gitignored: it is deployment configuration, not source.
If you need to declare a custom internal MCP server (HTTP, SSE, or stdio), define
it statically in `servers.json`:

```json
{
  "demo": {
    "label": "Demo Server",
    "transport": "stdio",
    "command": "python",
    "args": ["/app/mcp/demo_server.py"]
  }
}
```

Anything a server definition points at has to live on this mount for the same
reason the definitions do. A path inside the container (`/tmp/...`) survives
until the next rebuild and then reports "Connection closed", which is the SDK
saying the command died without saying why.

Use the operator CLI to inspect or toggle declared servers:

    docker compose exec app python scripts/safi_mcp.py list
    docker compose exec app python scripts/safi_mcp.py check
    docker compose exec app python scripts/safi_mcp.py disable <key>
