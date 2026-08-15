#!/usr/bin/env python3
"""Reference MCP resource server with OAuth 2.1 authorization (backlog 48i).

The server half of SAFi's per-user tool authorization. SAFi is the OAuth
client; this is the protected resource it calls; an IdP (Keycloak, Auth0, any
RFC 8414-compliant server) sits between them and mints tokens whose `aud` is
THIS server. Pure Python on purpose: it runs on the dependencies SAFi already
ships (authlib, the MCP SDK, uvicorn), and the test suite drives it end to end,
which a compiled-but-never-executed example in another language cannot claim.

What the middleware enforces, in order:

  1. `/.well-known/oauth-protected-resource` is served WITHOUT authentication
     (RFC 9728). This document is how an unauthenticated client learns where
     to authenticate, so protecting it would break the handshake.
  2. Everything else requires a Bearer token. A missing or bad one gets a 401
     whose WWW-Authenticate header points at that metadata: rejection is the
     first step of the flow, not a dead end.
  3. The JWT is verified against the IdP's JWKS: signature, issuer, expiry,
     and STRICTLY the audience. The audience check is the whole architecture.
     A token minted for Google, for another MCP server, or with no audience at
     all is refused no matter who signed it, which is what stops this server
     being used as a confused deputy.
  4. The verified subject is exposed to tool handlers (a contextvar), which is
     what a real server keys its upstream exchange (RFC 8693) on. The upstream
     credential never exists inside SAFi and never crosses this wire.

Run it:

    RESOURCE_URI=https://tools.example.com/mcp \\
    ISSUER=https://idp.example.com/realms/main \\
    JWKS_URI=https://idp.example.com/realms/main/protocol/openid-connect/certs \\
    python scripts/oauth_resource_server.py

Install it in SAFi from the host:

    scripts/safi_mcp.py add --url https://tools.example.com/mcp --auth oauth

The IdP must have SAFi registered as a client (or offer dynamic registration)
with redirect URI {WEB_BASE_URL}/api/mcp/auth/<key>/callback, and must support
RFC 8707 resource indicators so the minted audience lands on RESOURCE_URI.
"""
from __future__ import annotations

import contextvars
import json
import os
import time
from typing import Any, Dict, Optional

# The identity of the current call, set by the middleware after verification
# and read by tools. A contextvar rather than a global because concurrent
# requests each carry their own caller.
current_subject: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_subject", default=""
)
current_scopes: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_scopes", default=""
)


class _Jwks:
    """The IdP's signing keys, fetched lazily and re-fetched on a schedule.

    Keys rotate. A server that caches them forever starts refusing every valid
    token the day the IdP rolls over, and one that fetches per request turns
    its IdP into a dependency of every tool call.
    """

    def __init__(self, jwks_uri: str, ttl: float = 300.0):
        self.jwks_uri = jwks_uri
        self.ttl = ttl
        self._keys: Optional[Dict[str, Any]] = None
        self._fetched = 0.0

    def keys(self) -> Dict[str, Any]:
        if self._keys is None or time.time() - self._fetched > self.ttl:
            import requests

            resp = requests.get(self.jwks_uri, timeout=10)
            resp.raise_for_status()
            self._keys = resp.json()
            self._fetched = time.time()
        return self._keys


def build_app(resource_uri: str, issuer: str, jwks_uri: str):
    """The ASGI app: PRM endpoint + auth middleware + the MCP server."""
    from authlib.jose import JsonWebToken
    from mcp.server import MCPServer

    server = MCPServer(name="safi-reference-tools")

    @server.tool()
    def whoami() -> str:
        """Report the identity this call is authorized as."""
        scopes = current_scopes.get() or "none"
        return f"Authorized as {current_subject.get()} (scopes: {scopes})"

    @server.tool()
    def echo(message: str) -> str:
        """Echo a message back, attributed to the verified caller."""
        return f"{current_subject.get()} said: {message}"

    inner = server.streamable_http_app()
    jwks = _Jwks(jwks_uri)
    # RS256/ES256 only. Accepting whatever `alg` the token names is the classic
    # JWT downgrade mistake; the allowed list is the server's, never the token's.
    jwt = JsonWebToken(["RS256", "ES256"])
    prm_path = "/.well-known/oauth-protected-resource"
    prm_body = json.dumps({
        "resource": resource_uri,
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
    }).encode()

    async def _respond(send, status: int, body: bytes, headers=()):
        wire = [(b"content-type", b"application/json")] + list(headers)
        await send({"type": "http.response.start", "status": status, "headers": wire})
        await send({"type": "http.response.body", "body": body})

    async def _challenge(send, error: str = ""):
        # The 401 that starts the handshake: it names where the client can
        # find the resource metadata. Which check failed is deliberately not
        # said; a probe learns nothing and a legitimate client's remedy is the
        # same either way.
        params = f'resource_metadata="{resource_uri.rstrip("/")}{prm_path}"'
        if error:
            params += f', error="{error}"'
        await _respond(send, 401, b'{"error":"unauthorized"}',
                       [(b"www-authenticate", f"Bearer {params}".encode())])

    async def app(scope, receive, send):
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        if scope.get("path", "").startswith(prm_path):
            await _respond(send, 200, prm_body)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            await _challenge(send)
            return

        try:
            claims = jwt.decode(
                auth[7:].strip(),
                jwks.keys(),
                claims_options={
                    "iss": {"essential": True, "values": [issuer]},
                    # The strict audience check. `aud` must be this server's
                    # resource URI, which is what SAFi asked the IdP for via
                    # RFC 8707. This line is the no-passthrough rule enforced.
                    "aud": {"essential": True, "values": [resource_uri]},
                    "exp": {"essential": True},
                },
            )
            claims.validate()
        except Exception:
            await _challenge(send, "invalid_token")
            return

        current_subject.set(str(claims.get("sub") or ""))
        current_scopes.set(str(claims.get("scope") or ""))
        await inner(scope, receive, send)

    return app


def main() -> None:
    import uvicorn

    resource_uri = os.environ.get("RESOURCE_URI", "http://localhost:8402/mcp")
    issuer = os.environ.get("ISSUER", "http://localhost:8401")
    jwks_uri = os.environ.get("JWKS_URI", "http://localhost:8401/jwks")
    port = int(os.environ.get("PORT", "8402"))
    print(f"resource server on :{port}, aud={resource_uri}, issuer={issuer}")
    uvicorn.run(build_app(resource_uri, issuer, jwks_uri),
                host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
