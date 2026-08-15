/**
 * Authentication middleware for an MCP resource server (backlog 48i).
 *
 * This is the server half of the no-passthrough rule. The token arriving here
 * was minted by the IdP FOR THIS SERVER: its `aud` claim is this server's
 * resource URI (requested by the client via RFC 8707), and the checks below are
 * what make that binding worth anything. A server that skips the audience check
 * will happily accept a token minted for some other service, which is the
 * confused-deputy attack the whole architecture exists to prevent.
 *
 * What this middleware does, in order:
 *   1. No/invalid Authorization header -> 401 with a WWW-Authenticate header
 *      pointing at this server's Protected Resource Metadata (RFC 9728), which
 *      is how a spec-compliant client discovers the IdP and starts the flow.
 *   2. Verify the JWT's signature against the IdP's JWKS (fetched and cached
 *      by jose), its issuer, its expiry, and — strictly — its audience.
 *   3. Attach the verified claims to the request so tool handlers know WHO the
 *      call runs for, and can do their own upstream exchange (RFC 8693) for
 *      that subject. The upstream (e.g. Google) credential never appears in
 *      the token and never passes through the client.
 */
import type { NextFunction, Request, Response } from "express";
import { createRemoteJWKSet, jwtVerify } from "jose";
// The SDK's own AuthInfo: its streamable HTTP transport reads req.auth in this
// shape and forwards it to tool handlers, so conforming to it is what lets
// handlers see the verified identity without a side channel.
import type { AuthInfo } from "@modelcontextprotocol/sdk/server/auth/types.js";

export interface AuthConfig {
  /** This server's own resource identifier — the value `aud` must equal. */
  resourceUri: string;
  /** The IdP's issuer URL, exactly as it appears in tokens. */
  issuer: string;
  /** The IdP's JWKS endpoint. */
  jwksUri: string;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      auth?: AuthInfo;
    }
  }
}

export function protectedResourceMetadata(config: AuthConfig) {
  // RFC 9728. Served without authentication, deliberately: this document is
  // how an unauthenticated client learns where to authenticate.
  return {
    resource: config.resourceUri,
    authorization_servers: [config.issuer],
    bearer_methods_supported: ["header"],
  };
}

export function requireAudienceBoundToken(config: AuthConfig) {
  const jwks = createRemoteJWKSet(new URL(config.jwksUri));
  const prmUrl = new URL(
    "/.well-known/oauth-protected-resource",
    config.resourceUri,
  ).toString();

  const challenge = (res: Response, error?: string) => {
    // The WWW-Authenticate header carries the PRM location: a client that has
    // never seen this server reads it, discovers the IdP, and comes back with
    // a proper token. Rejection IS the first step of the handshake.
    const params = [`resource_metadata="${prmUrl}"`];
    if (error) params.push(`error="${error}"`);
    res
      .status(401)
      .set("WWW-Authenticate", `Bearer ${params.join(", ")}`)
      .json({ error: error ?? "unauthorized" });
  };

  return async (req: Request, res: Response, next: NextFunction) => {
    const header = req.get("authorization") ?? "";
    if (!header.toLowerCase().startsWith("bearer ")) {
      return challenge(res);
    }
    const token = header.slice(7).trim();

    try {
      const { payload } = await jwtVerify(token, jwks, {
        issuer: config.issuer,
        // The strict audience check. `aud` must be this server's URI — a token
        // minted for Google, for another MCP server, or with no audience at
        // all is refused regardless of who signed it.
        audience: config.resourceUri,
      });
      req.auth = {
        token,
        clientId: String(payload.azp ?? payload.client_id ?? ""),
        scopes:
          typeof payload.scope === "string" ? payload.scope.split(" ") : [],
        expiresAt: typeof payload.exp === "number" ? payload.exp : undefined,
        // The verified subject and full claims ride along for tool handlers:
        // this is what a real server keys its upstream exchange (RFC 8693) on.
        extra: { subject: String(payload.sub ?? ""), claims: payload },
      };
      return next();
    } catch {
      // Signature, expiry, issuer or audience failed. Which one is not
      // reported to the caller: an attacker probing tokens learns nothing,
      // and a legitimate client's remedy is the same either way — go back
      // through the flow.
      return challenge(res, "invalid_token");
    }
  };
}
