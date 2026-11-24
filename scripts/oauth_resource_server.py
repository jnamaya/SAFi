#!/usr/bin/env python3
from __future__ import annotations

import contextvars
import json
import os
import time
from typing import Any, Dict, Optional

current_subject: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_subject", default=""
)
current_scopes: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_scopes", default=""
)


class _Jwks:

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
    from authlib.jose import JsonWebToken
    from mcp.server import MCPServer

    server = MCPServer(name="safi-reference-tools")

    @server.tool()
    def whoami() -> str:
        scopes = current_scopes.get() or "none"
        return f"Authorized as {current_subject.get()} (scopes: {scopes})"

    @server.tool()
    def echo(message: str) -> str:
        return f"{current_subject.get()} said: {message}"

    from urllib.parse import urlparse as _urlparse
    from mcp.server.transport_security import TransportSecuritySettings

    _public_host = _urlparse(resource_uri).netloc
    inner = server.streamable_http_app(
        transport_security=TransportSecuritySettings(
            allowed_hosts=[_public_host, "127.0.0.1", "localhost"],
        )
    )
    jwks = _Jwks(jwks_uri)
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
