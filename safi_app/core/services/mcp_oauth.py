"""
OAuth 2.1 client for MCP tool servers (GOVERNANCE_BACKLOG 48i).

This is the other half of the credential story. An MCP server installed with a
token in its environment is a service principal: one identity for everybody,
attribution lost. A server that implements the MCP authorization specification
instead advertises an Authorization Server, and SAFi acts as an OAuth client:
each member signs in once, SAFi holds a token for THAT member, and every tool
call runs as the person who asked for it.

THE NO-PASSTHROUGH RULE, WHICH SHAPES EVERYTHING HERE
------------------------------------------------------
SAFi never requests or holds an upstream (e.g. Google) token. The token minted
for us carries `aud` = the MCP server's URI — asked for explicitly via
RFC 8707's `resource` parameter at BOTH the authorization and token endpoints —
and is useless anywhere else. The MCP server validates it against the IdP's
JWKS and does its own upstream exchange (RFC 8693) if it needs one. So a token
stolen from SAFi's database opens exactly one tool server, not a mailbox, and
the server can never be confused into replaying our token at Google because
Google would not accept it.

WHAT IS IMPLEMENTED
-------------------
* Discovery: RFC 9728 Protected Resource Metadata at the server's
  /.well-known/oauth-protected-resource (path-suffixed variant tried too),
  then RFC 8414 Authorization Server Metadata, falling back to OpenID Connect
  discovery — real IdPs ship one or the other.
* PKCE (S256), mandatory. There is no non-PKCE path and no implicit flow.
* Dynamic Client Registration (RFC 7591) when the AS advertises a
  registration_endpoint and the operator supplied no client_id. The
  registration is per deployment and persisted (mcp_store), not per user.
* Token exchange and refresh, both carrying `resource`.
* Storage: the existing encrypted oauth_tokens table, provider "mcp:<key>",
  so retention, encryption and the same-transaction evidence row all come for
  free and identically to the delegated-OAuth connectors.

Everything here is deterministic plumbing: requests, redirects and parameter
checks. No model is ever involved, and nothing here grants a tool — the Will's
gate is upstream of every call this module authenticates.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests

from ...persistence import database as db
from ...persistence import mcp_store

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 10.0
PROVIDER_PREFIX = "mcp:"

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: str) -> str:
    """${VAR} from the process environment, the same convention the server
    file uses for stdio env blocks. The definition is a file that gets copied;
    a client secret written into it literally will eventually leak."""
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value or "")

# Discovery results barely change and are re-read on every login redirect, so a
# short cache keeps the login route from hammering the IdP. Failures are never
# cached: a transient IdP outage should not stick for ten minutes.
_DISCOVERY_TTL = 600
_discovery_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


class OAuthConfigError(Exception):
    """The server or its IdP is not set up in a way this flow can use."""


def provider_key(server_key: str) -> str:
    return f"{PROVIDER_PREFIX}{server_key}"


# ── Discovery ─────────────────────────────────────────────────────────────────

def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT,
                            headers={"Accept": "application/json", "User-Agent": "SAFi"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError):
        return None


def discover(server_url: str) -> Dict[str, Any]:
    """Resolve a server URL to its IdP's endpoints, per the MCP auth spec.

    Returns {resource, issuer, authorization_endpoint, token_endpoint,
    registration_endpoint?, scopes_supported?}. Raises OAuthConfigError with a
    reason an operator can act on — "the server publishes no resource
    metadata" is a different problem from "its IdP publishes no metadata", and
    collapsing them costs someone an afternoon.
    """
    cached = _discovery_cache.get(server_url)
    if cached and time.time() - cached[0] < _DISCOVERY_TTL:
        return cached[1]

    parsed = urlparse(server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    # RFC 9728: the well-known may be at the origin root or path-suffixed
    # (/.well-known/oauth-protected-resource/mcp for a server at /mcp).
    prm = None
    for candidate in (
        f"{origin}/.well-known/oauth-protected-resource{path}",
        f"{origin}/.well-known/oauth-protected-resource",
    ):
        prm = _get_json(candidate)
        if prm:
            break
    if not prm:
        raise OAuthConfigError(
            "The server publishes no protected-resource metadata "
            "(/.well-known/oauth-protected-resource), so it does not implement "
            "the MCP authorization specification. If it expects a static token, "
            "install it with credentials in the operator's file instead."
        )

    servers = prm.get("authorization_servers")
    if not isinstance(servers, list) or not servers:
        raise OAuthConfigError(
            "The server's resource metadata names no authorization server."
        )
    issuer = str(servers[0]).rstrip("/")

    # RFC 8414 first, OIDC discovery as the fallback; issuers with a path
    # component get the path-aware RFC 8414 form tried as well.
    iss = urlparse(issuer)
    iss_origin = f"{iss.scheme}://{iss.netloc}"
    iss_path = iss.path.rstrip("/")
    meta = None
    for candidate in (
        f"{iss_origin}/.well-known/oauth-authorization-server{iss_path}",
        f"{issuer}/.well-known/oauth-authorization-server",
        f"{issuer}/.well-known/openid-configuration",
    ):
        meta = _get_json(candidate)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            break
        meta = None
    if not meta:
        raise OAuthConfigError(
            f"The authorization server {issuer} publishes no usable metadata "
            "(neither RFC 8414 nor OpenID Connect discovery)."
        )

    result = {
        # The resource identifier the token must be bound to. The PRM's own
        # `resource` claim is authoritative when present; the server URL is the
        # spec's default identity for it.
        "resource": str(prm.get("resource") or server_url),
        "issuer": str(meta.get("issuer") or issuer),
        "authorization_endpoint": str(meta["authorization_endpoint"]),
        "token_endpoint": str(meta["token_endpoint"]),
        "registration_endpoint": meta.get("registration_endpoint"),
        "scopes_supported": prm.get("scopes_supported") or meta.get("scopes_supported") or [],
    }
    _discovery_cache[server_url] = (time.time(), result)
    return result


def clear_discovery_cache() -> None:
    _discovery_cache.clear()


# ── PKCE ──────────────────────────────────────────────────────────────────────

def make_pkce() -> Tuple[str, str]:
    """(code_verifier, code_challenge), S256. There is no 'plain' fallback:
    an AS that cannot do S256 does not get a code from us."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── Client identity (configured or dynamically registered) ────────────────────

def ensure_client(server_key: str, definition: Dict[str, Any],
                  discovery: Dict[str, Any], redirect_uri: str) -> Dict[str, str]:
    """The OAuth client this deployment presents to the IdP.

    Order of precedence: credentials in the server definition (client_id, and
    client_secret usually via ${VAR} from the environment) win; otherwise a
    previously stored dynamic registration is reused; otherwise we register
    (RFC 7591) if the AS allows it. Registration is once per deployment and
    persisted — re-registering on every login would litter the IdP with
    clients and break token revocation as a management tool.
    """
    if definition.get("client_id"):
        return {
            "client_id": _expand_env(str(definition["client_id"])),
            "client_secret": _expand_env(str(definition.get("client_secret") or "")),
        }

    stored = mcp_store.get_oauth_client(server_key)
    if stored and stored.get("issuer") == discovery["issuer"]:
        return {"client_id": stored["client_id"],
                "client_secret": stored.get("client_secret") or ""}

    registration_endpoint = discovery.get("registration_endpoint")
    if not registration_endpoint:
        raise OAuthConfigError(
            f"The authorization server {discovery['issuer']} does not offer "
            "dynamic client registration; set client_id (and client_secret via "
            "${VAR}) in the server's definition."
        )
    try:
        resp = requests.post(
            registration_endpoint,
            json={
                "client_name": "SAFi",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise OAuthConfigError(f"Dynamic client registration failed: {e}") from e

    client = {
        "client_id": str(body.get("client_id") or ""),
        "client_secret": str(body.get("client_secret") or ""),
    }
    if not client["client_id"]:
        raise OAuthConfigError("The authorization server returned no client_id.")
    mcp_store.save_oauth_client(server_key, discovery["issuer"],
                                client["client_id"], client["client_secret"])
    return client


# ── The flow ──────────────────────────────────────────────────────────────────

def build_authorization_url(discovery: Dict[str, Any], client_id: str,
                            redirect_uri: str, state: str,
                            code_challenge: str,
                            scopes: Optional[list] = None) -> str:
    params = {
        # OAuth 2.1: authorization code only. There is no implicit branch to
        # take and none will be added.
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # RFC 8707: bind the requested token to the MCP server, by identity.
        # This is the line that makes the no-passthrough rule real — the IdP
        # mints for the tool server, never for anything upstream of it.
        "resource": discovery["resource"],
    }
    scope_list = scopes if scopes is not None else discovery.get("scopes_supported") or []
    if scope_list:
        params["scope"] = " ".join(scope_list)
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


def _token_request(discovery: Dict[str, Any], client: Dict[str, str],
                   form: Dict[str, str]) -> Dict[str, Any]:
    form = dict(form)
    form["client_id"] = client["client_id"]
    # `resource` again at the token endpoint: RFC 8707 wants it at both stops,
    # and some ASes decide the audience only here.
    form["resource"] = discovery["resource"]
    # The secret travels in the body, not as Basic auth. RFC 6749 permits both;
    # GitHub's token endpoint accepts only the body form, and every other AS we
    # have met (Keycloak, Auth0, our own gateway) accepts it too, so the body is
    # the one shape that works everywhere.
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    resp = requests.post(discovery["token_endpoint"], data=form,
                         timeout=HTTP_TIMEOUT,
                         headers={"Accept": "application/json"})
    body = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    if resp.status_code != 200 or "access_token" not in body:
        detail = body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"
        raise OAuthConfigError(f"Token endpoint refused the request: {detail}")
    return body


def exchange_code(discovery: Dict[str, Any], client: Dict[str, str],
                  code: str, redirect_uri: str, code_verifier: str) -> Dict[str, Any]:
    return _token_request(discovery, client, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    })


def refresh(discovery: Dict[str, Any], client: Dict[str, str],
            refresh_token: str) -> Dict[str, Any]:
    return _token_request(discovery, client, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })


# ── Token storage and retrieval ───────────────────────────────────────────────

def store_tokens(user_id: str, server_key: str, body: Dict[str, Any],
                 org_id: Optional[str]) -> None:
    # oauth_tokens.expires_at is a DATETIME. Stored naive-UTC, matching how the
    # connector tokens in the same table are written.
    expires_at = None
    if body.get("expires_in"):
        try:
            expires_at = (datetime.now(timezone.utc)
                          + timedelta(seconds=int(body["expires_in"]))).replace(tzinfo=None)
        except (TypeError, ValueError):
            expires_at = None
    db.upsert_oauth_token(
        user_id, provider_key(server_key),
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=expires_at,
        scope=body.get("scope"),
        org_id=org_id,
    )


def access_token_for(user_id: str, server_key: str,
                     definition: Dict[str, Any]) -> Optional[str]:
    """This user's live token for this server, refreshing when it has expired.

    None means the person has never connected (or their refresh failed and the
    stale row was cleared, which sends them back through a clean sign-in rather
    than a loop of failing refreshes).
    """
    row = db.get_oauth_token(user_id, provider_key(server_key))
    if not row or not row.get("access_token"):
        return None

    expires_at = row.get("expires_at")
    expired = False
    if isinstance(expires_at, datetime):
        reference = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        expired = reference <= datetime.now(timezone.utc) + timedelta(seconds=30)
    if not expired:
        return row["access_token"]

    if not row.get("refresh_token"):
        return None
    try:
        discovery = discover(definition["url"])
        client = ensure_client_readonly(server_key, definition, discovery)
        body = refresh(discovery, client, row["refresh_token"])
        store_tokens(user_id, server_key, body, org_id=None)
        return body["access_token"]
    except Exception as e:
        log.warning("token refresh failed for %s / %s: %s",
                    user_id, server_key, e)
        db.delete_oauth_token(user_id, provider_key(server_key))
        return None


def ensure_client_readonly(server_key: str, definition: Dict[str, Any],
                           discovery: Dict[str, Any]) -> Dict[str, str]:
    """The client identity without ever registering a new one — refresh runs on
    the tool-call path, and a background call must not create IdP clients."""
    if definition.get("client_id"):
        return {"client_id": _expand_env(str(definition["client_id"])),
                "client_secret": _expand_env(str(definition.get("client_secret") or ""))}
    stored = mcp_store.get_oauth_client(server_key)
    if not stored:
        raise OAuthConfigError("No OAuth client is registered for this server.")
    return {"client_id": stored["client_id"],
            "client_secret": stored.get("client_secret") or ""}
