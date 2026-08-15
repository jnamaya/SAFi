#!/usr/bin/env python3
"""The Workspace gateway: per-user Google tools over the MCP authorization spec.

GOVERNANCE_BACKLOG 48j. SAFi's members press Sign in, authenticate at Google's
own consent screen, and from then on every Workspace tool call runs as the
member who asked, with SAFi never touching a Google credential.

The OAuth machinery (co-located AS + RS, PKCE, RFC 8707, encrypted upstream
tokens, hashed refresh tokens) lives in gateway_core.py, shared with the Graph
gateway since 48k needed a second provider. This file is only what is
Google-shaped: the endpoints, the scopes, how identity is read out of the
token response, and the tools. The design reasoning and the two-role
architecture are documented on the core.

WHAT IS DELIBERATELY ABSENT
---------------------------
Write tools. v1 is calendar list, drive search and read, gmail search, and
whoami, all reads, matching the standing doctrine: nothing that sends, moves
or deletes until SAFi can hold a call for human review. Add write tools here
only alongside that.

RUNNING IT
----------
    GATEWAY_BASE_URL=https://gw.example.com        # public URL of this service
    GOOGLE_CLIENT_ID=...                           # a Google OAuth client
    GOOGLE_CLIENT_SECRET=...
    GATEWAY_ENCRYPTION_KEY=<Fernet key>            # encrypts Google tokens at rest
    GATEWAY_DB=/home/safi/workspace-gateway.db     # sqlite, single file
    PORT=8402
    python scripts/workspace_gateway.py

The Google client must list {GATEWAY_BASE_URL}/google/callback as an authorized
redirect URI. Install in SAFi with:

    scripts/safi_mcp.py add --url {GATEWAY_BASE_URL}/mcp --auth oauth

Run it as ONE process: authorization codes and sessions live in sqlite, but the
signing key is loaded once and uvicorn here is deliberately single-worker.

GOOGLE_OAUTH_BASE / GOOGLE_TOKEN_URL / GOOGLE_API_BASE exist so the test suite
can stand in for Google; production never sets them.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("workspace-gateway")


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

BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://localhost:8402").rstrip("/")
RESOURCE_URI = f"{BASE_URL}/mcp"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DB_PATH = os.environ.get("GATEWAY_DB", "workspace-gateway.db")
PORT = int(os.environ.get("PORT", "8402"))

# Test seams. Production never sets these; the suite points them at a stub.
GOOGLE_OAUTH_BASE = os.environ.get("GOOGLE_OAUTH_BASE", "https://accounts.google.com")
GOOGLE_TOKEN_URL = os.environ.get("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
GOOGLE_API_BASE = os.environ.get("GOOGLE_API_BASE", "https://www.googleapis.com")

# Read-only scopes, matching the read-only tool set. Widening this list is a
# governance decision, not a convenience: every scope here is something every
# signed-in member grants.
GOOGLE_SCOPES = (
    "openid email "
    "https://www.googleapis.com/auth/calendar.readonly "
    "https://www.googleapis.com/auth/drive.readonly "
    "https://www.googleapis.com/auth/gmail.readonly"
)


def _google_identity(token_response: Dict[str, Any]) -> tuple:
    # The id_token arrived over TLS directly from Google's token endpoint in a
    # server-to-server exchange, the one context where decoding without a JWKS
    # round trip is sound (see decode_jwt_segment).
    claims = core.decode_jwt_segment(token_response["id_token"])
    return str(claims.get("sub")), str(claims.get("email", ""))


PROVIDER = core.UpstreamProvider(
    name="Google",
    authorize_url=f"{GOOGLE_OAUTH_BASE}/o/oauth2/v2/auth",
    token_url=GOOGLE_TOKEN_URL,
    scopes=GOOGLE_SCOPES,
    callback_path="/google/callback",
    # offline for a refresh token; consent because Google only issues one on a
    # consented grant.
    authorize_extra={"access_type": "offline", "prompt": "consent"},
    extract_identity=_google_identity,
)


# ── Google, over plain REST ───────────────────────────────────────────────────

def _google_access_token(store: Store, subject: str) -> Optional[str]:
    return core.upstream_access_token(
        store, PROVIDER, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, subject)


def _google_get(store: Store, path: str, params: Dict[str, Any]) -> Any:
    import requests

    token = _google_access_token(store, current_subject.get())
    if not token:
        return {"error": "No Google authorization is stored for you. Sign in to this server again from Settings."}
    resp = requests.get(f"{GOOGLE_API_BASE}{path}", params=params,
                        headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code != 200:
        return {"error": f"Google answered {resp.status_code}: {resp.text[:200]}"}
    return resp.json()


# ── The ASGI app ──────────────────────────────────────────────────────────────

def build_app(store: Optional[Store] = None):
    from mcp.server import MCPServer

    store = store or Store(DB_PATH)

    server = MCPServer(name="google-workspace-gateway")

    @server.tool()
    def whoami() -> str:
        """Report the Google identity this call runs as."""
        tokens = store.upstream_tokens(current_subject.get())
        return f"Authorized as {tokens['email'] if tokens else 'nobody'}"

    @server.tool()
    def calendar_list_events(time_min: str = "", time_max: str = "",
                             max_results: int = 10) -> str:
        """List events on the member's primary Google Calendar.
        Times are RFC 3339 (e.g. 2026-08-15T00:00:00Z); both optional."""
        params: Dict[str, Any] = {"maxResults": min(int(max_results or 10), 50),
                                  "singleEvents": "true", "orderBy": "startTime"}
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        data = _google_get(store, "/calendar/v3/calendars/primary/events", params)
        if "error" in data:
            return f"ERROR: {data['error']}"
        items = [
            f"- {e.get('summary', '(no title)')} "
            f"[{(e.get('start') or {}).get('dateTime') or (e.get('start') or {}).get('date', '?')}]"
            for e in data.get("items", [])
        ]
        return "\n".join(items) or "No events in that window."

    @server.tool()
    def drive_search(query: str, max_results: int = 10) -> str:
        """Search the member's Google Drive by file name."""
        safe = (query or "").replace("'", "\\'")
        data = _google_get(store, "/drive/v3/files", {
            "q": f"name contains '{safe}' and trashed = false",
            "pageSize": min(int(max_results or 10), 50),
            "fields": "files(name,mimeType,modifiedTime,webViewLink)",
        })
        if "error" in data:
            return f"ERROR: {data['error']}"
        items = [f"- {f['name']} ({f.get('mimeType','?')}, modified {f.get('modifiedTime','?')})"
                 for f in data.get("files", [])]
        return "\n".join(items) or "No files matched."

    @server.tool()
    def drive_get_file_contents(file_id: str, max_chars: int = 20000) -> str:
        """Read a file's text content from the member's Google Drive by id
        (drive_search returns ids). Google Docs are exported as plain text;
        other files are fetched raw and decoded best-effort. Read-only."""
        meta = _google_get(store, f"/drive/v3/files/{file_id}", {"fields": "name,mimeType"})
        if "error" in meta:
            return f"ERROR: {meta['error']}"
        import requests
        token = _google_access_token(store, current_subject.get())
        mime = meta.get("mimeType", "")
        if mime.startswith("application/vnd.google-apps"):
            url = f"{GOOGLE_API_BASE}/drive/v3/files/{file_id}/export"
            params = {"mimeType": "text/plain"}
        else:
            url = f"{GOOGLE_API_BASE}/drive/v3/files/{file_id}"
            params = {"alt": "media"}
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if resp.status_code != 200:
            return f"ERROR: Google answered {resp.status_code} reading {meta.get('name', file_id)}"
        text = resp.content[: max(1000, int(max_chars or 20000)) * 4].decode("utf-8", "replace")
        limit = max(1000, int(max_chars or 20000))
        clipped = text[:limit]
        suffix = "" if len(text) <= limit else f"\n[truncated at {limit} characters]"
        return f"{meta.get('name', file_id)}:\n{clipped}{suffix}"

    @server.tool()
    def gmail_search(query: str, max_results: int = 5) -> str:
        """Search the member's Gmail; returns sender, subject and date."""
        listing = _google_get(store, "/gmail/v1/users/me/messages", {
            "q": query, "maxResults": min(int(max_results or 5), 20)})
        if "error" in listing:
            return f"ERROR: {listing['error']}"
        out = []
        for ref in listing.get("messages", [])[:max_results]:
            msg = _google_get(store, f"/gmail/v1/users/me/messages/{ref['id']}", {
                "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            if "error" in msg:
                continue
            headers = {h["name"]: h["value"]
                       for h in (msg.get("payload") or {}).get("headers", [])}
            out.append(f"- {headers.get('Subject','(no subject)')} | "
                       f"{headers.get('From','?')} | {headers.get('Date','?')}")
        return "\n".join(out) or "No messages matched."

    return core.build_gateway_app(
        base_url=BASE_URL, store=store, provider=PROVIDER,
        client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET,
        mcp_server=server, scope_label="workspace.read",
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    print(f"workspace gateway on :{PORT}\n  issuer/AS: {BASE_URL}\n  resource:  {RESOURCE_URI}")
    # Single worker on purpose: see the module docstring.
    uvicorn.run(build_app(), host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
