"""Provider-agnostic core of SAFi's per-user tool gateways (backlog 48k).

Extracted from the Workspace gateway the day a second gateway (Microsoft
Graph) was needed. Everything here is the part that has nothing to do with
which upstream the tools call: the sqlite store, the co-located Authorization
Server (PKCE S256 only, RFC 8707 resource enforcement, single-use five-minute
codes, dynamic client registration, hashed refresh tokens), the RS256 token
mint and validation, and the ASGI shell that puts the MCP tool server behind
strict audience-bound Bearer checks.

A concrete gateway (workspace_gateway.py, graph_gateway.py) supplies four
things through an UpstreamProvider:

  * where to send the member for login and consent, and with which scopes,
  * how to exchange and refresh codes/tokens at the upstream,
  * how to read the member's identity out of the upstream's token response,
  * the tools, registered on an MCPServer, reading current_subject to know
    who each call runs as.

The no-passthrough property is preserved by construction: upstream tokens are
Fernet-encrypted in the gateway's own database keyed by verified subject, and
the token minted for SAFi carries aud = this gateway's /mcp and opens nothing
else. The end-to-end and adversarial tests live with the Workspace gateway
(tests/test_workspace_gateway.py) and exercise this core; the Graph suite
covers its provider specifics.
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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlencode

log = logging.getLogger("safi-gateway")

ACCESS_TOKEN_TTL = int(os.environ.get("GATEWAY_ACCESS_TTL", "3600"))
AUTH_CODE_TTL = 300  # single-use and five minutes, per OAuth 2.1 guidance

# The identity of the current call, set by the middleware after verification
# and read by tools. A contextvar because concurrent requests each carry their
# own caller.
current_subject: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_subject", default="")


def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get("GATEWAY_ENCRYPTION_KEY", "")
    if not key:
        raise SystemExit(
            "GATEWAY_ENCRYPTION_KEY is required: it encrypts members' upstream "
            "tokens at rest. Generate one with\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


class Store:
    """Everything a gateway must remember, in one sqlite file.

    Upstream refresh tokens are Fernet-encrypted: they are the crown jewels,
    long-lived and usable against the upstream directly. The gateway's own
    refresh tokens are stored as sha256 hashes, never plaintext. Auth codes
    are single-use rows with a short expiry, deleted on redemption.
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
        # The table kept its original name when the core was extracted: a
        # rename would orphan every live Workspace gateway's stored tokens for
        # a cosmetic win. It holds whichever upstream this gateway federates.

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

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
        # Single use: deleted before the payload is judged, so a replayed code
        # finds nothing even if the first redemption failed late.
        row = self._exec("SELECT payload, created_at FROM auth_codes WHERE code=?",
                         (code,)).fetchone()
        self._exec("DELETE FROM auth_codes WHERE code=?", (code,))
        if not row or time.time() - row[1] > AUTH_CODE_TTL:
            return None
        return json.loads(row[0])

    def save_upstream_tokens(self, subject: str, email: str,
                             refresh_token: Optional[str], access_token: str,
                             expires_in: int):
        enc = self._fernet.encrypt
        existing = self._exec("SELECT refresh_token_enc FROM google_tokens WHERE subject=?",
                              (subject,)).fetchone()
        # Many upstreams return a refresh token only on the first consent;
        # keep the stored one when a re-login omits it.
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

    def upstream_tokens(self, subject: str) -> Optional[Dict[str, Any]]:
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

    def revoke_subject(self, subject: str) -> bool:
        """Offboarding: everything this subject could ever redeem, gone in one
        motion. Every gateway refresh token for the subject and the stored
        upstream tokens; outstanding access JWTs stay signature-valid until
        exp but find no upstream token to act with."""
        had = bool(self._exec("SELECT 1 FROM refresh_tokens WHERE subject=?",
                              (subject,)).fetchone()
                   or self._exec("SELECT 1 FROM google_tokens WHERE subject=?",
                                 (subject,)).fetchone())
        self._exec("DELETE FROM refresh_tokens WHERE subject=?", (subject,))
        self._exec("DELETE FROM google_tokens WHERE subject=?", (subject,))
        return had


@dataclass
class UpstreamProvider:
    """What differs between Google, Microsoft, and whatever comes third."""

    name: str
    authorize_url: str                    # where the member's browser goes
    token_url: str                        # where codes and refreshes exchange
    scopes: str                           # space-separated, what members grant
    # The path (on this gateway) the upstream redirects back to. Owned by the
    # provider because it is registered in the upstream's console: Workspace
    # deployments already registered /google/callback at Google, and a core
    # refactor must not force anyone back into a cloud console.
    callback_path: str = "/upstream/callback"
    # extras appended to the authorize redirect (access_type/prompt for
    # Google; nothing needed for Microsoft)
    authorize_extra: Dict[str, str] = field(default_factory=dict)
    # (token_response_json) -> (subject, email). Raises on garbage.
    extract_identity: Callable[[Dict[str, Any]], tuple] = None
    # Where the upstream revokes a refresh token, when it has such a thing.
    # Google does; Microsoft does not, and None means our /revoke destroys the
    # only stored copy instead, which is the strongest control available there.
    revoke_url: Optional[str] = None


def decode_jwt_segment(token: str, index: int = 1) -> Dict[str, Any]:
    """Decode one JWT segment without verification. Sound ONLY for tokens that
    arrived over TLS directly from the upstream's token endpoint in a
    server-to-server exchange, which is the single place this is used."""
    segment = token.split(".")[index]
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def upstream_access_token(store: Store, provider: UpstreamProvider,
                          client_id: str, client_secret: str,
                          subject: str) -> Optional[str]:
    """A live upstream token for this subject, refreshed when expired. The only
    place upstream credentials are touched, and its inputs come from a VERIFIED
    JWT subject, never from anything the caller sent."""
    import requests

    tokens = store.upstream_tokens(subject)
    if not tokens:
        return None
    if tokens["access_token"] and tokens["expires_at"] > time.time() + 30:
        return tokens["access_token"]
    if not tokens["refresh_token"]:
        return None
    resp = requests.post(provider.token_url, data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=10)
    if resp.status_code != 200:
        log.warning("%s refresh failed for %s: %s", provider.name, subject, resp.status_code)
        return None
    body = resp.json()
    store.save_upstream_tokens(subject, tokens["email"], body.get("refresh_token"),
                               body["access_token"], body.get("expires_in", 3600))
    return body["access_token"]


def build_gateway_app(*, base_url: str, store: Store, provider: UpstreamProvider,
                      client_id: str, client_secret: str, mcp_server,
                      scope_label: str = "tools.read"):
    """The ASGI app: discovery documents, the AS routes, and the MCP server
    behind strict audience-bound Bearer validation. `mcp_server` arrives with
    its tools already registered; they read current_subject."""
    from authlib.jose import JsonWebToken
    from urllib.parse import urlparse
    from mcp.server.transport_security import TransportSecuritySettings

    base_url = base_url.rstrip("/")
    resource_uri = f"{base_url}/mcp"
    key = store.signing_key()
    public_jwk = key.as_dict(is_private=False)
    kid = public_jwk.get("kid")
    jwt = JsonWebToken(["RS256"])

    inner = mcp_server.streamable_http_app(
        transport_security=TransportSecuritySettings(
            allowed_hosts=[urlparse(base_url).netloc, "127.0.0.1", "localhost"],
        )
    )

    async def _read_body(receive) -> bytes:
        body = b""
        while True:
            event = await receive()
            body += event.get("body", b"")
            if not event.get("more_body"):
                return body

    async def _respond(send, status, payload, headers=()):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")] + list(headers)})
        await send({"type": "http.response.body", "body": body})

    async def _redirect(send, url):
        await send({"type": "http.response.start", "status": 302,
                    "headers": [(b"location", url.encode())]})
        await send({"type": "http.response.body", "body": b""})

    def _query(scope) -> Dict[str, str]:
        from urllib.parse import parse_qs
        return {k: v[0] for k, v in parse_qs(scope.get("query_string", b"").decode()).items()}

    def _mint(subject: str) -> str:
        return jwt.encode(
            {"alg": "RS256", "kid": kid},
            {"iss": base_url, "aud": resource_uri, "sub": subject,
             "exp": int(time.time()) + ACCESS_TOKEN_TTL, "scope": scope_label},
            key,
        ).decode()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        path = scope.get("path", "")
        query = _query(scope)

        if path.startswith("/.well-known/oauth-protected-resource"):
            return await _respond(send, 200, {
                "resource": resource_uri,
                "authorization_servers": [base_url],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [scope_label],
            })
        if path.startswith("/.well-known/oauth-authorization-server"):
            return await _respond(send, 200, {
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}/authorize",
                "token_endpoint": f"{base_url}/token",
                "registration_endpoint": f"{base_url}/register",
                "revocation_endpoint": f"{base_url}/revoke",
                "jwks_uri": f"{base_url}/jwks",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
            })
        if path == "/jwks":
            return await _respond(send, 200, {"keys": [public_jwk]})

        if path == "/register" and scope["method"] == "POST":
            try:
                body = json.loads((await _read_body(receive)).decode() or "{}")
            except ValueError:
                return await _respond(send, 400, {"error": "invalid_client_metadata"})
            uris = [u for u in (body.get("redirect_uris") or []) if isinstance(u, str)]
            if not uris:
                return await _respond(send, 400, {"error": "invalid_redirect_uri"})
            return await _respond(send, 201, {
                "client_id": store.register_client(uris), "redirect_uris": uris,
                "token_endpoint_auth_method": "none",
            })

        if path == "/authorize":
            registered = store.client_redirects(query.get("client_id", ""))
            if registered is None:
                return await _respond(send, 400, {"error": "unknown client_id"})
            if query.get("redirect_uri") not in registered:
                return await _respond(send, 400, {"error": "redirect_uri not registered"})
            if query.get("response_type") != "code":
                return await _respond(send, 400, {"error": "only response_type=code is supported"})
            if query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
                return await _respond(send, 400, {"error": "PKCE with S256 is required"})
            if query.get("resource") != resource_uri:
                return await _respond(send, 400, {
                    "error": f"resource must be {resource_uri} (RFC 8707)"})
            if not client_id:
                return await _respond(send, 500, {
                    "error": f"gateway has no {provider.name} client configured"})

            nonce = secrets.token_urlsafe(32)
            store.put_pending(nonce, {
                "client_id": query["client_id"],
                "redirect_uri": query["redirect_uri"],
                "state": query.get("state", ""),
                "code_challenge": query["code_challenge"],
            })
            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": f"{base_url}{provider.callback_path}",
                "scope": provider.scopes,
                "state": nonce,
            }
            params.update(provider.authorize_extra)
            return await _redirect(send, f"{provider.authorize_url}?{urlencode(params)}")

        if path == provider.callback_path:
            pending = store.pop_pending(query.get("state", ""))
            if not pending or not query.get("code"):
                return await _respond(send, 400, {
                    "error": "authorization response did not match a pending request"})

            import requests
            resp = requests.post(provider.token_url, data={
                "grant_type": "authorization_code",
                "code": query["code"],
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": f"{base_url}{provider.callback_path}",
            }, timeout=10)
            if resp.status_code != 200:
                return await _respond(send, 502, {
                    "error": f"{provider.name} refused the code exchange"})
            body = resp.json()
            subject, email = provider.extract_identity(body)
            store.save_upstream_tokens(subject, email, body.get("refresh_token"),
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
                send, f"{pending['redirect_uri']}{sep}"
                + urlencode({"code": code, "state": pending["state"]}))

        if path == "/token" and scope["method"] == "POST":
            from urllib.parse import parse_qs as pq
            form = {k: v[0] for k, v in pq((await _read_body(receive)).decode()).items()}

            if form.get("resource") != resource_uri:
                return await _respond(send, 400, {
                    "error": "invalid_target",
                    "error_description": f"resource must be {resource_uri}"})

            if form.get("grant_type") == "authorization_code":
                payload = store.pop_code(form.get("code", ""))
                if not payload:
                    return await _respond(send, 400, {"error": "invalid_grant"})
                if form.get("client_id") != payload["client_id"]:
                    return await _respond(send, 400, {"error": "invalid_client"})
                if form.get("redirect_uri") != payload["redirect_uri"]:
                    return await _respond(send, 400, {
                        "error": "invalid_grant", "error_description": "redirect_uri mismatch"})
                digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                if expected != payload["code_challenge"]:
                    return await _respond(send, 400, {
                        "error": "invalid_grant", "error_description": "PKCE verification failed"})
                return await _respond(send, 200, {
                    "access_token": _mint(payload["subject"]),
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TOKEN_TTL,
                    "refresh_token": store.issue_refresh_token(
                        payload["subject"], payload["client_id"]),
                    "scope": scope_label,
                })

            if form.get("grant_type") == "refresh_token":
                subject = store.subject_for_refresh(form.get("refresh_token", ""))
                if not subject:
                    return await _respond(send, 400, {"error": "invalid_grant"})
                return await _respond(send, 200, {
                    "access_token": _mint(subject),
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TOKEN_TTL,
                    "scope": scope_label,
                })

            return await _respond(send, 400, {"error": "unsupported_grant_type"})

        if path == "/revoke" and scope["method"] == "POST":
            # RFC 7009, with offboarding semantics. The clients are public, so
            # possession IS the authorization: only a holder of a live token
            # can call this, and the only thing it can do is destroy access.
            # A valid token resolves to its subject and the revocation
            # CASCADES: every gateway refresh token for that subject, the
            # stored upstream tokens, and the upstream's own revocation where
            # the provider offers one. Per the RFC, the answer is 200 whether
            # or not the token was known, so this endpoint confirms nothing
            # to a caller probing with guesses.
            from urllib.parse import parse_qs as pq
            form = {k: v[0] for k, v in pq((await _read_body(receive)).decode()).items()}
            presented = form.get("token", "")

            subject = store.subject_for_refresh(presented) if presented else None
            if not subject and presented.count(".") == 2:
                try:
                    claims = jwt.decode(presented, {"keys": [public_jwk]}, claims_options={
                        "iss": {"essential": True, "values": [base_url]},
                        "aud": {"essential": True, "values": [resource_uri]},
                    })
                    claims.validate()
                    subject = str(claims.get("sub") or "") or None
                except Exception:
                    subject = None

            if subject:
                upstream = store.upstream_tokens(subject)
                if provider.revoke_url and upstream and upstream.get("refresh_token"):
                    try:
                        import requests
                        requests.post(provider.revoke_url,
                                      data={"token": upstream["refresh_token"]},
                                      timeout=10)
                    except Exception:
                        # Best effort: the upstream being unreachable must not
                        # keep the local copy alive.
                        log.warning("%s upstream revocation failed for %s",
                                    provider.name, subject)
                store.revoke_subject(subject)
                log.info("revoked all tokens for subject %s", subject)
            return await _respond(send, 200, {})

        # Everything else needs a valid audience-bound token.
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        challenge_headers = [(
            b"www-authenticate",
            f'Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"'.encode())]
        if not auth.lower().startswith("bearer "):
            return await _respond(send, 401, {"error": "unauthorized"}, challenge_headers)
        try:
            claims = jwt.decode(auth[7:].strip(), {"keys": [public_jwk]}, claims_options={
                "iss": {"essential": True, "values": [base_url]},
                "aud": {"essential": True, "values": [resource_uri]},
                "exp": {"essential": True},
            })
            claims.validate()
        except Exception:
            return await _respond(send, 401, {"error": "invalid_token"}, challenge_headers)

        current_subject.set(str(claims.get("sub") or ""))
        await inner(scope, receive, send)

    return app
