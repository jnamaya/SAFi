#!/usr/bin/env python3
"""Install and manage MCP tool servers from the operator's console.

WHY A CLI EXISTS WHEN THERE IS ALREADY A SCREEN
-----------------------------------------------
The screen can only install HOSTED servers, and that is not a limitation to be
worked around: starting a package server runs someone else's code on this host,
which is deployment-level trust and cannot belong to anyone holding an admin
login in a browser (GOVERNANCE_BACKLOG 48).

The consequence is that the browser reaches the minority of the ecosystem, and
the least reliable part of it: hosted servers are exactly the ones most likely
to want OAuth, and measured against the public registry on 2026-08-14 only four
of ten answered anonymously. The npm and pypi servers that make up most of the
ecosystem work reliably and were unreachable.

Whoever runs this CLI already has shell on the host, so installing a package
server here adds no privilege that was not already held. That is the whole
argument: the CLI is not a bypass, it is the place the decision already lives.

WHERE THIS SITS IN THE PIPELINE
-------------------------------
    1. install here, on the host
    2. SAFi connects and asks the server what tools it has
    3. those tools appear in Settings -> Tools Catalog, visible and INACTIVE
    4. a policy editor enables specific tools and blocks the rest
    5. an agent is assigned the tools its policy allows
    6. the Will authorizes every call by exact name

This command is step 1 only. It grants nothing, and nothing it does can widen
what any existing agent may do.

NO RESTART NEEDED
-----------------
Writing the file is not enough on its own: each gunicorn worker read it at boot.
Every write here also bumps the shared generation counter, which is how the GUI
already tells other workers to catch up, so a server added here appears in the
running app within one request per worker.

Usage:
  scripts/safi_mcp.py list
  scripts/safi_mcp.py search <term>
  scripts/safi_mcp.py add <registry-name> [--key NAME]
  scripts/safi_mcp.py add --url https://example.com/mcp [--transport http|sse]
  scripts/safi_mcp.py add --url https://example.com/mcp --auth oauth
  scripts/safi_mcp.py add --command npx --args="-y,@scope/server@1.2.3" [--env K=V]
  scripts/safi_mcp.py add --command node --args="scripts/start.js" --cwd /app/mcp/thing
  scripts/safi_mcp.py check [--key NAME]
  scripts/safi_mcp.py remove <key>
  scripts/safi_mcp.py enable <key> | disable <key>
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# The script's own directory goes on sys.path[0] automatically, and this file
# must not be importable as `mcp`: the SDK is imported by name deep inside
# mcp_runtime, and a script called mcp.py shadowed it for its own process
# ("cannot import name StdioServerParameters from mcp"). Hence safi_mcp.py, and
# hence dropping the script directory rather than trusting the name alone.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
sys.path.insert(0, os.path.dirname(_HERE))

from safi_app.config import Config, _load_mcp_servers  # noqa: E402
from safi_app.core import mcp_runtime  # noqa: E402
from safi_app.core.services import mcp_install, mcp_registry  # noqa: E402
from safi_app.core.tool_connectors import CONNECTOR_TOOLS  # noqa: E402

KEY_SAFE = re.compile(r"[^a-z0-9_]+")

# npx/uvx fetch from the network at every boot unless the package is pinned, so
# an unpinned entry means the code running on this host can change without
# anyone touching this deployment. Warned about rather than refused: pinning is
# the operator's call, and some internal packages are versioned elsewhere.
UNPINNED_WARNING = (
    "warning: no version pin. This command fetches the package at every boot, so "
    "what runs here can change without anyone changing this deployment. Pin it "
    "(e.g. @scope/server@1.2.3) unless you control the package."
)


def _server_file() -> Path:
    path = (os.environ.get("MCP_SERVERS_JSON") or "").strip()
    if not path:
        fail("MCP_SERVERS_JSON is not set. Point it at a JSON file (see .env.example).")
    return Path(path)


def fail(message: str, code: int = 1):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_servers() -> dict:
    return _load_mcp_servers() or {}


def write_servers(servers: dict) -> None:
    """Write the file, then tell the running app to re-read it.

    The bump is best effort: a CLI run on a host whose database is down should
    still be able to edit the file, and say plainly that a restart is needed.
    """
    path = _server_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(servers, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"wrote {path}")

    from safi_app.persistence import mcp_store

    if mcp_store.bump_generation():
        print("running workers will pick this up on their next request")
    else:
        print("note: could not signal the running app. Restart it to apply.")


def derive_key(text: str) -> str:
    tail = (text or "").strip().lower().rsplit("/", 1)[-1]
    key = KEY_SAFE.sub("_", tail).strip("_")
    return key or "mcp_server"


def unique_key(base: str, servers: dict) -> str:
    candidate = base
    suffix = 2
    while candidate in CONNECTOR_TOOLS or candidate in servers:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def check_runtime_available(params: dict) -> None:
    """Refuse a stdio server whose launcher is not installed here.

    Most registry packages are npm, and a host with no Node could never start
    one. Without this check the CLI would happily write a definition that can
    never start, and the failure would surface later as a server that is simply
    absent. Say it now, name the missing binary, and let the operator decide
    whether to install the runtime.

    `shutil.which` decides, so this adapts to wherever it runs rather than
    assuming: the Docker image carries node, npm and npx (see the Dockerfile's
    copy from `node:22-slim`), while a bare-metal host or a venv outside the
    container may carry none of them. That is the case this exists for, and the
    hints below are worded for it.
    """
    import shutil

    if (params.get("transport") or "stdio") != "stdio":
        return
    command = params.get("command")
    if not command or shutil.which(command):
        return
    hint = {
        # The container image ships Node, so npx missing means this is running
        # somewhere else: a bare-metal host, or a venv outside the container.
        "npx": "install Node.js on this host (the Docker image already has it)",
        "uvx": "install uv (pip install uv), which provides uvx",
        "docker": "the docker CLI is not available inside this container",
    }.get(command, "install it, or point --command at a binary that exists here")
    fail(
        f"{command!r} is not on PATH here, so this server could never start. {hint}.\n"
        f"       Servers that are hosted (--url) need no local runtime at all."
    )


def probe_and_report(key: str, params: dict) -> bool:
    result = mcp_runtime.probe(params, timeout=25.0)
    if not result["ok"]:
        print(f"  {key}: FAILED  {result['error']}")
        return False
    if not result["tools"]:
        print(f"  {key}: connected but advertises no tools")
        return False
    print(f"  {key}: ok, {len(result['tools'])} tool(s): {', '.join(result['tools'][:8])}")
    return True


# --- commands ----------------------------------------------------------------

def cmd_list(args) -> int:
    servers = read_servers()
    if not servers:
        print("No servers in the operator's file.")
    for key, params in servers.items():
        state = "" if params.get("enabled", True) else "  [disabled]"
        where = params.get("url") or f"{params.get('command','')} {' '.join(params.get('args') or [])}".strip()
        print(f"{key}{state}\n    {params.get('transport', 'stdio')}  {where}")

    return 0


def cmd_search(args) -> int:
    try:
        result = mcp_registry.search(query=args.term, limit=args.limit, config=Config)
    except mcp_registry.RegistryError as e:
        fail(str(e))
    if not result["servers"]:
        print("No matches.")
        return 0
    for entry in result["servers"]:
        kind = "hosted" if entry["has_remote"] else "package"
        pkg = ""
        if entry["packages"]:
            first = entry["packages"][0]
            pkg = f"  [{first['registry_type']}:{first['identifier']}@{first['version'] or 'unpinned'}]"
        print(f"{entry['name']}  ({kind}, v{entry['version'] or '?'}){pkg}")
        if entry["description"]:
            print(f"    {entry['description'][:110]}")
    print("\nAdd one with:  scripts/safi_mcp.py add <name>")
    return 0


def _entry_from_registry(name: str) -> dict:
    """Build a server definition from a registry entry, preferring a hosted
    endpoint and falling back to the package the entry publishes."""
    try:
        entry = mcp_registry.get_server(name, config=Config)
    except mcp_registry.RegistryError as e:
        fail(str(e))
    if entry is None:
        fail(f"no registry entry named exactly {name!r}")

    for remote in entry["remotes"]:
        ok, why = mcp_registry.validate_remote_url(remote["url"])
        if ok:
            return {
                "label": entry["title"],
                "transport": remote["transport"],
                "url": remote["url"],
            }
        print(f"note: skipping endpoint {remote['url']}: {why}")

    for package in entry["packages"]:
        registry_type = package["registry_type"]
        identifier = package["identifier"]
        version = package["version"]
        if registry_type == "npm":
            spec = f"{identifier}@{version}" if version else identifier
            command, cmd_args = "npx", ["-y", spec]
        elif registry_type == "pypi":
            spec = f"{identifier}=={version}" if version else identifier
            command, cmd_args = "uvx", [spec]
        else:
            print(f"note: skipping {registry_type} package, no launcher for it here")
            continue
        if not version:
            print(UNPINNED_WARNING)
        return {
            "label": entry["title"],
            "transport": "stdio",
            "command": command,
            "args": cmd_args,
        }

    fail("that entry publishes no endpoint this CLI can install")


def cmd_add(args) -> int:
    servers = read_servers()

    if args.url:
        ok, why = mcp_registry.validate_remote_url(args.url)
        if not ok:
            fail(why)
        params = {"transport": args.transport, "url": args.url}
        if args.auth:
            params["auth"] = args.auth
            if args.client_id:
                params["client_id"] = args.client_id
            if args.client_secret:
                params["client_secret"] = args.client_secret
            if args.scopes:
                params["scopes"] = [s.strip() for s in args.scopes.split(",") if s.strip()]
        base = mcp_install.connector_key_for_url(args.url)
    elif args.command:
        cmd_args = [a for a in (args.args or "").split(",") if a]
        params = {"transport": "stdio", "command": args.command, "args": cmd_args}
        if args.cwd:
            params["cwd"] = args.cwd
        if args.env:
            params["env"] = dict(
                pair.split("=", 1) for pair in args.env if "=" in pair
            )
        joined = " ".join(cmd_args)
        if "@" not in joined and "==" not in joined:
            print(UNPINNED_WARNING)
        base = derive_key(cmd_args[-1] if cmd_args else args.command)
    elif args.name:
        params = _entry_from_registry(args.name)
        base = derive_key(args.name)
    else:
        fail("give a registry name, or --url, or --command")

    if args.orgs:
        params["orgs"] = [o.strip() for o in args.orgs.split(",") if o.strip()]

    key = args.key or unique_key(base, servers)
    if key in CONNECTOR_TOOLS:
        fail(f"{key!r} is a built-in connector name; choose another with --key")
    if key in servers and not args.force:
        fail(f"{key!r} already exists; pass --force to replace it")

    if args.label:
        params["label"] = args.label

    check_runtime_available(params)

    if params.get("auth") == "oauth":
        # An OAuth server refuses anonymous connections by design, so the MCP
        # probe would only prove what the spec already promises. What CAN be
        # checked without a token is the discovery chain: the server's
        # protected-resource metadata and its IdP's endpoints.
        from safi_app.core.services import mcp_oauth
        try:
            discovery = mcp_oauth.discover(params["url"])
            print(f"  {key}: OAuth-protected, authorization server {discovery['issuer']}")
        except mcp_oauth.OAuthConfigError as e:
            if not args.force:
                fail(str(e))
            print(f"  warning: {e}")
    else:
        print(f"checking {key} ...")
        if not probe_and_report(key, params) and not args.force:
            fail("not added. Fix the server or pass --force to add it anyway.")

    servers[key] = params
    write_servers(servers)
    print(
        f"\nadded {key!r}. Its tools are now visible and INACTIVE in "
        "Settings -> Tools Catalog.\nEnable the ones you want in a policy, under "
        "Tools & Guardrails. They then become available\nto every agent that uses "
        "that policy. Nothing can call them until then."
    )
    return 0


def cmd_check(args) -> int:
    servers = read_servers()
    if args.key:
        if args.key not in servers:
            fail(f"no server named {args.key!r}")
        servers = {args.key: servers[args.key]}
    if not servers:
        print("Nothing to check.")
        return 0

    oauth_servers = {k: v for k, v in servers.items()
                     if v.get("enabled", True) and (v.get("auth") or "").lower() == "oauth"}
    for key, params in oauth_servers.items():
        from safi_app.core.services import mcp_oauth
        try:
            discovery = mcp_oauth.discover(params["url"])
            print(f"  {key}: OAuth-protected, IdP {discovery['issuer']} reachable")
        except mcp_oauth.OAuthConfigError as e:
            print(f"  {key}: FAILED  {e}")

    probeable = {k: v for k, v in servers.items()
                 if v.get("enabled", True) and k not in oauth_servers}
    print(f"checking {len(probeable)} server(s) ...")
    failures = 0
    results = mcp_runtime.probe_many(probeable, timeout=25.0)
    for key, result in results.items():
        if result["ok"] and result["tools"]:
            print(f"  {key}: ok, {len(result['tools'])} tool(s)")
        else:
            failures += 1
            print(f"  {key}: FAILED  {result['error'] or 'no tools advertised'}")
    return 1 if failures else 0


def cmd_remove(args) -> int:
    servers = read_servers()
    if args.key not in servers:
        fail(f"no server named {args.key!r}")
    del servers[args.key]
    write_servers(servers)
    print(f"removed {args.key!r}. Agents granted it lose those tools.")
    return 0


def _set_enabled(key: str, enabled: bool) -> int:
    servers = read_servers()
    if key not in servers:
        fail(f"no server named {key!r}")
    servers[key]["enabled"] = enabled
    write_servers(servers)
    print(f"{key!r} {'enabled' if enabled else 'disabled'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/safi_mcp.py",
        description="Install and manage MCP tool servers for this deployment.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show configured servers")

    p_search = sub.add_parser("search", help="search the MCP registry")
    p_search.add_argument("term", nargs="?", default="")
    p_search.add_argument("--limit", type=int, default=20)

    p_add = sub.add_parser("add", help="add a server")
    p_add.add_argument("name", nargs="?", help="registry name, e.g. io.github.owner/server")
    p_add.add_argument("--url", help="hosted endpoint instead of a registry name")
    p_add.add_argument("--transport", default="http", choices=("http", "sse"))
    p_add.add_argument(
        "--auth", choices=("oauth",),
        help="'oauth' marks a server that implements the MCP authorization "
             "specification: each member signs in from the app and every call "
             "runs with that member's audience-bound token. The catalog is "
             "discovered at the first sign-in, not at install",
    )
    p_add.add_argument("--command", help="local command for a stdio server")
    p_add.add_argument(
        "--args",
        help="comma-separated arguments for --command. Use the = form when the "
             "first argument starts with a dash, e.g. --args=\"-y,@scope/pkg\", "
             "or argparse reads it as an option",
    )
    p_add.add_argument(
        "--cwd",
        help="working directory for --command. Needed by servers distributed as "
             "a checkout rather than a package, which resolve their own files "
             "relative to where they were started",
    )
    p_add.add_argument(
        "--client-id",
        help="OAuth client id for an --auth oauth server whose IdP does not "
             "offer dynamic registration (GitHub, for one). ${VAR} is read "
             "from the environment at use time",
    )
    p_add.add_argument(
        "--client-secret",
        help="OAuth client secret, same rules. Pass a ${VAR} reference rather "
             "than the literal secret so the server file stays safe to copy",
    )
    p_add.add_argument(
        "--scopes",
        help="comma-separated OAuth scopes to request at sign-in. Set this for "
             "IdPs whose advertised scope list includes writes you do not "
             "want every member granting",
    )
    p_add.add_argument(
        "--orgs",
        help="comma-separated organization ids allowed to use this server. "
             "Absent means every organization, which is right for a "
             "single-tenant install and wrong to assume on a shared one. "
             "Guests never get installed servers regardless",
    )
    p_add.add_argument("--env", action="append", help="KEY=VALUE for the child process")
    p_add.add_argument("--key", help="connector key (defaults to a derived name)")
    p_add.add_argument("--label", help="display name shown in the tool picker")
    p_add.add_argument("--force", action="store_true", help="add even if it fails its check")

    p_check = sub.add_parser("check", help="connect to servers and report")
    p_check.add_argument("--key")

    p_remove = sub.add_parser("remove", help="remove a server")
    p_remove.add_argument("key")

    p_enable = sub.add_parser("enable", help="enable a configured server")
    p_enable.add_argument("key")
    p_disable = sub.add_parser("disable", help="keep the definition, stop connecting")
    p_disable.add_argument("key")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            return cmd_list(args)
        if args.cmd == "search":
            return cmd_search(args)
        if args.cmd == "add":
            return cmd_add(args)
        if args.cmd == "check":
            return cmd_check(args)
        if args.cmd == "remove":
            return cmd_remove(args)
        if args.cmd == "enable":
            return _set_enabled(args.key, True)
        if args.cmd == "disable":
            return _set_enabled(args.key, False)
    finally:
        mcp_runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
