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
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value or "")

_DISCOVERY_TTL = 600
_discovery_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


class OAuthConfigError(Exception):
    pass


def provider_key(server_key: str) -> str:
    return f"{PROVIDER_PREFIX}{server_key}"


def _assert_safe_url(url: str) -> None:
    import ipaddress
    import socket

    if not url or not isinstance(url, str):
        raise OAuthConfigError("Blocked unsafe OAuth endpoint URL: empty URL.")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("https", "http"):
        raise OAuthConfigError(f"Blocked unsafe OAuth endpoint URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise OAuthConfigError("Blocked unsafe OAuth endpoint URL: missing hostname.")
    if parsed.username or parsed.password:
        raise OAuthConfigError("Blocked unsafe OAuth endpoint URL: embedded credentials are not allowed.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise OAuthConfigError(f"OAuth endpoint host does not resolve: {e}") from e
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            raise OAuthConfigError(f"Blocked unparseable OAuth endpoint address: {info[4][0]}")
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise OAuthConfigError(f"Blocked unsafe OAuth endpoint IP: {ip}")


def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        _assert_safe_url(url)
        resp = requests.get(url, timeout=HTTP_TIMEOUT,
                            headers={"Accept": "application/json", "User-Agent": "SAFi"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError, OAuthConfigError):
        return None


def discover(server_url: str) -> Dict[str, Any]:
    cached = _discovery_cache.get(server_url)
    if cached and time.time() - cached[0] < _DISCOVERY_TTL:
        return cached[1]

    parsed = urlparse(server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

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
        "resource": str(prm.get("resource") or server_url),
        "issuer": str(meta.get("issuer") or issuer),
        "authorization_endpoint": str(meta["authorization_endpoint"]),
        "token_endpoint": str(meta["token_endpoint"]),
        "registration_endpoint": meta.get("registration_endpoint"),
        "revocation_endpoint": meta.get("revocation_endpoint"),
        "scopes_supported": prm.get("scopes_supported") or meta.get("scopes_supported") or [],
    }
    _discovery_cache[server_url] = (time.time(), result)
    return result


def clear_discovery_cache() -> None:
    _discovery_cache.clear()


def make_pkce() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def ensure_client(server_key: str, definition: Dict[str, Any],
                  discovery: Dict[str, Any], redirect_uri: str) -> Dict[str, str]:
    if definition.get("client_id"):
        client_id = _expand_env(str(definition["client_id"]))
        if not client_id:
            raise OAuthConfigError(
                f"This server's client_id is configured as "
                f"{definition['client_id']!r} but that variable is empty in the "
                "deployment's environment. Set it (and the client secret) in "
                ".env and restart."
            )
        return {
            "client_id": client_id,
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
        _assert_safe_url(registration_endpoint)
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


def build_authorization_url(discovery: Dict[str, Any], client_id: str,
                            redirect_uri: str, state: str,
                            code_challenge: str,
                            scopes: Optional[list] = None) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
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
    form["resource"] = discovery["resource"]
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    _assert_safe_url(discovery["token_endpoint"])
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


def store_tokens(user_id: str, server_key: str, body: Dict[str, Any],
                 org_id: Optional[str]) -> None:
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
    if definition.get("client_id"):
        return {"client_id": _expand_env(str(definition["client_id"])),
                "client_secret": _expand_env(str(definition.get("client_secret") or ""))}
    stored = mcp_store.get_oauth_client(server_key)
    if not stored:
        raise OAuthConfigError("No OAuth client is registered for this server.")
    return {"client_id": stored["client_id"],
            "client_secret": stored.get("client_secret") or ""}


def revoke_at_server(user_id: str, server_key: str,
                     definition: Dict[str, Any]) -> bool:
    import requests

    row = db.get_oauth_token(user_id, provider_key(server_key))
    if not row:
        return False
    token = row.get("refresh_token") or row.get("access_token")
    if not token:
        return False
    try:
        discovery = discover(str(definition.get("url") or ""))
        endpoint = discovery.get("revocation_endpoint")
        if not endpoint:
            return False
        _assert_safe_url(endpoint)
        resp = requests.post(endpoint, data={"token": token}, timeout=10)
        ok = resp.status_code == 200
        if not ok:
            log.warning("revocation at %s answered %s for %s",
                        server_key, resp.status_code, user_id)
        return ok
    except Exception as exc:
        log.warning("revocation at %s failed for %s: %s", server_key, user_id, exc)
        return False


def revoke_all_mcp_tokens(user_id: str) -> Dict[str, bool]:
    from .mcp_manager import file_servers

    results: Dict[str, bool] = {}
    try:
        providers = db.get_connected_providers(user_id)
        definitions = file_servers()
    except Exception as exc:
        log.warning("revocation sweep could not enumerate for %s: %s", user_id, exc)
        return results
    for provider in providers:
        if not str(provider).startswith(PROVIDER_PREFIX):
            continue
        key = str(provider)[len(PROVIDER_PREFIX):]
        try:
            results[key] = revoke_at_server(user_id, key, definitions.get(key) or {})
        except Exception as exc:
            log.warning("revocation at %s raised for %s: %s", key, user_id, exc)
            results[key] = False
    if results:
        log.info("offboarding revocation for %s: %s", user_id, results)
    return results
