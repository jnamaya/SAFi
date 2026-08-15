#!/usr/bin/env python3
"""The Workspace gateway: per-user Google tools over the MCP authorization spec.

GOVERNANCE_BACKLOG 48j. This is option A made runnable: SAFi's members press
Sign in, authenticate at Google's own consent screen, and from then on every
Workspace tool call runs as the member who asked, with SAFi never touching a
Google credential.

ONE SERVICE, TWO ROLES, ON PURPOSE
----------------------------------
The MCP authorization architecture has three parties: the OAuth client (SAFi,
already built), an Authorization Server, and the protected Resource Server.
This gateway is the second and third co-located:

  AS half   /.well-known/oauth-authorization-server, /register (RFC 7591),
            /authorize (redirects to Google for login and consent), /token
            (PKCE-verified code exchange), /jwks. It mints RS256 JWTs whose
            `aud` is this gateway's /mcp and whose `sub` is the Google account
            id of the person who consented.

  RS half   /.well-known/oauth-protected-resource, and /mcp behind Bearer
            validation: signature against our own JWKS, issuer, expiry, and
            STRICTLY the audience. Tool handlers then act on Google's APIs with
            the GOOGLE tokens stored here, keyed by the verified subject.

Co-locating them is why no RFC 8693 exchange is needed: the spec's "its own
secure mechanism" branch. The property that matters survives intact: the
token SAFi holds opens exactly this gateway for exactly one member, and the
Google refresh token exists only in this process's database, encrypted.

WHAT IS DELIBERATELY ABSENT
---------------------------
Write tools. v1 is calendar list, drive search, gmail search, and whoami, all
reads, matching the standing doctrine: nothing that sends, moves or deletes
until SAFi can hold a call for human review. Add write tools here only
alongside that.

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

GOOGLE_OAUTH_BASE / GOOGLE_API_BASE exist so the test suite can stand in for
Google; production never sets them.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

log = logging.getLogger("workspace-gateway")

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

ACCESS_TOKEN_TTL = int(os.environ.get("GATEWAY_ACCESS_TTL", "3600"))
AUTH_CODE_TTL = 300  # single-use and five minutes, per OAuth 2.1 guidance

current_subject: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_subject", default="")


# ── Storage: sqlite, one file, encrypted where it matters ────────────────────

def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get("GATEWAY_ENCRYPTION_KEY", "")
    if not key:
        raise SystemExit(
            "GATEWAY_ENCRYPTION_KEY is required: it encrypts members' Google "
            "refresh tokens at rest. Generate one with\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


class Store:
    """Everything the gateway must remember, in one sqlite file.

    Google refresh tokens are Fernet-encrypted: they are the crown jewels here,
    long-lived and usable against Google directly. Our own refresh tokens are
    stored as sha256 hashes, never plaintext, because we only ever need to
    check one, not read it back. Auth codes are single-use rows with a short
    expiry, deleted on redemption.
    """

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._fernet = _fernet()
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS signing_key (id INTEGER PRIMARY KEY, jwk TEXT);
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY, redirect_uris TEXT, created_at INTEGER);
                CREATE TABLE IF NOT EXISTS pending_auth (
                    nonce TEXT PRIMARY KEY, payload TEXT, created_at INTEGER);
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code TEXT PRIMARY KEY, payload TEXT, created_at INTEGER);
                CREATE TABLE IF NOT EXISTS google_tokens (
                    subject TEXT PRIMARY KEY, email TEXT,
                    refresh_token_enc TEXT, access_token_enc TEXT, expires_at INTEGER);
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_hash TEXT PRIMARY KEY, subject TEXT, client_id TEXT, created_at INTEGER);
            """)
            self._conn.commit()

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # signing key: generated once, reused forever, so tokens survive restarts
    def signing_key(self):
        from authlib.jose import JsonWebKey

        row = self._exec("SELECT jwk FROM signing_key WHERE id=1").fetchone()
        if row:
            return JsonWebKey.import_key(json.loads(row[0]))
        key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        jwk = key.as_dict(is_private=True)
        jwk["kid"] = "gw-" + secrets.token_hex(4)
        self._exec("INSERT INTO signing_key (id, jwk) VALUES (1, ?)", (json.dumps(jwk),))
        return JsonWebKey.import_key(jwk)

    def register_client(self, redirect_uris) -> str:
        client_id = "gwc-" + secrets.token_urlsafe(24)
        self._exec("INSERT INTO clients (client_id, redirect_uris, created_at) VALUES (?,?,?)",
                   (client_id, json.dumps(list(redirect_uris)), int(time.time())))
        return client_id

    def client_redirects(self, client_id: str):
        row = self._exec("SELECT redirect_uris FROM clients WHERE client_id=?",
                         (client_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_pending(self, nonce: str, payload: Dict[str, Any]):
        self._exec("INSERT INTO pending_auth (nonce, payload, created_at) VALUES (?,?,?)",
                   (nonce, json.dumps(payload), int(time.time())))

    def pop_pending(self, nonce: str) -> Optional[Dict[str, Any]]:
        row = self._exec("SELECT payload, created_at FROM pending_auth WHERE nonce=?",
                         (nonce,)).fetchone()
        self._exec("DELETE FROM pending_auth WHERE nonce=?", (nonce,))
        if not row or time.time() - row[1] > AUTH_CODE_TTL:
            return None
        return json.loads(row[0])

    def put_code(self, code: str, payload: Dict[str, Any]):
        self._exec("INSERT INTO auth_codes (code, payload, created_at) VALUES (?,?,?)",
                   (code, json.dumps(payload), int(time.time())))

    def pop_code(self, code: str) -> Optional[Dict[str, Any]]:
        # Single use: the row is deleted before the payload is judged, so a
        # replayed code finds nothing even if the first redemption failed late.
        row = self._exec("SELECT payload, created_at FROM auth_codes WHERE code=?",
                         (code,)).fetchone()
        self._exec("DELETE FROM auth_codes WHERE code=?", (code,))
        if not row or time.time() - row[1] > AUTH_CODE_TTL:
            return None
        return json.loads(row[0])

    def save_google_tokens(self, subject: str, email: str,
                           refresh_token: Optional[str], access_token: str,
                           expires_in: int):
        enc = self._fernet.encrypt
        existing = self._exec("SELECT refresh_token_enc FROM google_tokens WHERE subject=?",
                              (subject,)).fetchone()
        # Google returns a refresh token only on the first consent; keep the
        # stored one when a re-login omits it.
        refresh_enc = (enc(refresh_token.encode()).decode() if refresh_token
                       else (existing[0] if existing else None))
        self._exec("""INSERT INTO google_tokens (subject, email, refresh_token_enc,
                        access_token_enc, expires_at) VALUES (?,?,?,?,?)
                      ON CONFLICT(subject) DO UPDATE SET email=excluded.email,
                        refresh_token_enc=excluded.refresh_token_enc,
                        access_token_enc=excluded.access_token_enc,
                        expires_at=excluded.expires_at""",
                   (subject, email, refresh_enc,
                    enc(access_token.encode()).decode(),
                    int(time.time()) + int(expires_in or 3600)))

    def google_tokens(self, subject: str) -> Optional[Dict[str, Any]]:
        row = self._exec("""SELECT email, refresh_token_enc, access_token_enc, expires_at
                            FROM google_tokens WHERE subject=?""", (subject,)).fetchone()
        if not row:
            return None
        dec = self._fernet.decrypt
        return {
            "email": row[0],
            "refresh_token": dec(row[1].encode()).decode() if row[1] else None,
            "access_token": dec(row[2].encode()).decode() if row[2] else None,
            "expires_at": row[3],
        }

    def issue_refresh_token(self, subject: str, client_id: str) -> str:
        token = "gwr-" + secrets.token_urlsafe(48)
        digest = hashlib.sha256(token.encode()).hexdigest()
        self._exec("INSERT INTO refresh_tokens (token_hash, subject, client_id, created_at) "
                   "VALUES (?,?,?,?)", (digest, subject, client_id, int(time.time())))
        return token

    def subject_for_refresh(self, token: str) -> Optional[str]:
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = self._exec("SELECT subject FROM refresh_tokens WHERE token_hash=?",
                         (digest,)).fetchone()
        return row[0] if row else None


# ── Google, over plain REST ───────────────────────────────────────────────────

def _google_access_token(store: Store, subject: str) -> Optional[str]:
    """A live Google token for this subject, refreshed with the stored refresh
    token when expired. This function is the upstream exchange: it is the only
    place Google credentials are touched, and its inputs come from a VERIFIED
    JWT subject, never from anything the caller sent."""
    import requests

    tokens = store.google_tokens(subject)
    if not tokens:
        return None
    if tokens["access_token"] and tokens["expires_at"] > time.time() + 30:
        return tokens["access_token"]
    if not tokens["refresh_token"]:
        return None
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
    }, timeout=10)
    if resp.status_code != 200:
        log.warning("google refresh failed for %s: %s", subject, resp.status_code)
        return None
    body = resp.json()
    store.save_google_tokens(subject, tokens["email"], None,
                             body["access_token"], body.get("expires_in", 3600))
    return body["access_token"]


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
    from authlib.jose import JsonWebToken
    from mcp.server import MCPServer

    store = store or Store(DB_PATH)
    key = store.signing_key()
    public_jwk = key.as_dict(is_private=False)
    kid = public_jwk.get("kid")
    jwt = JsonWebToken(["RS256"])

    # ---- the tools (RS half) ----
    server = MCPServer(name="google-workspace-gateway")

    @server.tool()
    def whoami() -> str:
        """Report the Google identity this call runs as."""
        tokens = store.google_tokens(current_subject.get())
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

    # The SDK's DNS-rebinding protection only accepts Host headers it has been
    # told about, and its default is loopback. Behind a reverse proxy with
    # ProxyPreserveHost the Host is the public name, and every request dies as
    # 421 Misdirected Request while every loopback test passes, which is
    # precisely how this shipped broken: the tests could not see it. The
    # allowed list is the server's own public identity plus loopback for local
    # runs and the suite.
    from urllib.parse import urlparse as _urlparse
    from mcp.server.transport_security import TransportSecuritySettings

    _public_host = _urlparse(BASE_URL).netloc
    inner = server.streamable_http_app(
        transport_security=TransportSecuritySettings(
            allowed_hosts=[_public_host, "127.0.0.1", "localhost"],
        )
    )

    # ---- plumbing ----
    async def _read_body(receive) -> bytes:
        body = b""
        while True:
            event = await receive()
            body += event.get("body", b"")
            if not event.get("more_body"):
                return body

    async def _respond(send, status, payload, headers=(), content_type=b"application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", content_type)] + list(headers)})
        await send({"type": "http.response.body", "body": body})

    async def _redirect(send, url):
        await send({"type": "http.response.start", "status": 302,
                    "headers": [(b"location", url.encode())]})
        await send({"type": "http.response.body", "body": b""})

    def _query(scope) -> Dict[str, str]:
        from urllib.parse import parse_qs
        return {k: v[0] for k, v in parse_qs(scope.get("query_string", b"").decode()).items()}

    def _mint_access_token(subject: str) -> str:
        return jwt.encode(
            {"alg": "RS256", "kid": kid},
            {"iss": BASE_URL, "aud": RESOURCE_URI, "sub": subject,
             "exp": int(time.time()) + ACCESS_TOKEN_TTL, "scope": "workspace.read"},
            key,
        ).decode()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        path = scope.get("path", "")
        query = _query(scope)

        # ---- discovery documents, unauthenticated by design ----
        if path.startswith("/.well-known/oauth-protected-resource"):
            return await _respond(send, 200, {
                "resource": RESOURCE_URI,
                "authorization_servers": [BASE_URL],
                "bearer_methods_supported": ["header"],
                "scopes_supported": ["workspace.read"],
            })
        if path.startswith("/.well-known/oauth-authorization-server"):
            return await _respond(send, 200, {
                "issuer": BASE_URL,
                "authorization_endpoint": f"{BASE_URL}/authorize",
                "token_endpoint": f"{BASE_URL}/token",
                "registration_endpoint": f"{BASE_URL}/register",
                "jwks_uri": f"{BASE_URL}/jwks",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
            })
        if path == "/jwks":
            return await _respond(send, 200, {"keys": [public_jwk]})

        # ---- AS half ----
        if path == "/register" and scope["method"] == "POST":
            try:
                body = json.loads((await _read_body(receive)).decode() or "{}")
            except ValueError:
                return await _respond(send, 400, {"error": "invalid_client_metadata"})
            uris = [u for u in (body.get("redirect_uris") or []) if isinstance(u, str)]
            if not uris:
                return await _respond(send, 400, {"error": "invalid_redirect_uri"})
            client_id = store.register_client(uris)
            return await _respond(send, 201, {
                "client_id": client_id, "redirect_uris": uris,
                "token_endpoint_auth_method": "none",
            })

        if path == "/authorize":
            # OAuth 2.1 + RFC 8707, enforced rather than assumed. Refusing here
            # is what makes downstream guarantees real: a request with no PKCE
            # or the wrong resource never reaches Google at all.
            registered = store.client_redirects(query.get("client_id", ""))
            if registered is None:
                return await _respond(send, 400, {"error": "unknown client_id"})
            if query.get("redirect_uri") not in registered:
                return await _respond(send, 400, {"error": "redirect_uri not registered"})
            if query.get("response_type") != "code":
                return await _respond(send, 400, {"error": "only response_type=code is supported"})
            if query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
                return await _respond(send, 400, {"error": "PKCE with S256 is required"})
            if query.get("resource") != RESOURCE_URI:
                return await _respond(send, 400, {
                    "error": f"resource must be {RESOURCE_URI} (RFC 8707)"})
            if not GOOGLE_CLIENT_ID:
                return await _respond(send, 500, {"error": "gateway has no Google client configured"})

            nonce = secrets.token_urlsafe(32)
            store.put_pending(nonce, {
                "client_id": query["client_id"],
                "redirect_uri": query["redirect_uri"],
                "state": query.get("state", ""),
                "code_challenge": query["code_challenge"],
            })
            return await _redirect(send, f"{GOOGLE_OAUTH_BASE}/o/oauth2/v2/auth?" + urlencode({
                "response_type": "code",
                "client_id": GOOGLE_CLIENT_ID,
                "redirect_uri": f"{BASE_URL}/google/callback",
                "scope": GOOGLE_SCOPES,
                "state": nonce,
                "access_type": "offline",
                "prompt": "consent",
            }))

        if path == "/google/callback":
            pending = store.pop_pending(query.get("state", ""))
            if not pending or not query.get("code"):
                return await _respond(send, 400, {"error": "authorization response did not match a pending request"})

            import requests
            resp = requests.post(GOOGLE_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": query["code"],
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{BASE_URL}/google/callback",
            }, timeout=10)
            if resp.status_code != 200:
                return await _respond(send, 502, {"error": "Google refused the code exchange"})
            body = resp.json()

            # The id_token arrived over TLS directly from Google's token
            # endpoint in a server-to-server exchange, which is the one context
            # where decoding without a JWKS round trip is sound.
            segment = body["id_token"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(
                segment + "=" * (-len(segment) % 4)))
            subject, email = str(claims.get("sub")), str(claims.get("email", ""))
            store.save_google_tokens(subject, email, body.get("refresh_token"),
                                     body["access_token"], body.get("expires_in", 3600))

            code = "gwa-" + secrets.token_urlsafe(32)
            store.put_code(code, {
                "subject": subject,
                "client_id": pending["client_id"],
                "redirect_uri": pending["redirect_uri"],
                "code_challenge": pending["code_challenge"],
            })
            sep = "&" if "?" in pending["redirect_uri"] else "?"
            return await _redirect(
                send,
                f"{pending['redirect_uri']}{sep}"
                + urlencode({"code": code, "state": pending["state"]}),
            )

        if path == "/token" and scope["method"] == "POST":
            from urllib.parse import parse_qs as pq
            form = {k: v[0] for k, v in pq((await _read_body(receive)).decode()).items()}

            if form.get("resource") != RESOURCE_URI:
                return await _respond(send, 400, {
                    "error": "invalid_target",
                    "error_description": f"resource must be {RESOURCE_URI}"})

            if form.get("grant_type") == "authorization_code":
                payload = store.pop_code(form.get("code", ""))
                if not payload:
                    return await _respond(send, 400, {"error": "invalid_grant"})
                if form.get("client_id") != payload["client_id"]:
                    return await _respond(send, 400, {"error": "invalid_client"})
                if form.get("redirect_uri") != payload["redirect_uri"]:
                    return await _respond(send, 400, {"error": "invalid_grant",
                                                      "error_description": "redirect_uri mismatch"})
                digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                if expected != payload["code_challenge"]:
                    return await _respond(send, 400, {"error": "invalid_grant",
                                                      "error_description": "PKCE verification failed"})
                return await _respond(send, 200, {
                    "access_token": _mint_access_token(payload["subject"]),
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TOKEN_TTL,
                    "refresh_token": store.issue_refresh_token(
                        payload["subject"], payload["client_id"]),
                    "scope": "workspace.read",
                })

            if form.get("grant_type") == "refresh_token":
                subject = store.subject_for_refresh(form.get("refresh_token", ""))
                if not subject:
                    return await _respond(send, 400, {"error": "invalid_grant"})
                return await _respond(send, 200, {
                    "access_token": _mint_access_token(subject),
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TOKEN_TTL,
                    "scope": "workspace.read",
                })

            return await _respond(send, 400, {"error": "unsupported_grant_type"})

        # ---- RS half: everything else needs a valid audience-bound token ----
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return await _respond(send, 401, {"error": "unauthorized"}, [(
                b"www-authenticate",
                f'Bearer resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource"'.encode())])
        try:
            claims = jwt.decode(auth[7:].strip(), {"keys": [public_jwk]}, claims_options={
                "iss": {"essential": True, "values": [BASE_URL]},
                "aud": {"essential": True, "values": [RESOURCE_URI]},
                "exp": {"essential": True},
            })
            claims.validate()
        except Exception:
            return await _respond(send, 401, {"error": "invalid_token"}, [(
                b"www-authenticate",
                f'Bearer resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource", error="invalid_token"'.encode())])

        current_subject.set(str(claims.get("sub") or ""))
        await inner(scope, receive, send)

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    print(f"workspace gateway on :{PORT}\n  issuer/AS: {BASE_URL}\n  resource:  {RESOURCE_URI}")
    # Single worker on purpose: see the module docstring.
    uvicorn.run(build_app(), host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
