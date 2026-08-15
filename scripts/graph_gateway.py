#!/usr/bin/env python3
"""The Graph gateway: per-user Microsoft 365 tools over the MCP authorization spec.

GOVERNANCE_BACKLOG 48k, third slice. Microsoft ships an official MCP server,
but it is gated behind an M365 Copilot license, and SAFi cannot require a
competing AI product's license as a dependency for its own tools (Nelson's
Path B ruling, 2026-08-15). So this gateway does for Microsoft Graph what the
Workspace gateway does for Google: members sign in at Microsoft's own consent
screen, and every tool call runs as the member who asked, with SAFi never
touching a Microsoft credential.

The OAuth machinery (co-located AS + RS, PKCE, RFC 8707, encrypted upstream
tokens, hashed refresh tokens) lives in gateway_core.py, shared with the
Workspace gateway. This file is only what is Microsoft-shaped: the Entra
endpoints, the delegated scopes, how identity is read out of the token
response, and the tools.

WHAT IS DELIBERATELY ABSENT
---------------------------
Write tools, same doctrine as the Workspace gateway: nothing that sends,
moves, uploads or deletes until SAFi can hold a call for human review. The
scopes match: User.Read, Files.Read.All, Sites.Read.All, nothing writable.

RUNNING IT
----------
    GATEWAY_BASE_URL=https://graph-gw.example.com  # public URL of this service
    ENTRA_CLIENT_ID=...                            # an Entra app registration
    ENTRA_CLIENT_SECRET=...
    ENTRA_TENANT=organizations                     # or a tenant id to pin one
    GATEWAY_ENCRYPTION_KEY=<Fernet key>            # encrypts Graph tokens at rest
    GATEWAY_DB=/home/safi/graph-gateway.db         # sqlite, single file
    PORT=8403
    python scripts/graph_gateway.py

The Entra app registration must list {GATEWAY_BASE_URL}/microsoft/callback as
a Web redirect URI, hold a client secret, and have the delegated Graph
permissions User.Read, Files.Read.All and Sites.Read.All (admin consent not
required for these, members consent individually). Install in SAFi with:

    scripts/safi_mcp.py add --url {GATEWAY_BASE_URL}/mcp --auth oauth

Run it as ONE process, single-worker, same reasoning as the Workspace gateway.

MS_OAUTH_BASE / MS_TOKEN_URL / GRAPH_API_BASE exist so the test suite can
stand in for Microsoft; production never sets them.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("graph-gateway")


def _load_core():
    # By explicit path rather than sys.path: scripts/ must never enter the
    # import path (a scripts/mcp.py once shadowed the SDK and cost a day).
    import importlib.util
    if "gateway_core" in sys.modules:
        return sys.modules["gateway_core"]
    spec = importlib.util.spec_from_file_location(
        "gateway_core", Path(__file__).resolve().parent / "gateway_core.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gateway_core"] = module
    spec.loader.exec_module(module)
    return module


core = _load_core()
current_subject = core.current_subject
Store = core.Store

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://localhost:8403").rstrip("/")
RESOURCE_URI = f"{BASE_URL}/mcp"
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "")
# "organizations" lets any work or school account sign in; a deployment that
# serves one tenant pins its tenant id here instead.
ENTRA_TENANT = os.environ.get("ENTRA_TENANT", "organizations")
DB_PATH = os.environ.get("GATEWAY_DB", "graph-gateway.db")
PORT = int(os.environ.get("PORT", "8403"))

# Test seams. Production never sets these; the suite points them at a stub.
MS_OAUTH_BASE = os.environ.get("MS_OAUTH_BASE", "https://login.microsoftonline.com")
MS_TOKEN_URL = os.environ.get(
    "MS_TOKEN_URL", f"{MS_OAUTH_BASE}/{ENTRA_TENANT}/oauth2/v2.0/token")
GRAPH_API_BASE = os.environ.get("GRAPH_API_BASE", "https://graph.microsoft.com/v1.0")

# Delegated read-only scopes, matching the read-only tool set. offline_access
# is what makes Entra return a refresh token. Widening this list is a
# governance decision, not a convenience.
GRAPH_SCOPES = (
    "openid email offline_access "
    "User.Read Files.Read.All Sites.Read.All"
)


def _entra_identity(token_response: Dict[str, Any]) -> tuple:
    # The id_token arrived over TLS directly from Entra's token endpoint in a
    # server-to-server exchange, the one context where decoding without a JWKS
    # round trip is sound (see decode_jwt_segment).
    claims = core.decode_jwt_segment(token_response["id_token"])
    email = str(claims.get("email") or claims.get("preferred_username") or "")
    return str(claims.get("sub")), email


PROVIDER = core.UpstreamProvider(
    name="Microsoft",
    authorize_url=f"{MS_OAUTH_BASE}/{ENTRA_TENANT}/oauth2/v2.0/authorize",
    token_url=MS_TOKEN_URL,
    scopes=GRAPH_SCOPES,
    callback_path="/microsoft/callback",
    extract_identity=_entra_identity,
    # No revoke_url: Entra offers no public OAuth token-revocation endpoint.
    # /revoke therefore destroys the only stored copy of the refresh token,
    # which is the strongest control available; the token remains technically
    # valid at Microsoft until natural expiry but exists nowhere.
    revoke_url=None,
)


# ── Microsoft Graph, over plain REST ──────────────────────────────────────────

def _graph_access_token(store: Store, subject: str) -> Optional[str]:
    return core.upstream_access_token(
        store, PROVIDER, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, subject)


def _graph_get(store: Store, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    import requests

    token = _graph_access_token(store, current_subject.get())
    if not token:
        return {"error": "No Microsoft authorization is stored for you. Sign in to this server again from Settings."}
    resp = requests.get(f"{GRAPH_API_BASE}{path}", params=params or {},
                        headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code != 200:
        return {"error": f"Microsoft Graph answered {resp.status_code}: {resp.text[:200]}"}
    return resp.json()


def _quote_odata(text: str) -> str:
    # OData string literals escape a single quote by doubling it.
    return (text or "").replace("'", "''")


def _format_drive_items(data: Any) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    items = [
        f"- {item.get('name', '(unnamed)')} "
        f"(id {item.get('id', '?')}, modified {item.get('lastModifiedDateTime', '?')})"
        for item in data.get("value", [])
    ]
    return "\n".join(items) or "No files matched."


# ── The ASGI app ──────────────────────────────────────────────────────────────

def build_app(store: Optional[Store] = None):
    from mcp.server import MCPServer

    store = store or Store(DB_PATH)

    server = MCPServer(name="microsoft-graph-gateway")

    # Not `whoami`: the Workspace gateway already claims that name, and two
    # servers on one deployment collide in mcp_manager's connector registry,
    # where the first registration wins and the loser is skipped. Unique names
    # across our own gateways cost nothing; the collision rule exists for
    # servers we do not control.
    @server.tool()
    def microsoft_whoami() -> str:
        """Report the Microsoft identity this call runs as."""
        tokens = store.upstream_tokens(current_subject.get())
        return f"Authorized as {tokens['email'] if tokens else 'nobody'}"

    @server.tool()
    def files_list(folder_id: str = "", max_results: int = 25) -> str:
        """List files and folders in the member's OneDrive. Lists the drive
        root when folder_id is empty; pass an id from a listing or search
        result to descend into that folder. Read-only."""
        target = (f"/me/drive/items/{folder_id}/children" if folder_id
                  else "/me/drive/root/children")
        data = _graph_get(store, target, {
            "$top": min(int(max_results or 25), 100),
            "$select": "id,name,folder,file,lastModifiedDateTime,size"})
        if "error" in data:
            return f"ERROR: {data['error']}"
        items = []
        for item in data.get("value", []):
            if "folder" in item:
                count = (item.get("folder") or {}).get("childCount")
                detail = f"{count} items" if count is not None else "folder"
                items.append(f"- [folder] {item.get('name', '(unnamed)')} "
                             f"(id {item.get('id', '?')}, {detail})")
            else:
                items.append(f"- {item.get('name', '(unnamed)')} "
                             f"(id {item.get('id', '?')}, modified "
                             f"{item.get('lastModifiedDateTime', '?')})")
        return "\n".join(items) or "The folder is empty."

    @server.tool()
    def files_search(query: str, max_results: int = 10) -> str:
        """Search the member's OneDrive by file name or content."""
        data = _graph_get(
            store, f"/me/drive/root/search(q='{_quote_odata(query)}')",
            {"$top": min(int(max_results or 10), 50),
             "$select": "id,name,lastModifiedDateTime,size,webUrl"})
        return _format_drive_items(data)

    @server.tool()
    def file_get_contents(item_id: str, max_chars: int = 20000) -> str:
        """Read a file's text content from the member's OneDrive by item id
        (files_search returns ids). Fetched raw and decoded best-effort;
        Office formats come back as their stored bytes. Read-only."""
        meta = _graph_get(store, f"/me/drive/items/{item_id}", {"$select": "name"})
        if "error" in meta:
            return f"ERROR: {meta['error']}"
        import requests
        token = _graph_access_token(store, current_subject.get())
        # Graph answers /content with a 302 to a pre-authorized download URL;
        # requests follows it.
        resp = requests.get(f"{GRAPH_API_BASE}/me/drive/items/{item_id}/content",
                            headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if resp.status_code != 200:
            return f"ERROR: Microsoft Graph answered {resp.status_code} reading {meta.get('name', item_id)}"
        limit = max(1000, int(max_chars or 20000))
        text = resp.content[: limit * 4].decode("utf-8", "replace")
        clipped = text[:limit]
        suffix = "" if len(text) <= limit else f"\n[truncated at {limit} characters]"
        return f"{meta.get('name', item_id)}:\n{clipped}{suffix}"

    @server.tool()
    def sites_search(query: str, max_results: int = 10) -> str:
        """Search SharePoint sites the member can see; returns names and ids."""
        data = _graph_get(store, "/sites", {
            "search": query, "$top": min(int(max_results or 10), 50)})
        if "error" in data:
            return f"ERROR: {data['error']}"
        items = [
            f"- {site.get('displayName') or site.get('name', '(unnamed)')} "
            f"(id {site.get('id', '?')}) {site.get('webUrl', '')}"
            for site in data.get("value", [])
        ]
        return "\n".join(items) or "No sites matched."

    @server.tool()
    def site_files_search(site_id: str, query: str, max_results: int = 10) -> str:
        """Search a SharePoint site's default document library by file name or
        content (sites_search returns site ids)."""
        data = _graph_get(
            store,
            f"/sites/{site_id}/drive/root/search(q='{_quote_odata(query)}')",
            {"$top": min(int(max_results or 10), 50),
             "$select": "id,name,lastModifiedDateTime,size,webUrl"})
        return _format_drive_items(data)

    return core.build_gateway_app(
        base_url=BASE_URL, store=store, provider=PROVIDER,
        client_id=ENTRA_CLIENT_ID, client_secret=ENTRA_CLIENT_SECRET,
        mcp_server=server, scope_label="graph.read",
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    print(f"graph gateway on :{PORT}\n  issuer/AS: {BASE_URL}\n  resource:  {RESOURCE_URI}")
    # Single worker on purpose: see the module docstring.
    uvicorn.run(build_app(), host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
