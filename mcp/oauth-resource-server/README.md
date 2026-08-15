# Reference MCP resource server (OAuth 2.1)

The server half of SAFi's per-user tool authorization (GOVERNANCE_BACKLOG 48i).
SAFi is the OAuth client; this is the protected resource it calls. The IdP
(Keycloak, Auth0, or any RFC 8414-compliant server) sits between them and mints
tokens whose `aud` is THIS server.

The rule the two halves enforce together: SAFi never holds an upstream (e.g.
Google) credential. It holds a token that opens exactly this server for exactly
one user. This server validates it (signature via the IdP's JWKS, issuer,
expiry, and strictly the audience) and, if it needs to reach an upstream API,
exchanges the verified identity itself (RFC 8693). A token stolen from either
side is useless anywhere else.

Build and run:

    npm install && npm run build
    RESOURCE_URI=https://tools.example.com/mcp \
    ISSUER=https://idp.example.com/realms/main \
    JWKS_URI=https://idp.example.com/realms/main/protocol/openid-connect/certs \
    npm start

Install it in SAFi from the host:

    scripts/safi_mcp.py add --url https://tools.example.com/mcp --auth oauth

Members then press "Sign in" on the server's card in Settings -> Tools Catalog.
The IdP must have SAFi registered as a client (or offer dynamic registration)
with redirect URI {WEB_BASE_URL}/api/mcp/auth/<key>/callback, and must support
RFC 8707 resource indicators so the audience lands on this server.
