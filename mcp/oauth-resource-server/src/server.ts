/**
 * Reference MCP resource server with OAuth 2.1 authorization (backlog 48i).
 *
 * Wire shape:
 *   GET  /.well-known/oauth-protected-resource   RFC 9728, unauthenticated
 *   POST /mcp                                    MCP streamable HTTP, Bearer only
 *
 * Configure with environment variables:
 *   RESOURCE_URI  This server's public URL, e.g. https://tools.example.com/mcp.
 *                 Must equal the `aud` the IdP mints — and therefore the
 *                 `resource` value SAFi sends (RFC 8707).
 *   ISSUER        The IdP's issuer URL (Keycloak realm, Auth0 tenant, ...).
 *   JWKS_URI      The IdP's JWKS endpoint.
 *   PORT          Listen port, default 8402.
 *
 * The example tool returns the verified subject, which is the point being
 * demonstrated: the tool KNOWS WHO it runs for, from a token that could not
 * have been minted for anywhere else. A real Google Workspace server would use
 * req.auth.subject here to look up or mint upstream credentials for that user
 * via RFC 8693 token exchange with its own IdP — the upstream token never
 * exists inside SAFi and never crosses this wire.
 */
import express from "express";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import {
  protectedResourceMetadata,
  requireAudienceBoundToken,
  type AuthConfig,
} from "./auth.js";

const config: AuthConfig = {
  resourceUri: process.env.RESOURCE_URI ?? "http://localhost:8402/mcp",
  issuer: process.env.ISSUER ?? "http://localhost:8401",
  jwksUri: process.env.JWKS_URI ?? "http://localhost:8401/jwks",
};

const app = express();
app.use(express.json());

app.get("/.well-known/oauth-protected-resource", (_req, res) => {
  res.json(protectedResourceMetadata(config));
});

const guard = requireAudienceBoundToken(config);

app.post("/mcp", guard, async (req, res) => {
  // Stateless per-request transport: each authorized request gets a fresh
  // server instance carrying the caller's verified identity. Session reuse is
  // an optimization the reference deliberately skips — identity handling is
  // the thing being demonstrated, and per-request is the shape that cannot
  // leak one user's session to another.
  const server = new McpServer({ name: "safi-reference-tools", version: "1.0.0" });
  const auth = req.auth!;
  const who = {
    subject: String((auth.extra as { subject?: string } | undefined)?.subject ?? ""),
    scopes: auth.scopes,
  };

  server.tool(
    "whoami",
    "Report the identity this call is authorized as.",
    {},
    async () => ({
      content: [
        {
          type: "text",
          text: `Authorized as ${who.subject} (scopes: ${who.scopes.join(" ") || "none"})`,
        },
      ],
    }),
  );

  server.tool(
    "echo",
    "Echo a message back, attributed to the verified caller.",
    { message: z.string() },
    async ({ message }) => ({
      content: [{ type: "text", text: `${who.subject} said: ${message}` }],
    }),
  );

  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),
  });
  res.on("close", () => {
    void transport.close();
    void server.close();
  });
  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);
});

const port = Number(process.env.PORT ?? 8402);
app.listen(port, () => {
  console.log(`resource server on :${port}, aud=${config.resourceUri}, issuer=${config.issuer}`);
});
