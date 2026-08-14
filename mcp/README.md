# Operator MCP server definitions

`servers.json` in this directory is the list of MCP tool servers this
deployment has installed. It is **mounted into the container**, not baked into
the image, so servers added with `scripts/safi_mcp.py` survive a rebuild.

That mount is the whole reason this directory exists. Before it, the file lived
inside the package, the Dockerfile copied it in at build time, and every
`docker compose up --build` silently replaced an operator's server list with the
empty file from the repo.

`servers.json` is gitignored: it is deployment configuration, not source. Manage
it with the CLI rather than by hand:

    docker compose exec app python scripts/safi_mcp.py list
    docker compose exec app python scripts/safi_mcp.py add --url https://example.com/mcp
