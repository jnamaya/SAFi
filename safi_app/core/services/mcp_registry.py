from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://registry.modelcontextprotocol.io"
API_VERSION = "v0"
HTTP_TIMEOUT = 10.0
CACHE_TTL_SECONDS = 300

REMOTE_TRANSPORTS = {"streamable-http", "streamable_http", "http", "sse"}

_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


class RegistryError(Exception):
    pass


def _cached(key: str):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
            return hit[1]
    return None


def _store(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _base_url(config: Any = None) -> str:
    return (getattr(config, "MCP_REGISTRY_URL", "") or DEFAULT_BASE_URL).rstrip("/")


def _get(path: str, params: Dict[str, Any], config: Any = None) -> Dict[str, Any]:
    url = f"{_base_url(config)}/{API_VERSION}{path}"
    key = f"{url}|{sorted(params.items())}"
    hit = _cached(key)
    if hit is not None:
        return hit
    try:
        resp = requests.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "SAFi"},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RegistryError(f"registry unreachable: {e}") from e
    except ValueError as e:
        raise RegistryError(f"registry returned invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise RegistryError("registry returned an unexpected payload")
    _store(key, data)
    return data


def _normalize_remote(remote: Any) -> Optional[Dict[str, str]]:
    if not isinstance(remote, dict):
        return None
    transport = str(remote.get("type") or remote.get("transport") or "").strip().lower()
    url = str(remote.get("url") or "").strip()
    if not url or transport not in REMOTE_TRANSPORTS:
        return None
    return {
        "transport": "sse" if transport == "sse" else "http",
        "url": url,
        "declared_type": transport,
    }


def _normalize_package(package: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(package, dict):
        return None
    identifier = str(package.get("identifier") or "").strip()
    if not identifier:
        return None
    return {
        "registry_type": str(
            package.get("registryType") or package.get("registry_type") or ""
        ).strip().lower(),
        "identifier": identifier,
        "version": str(package.get("version") or "").strip(),
        "transport": str(
            (package.get("transport") or {}).get("type")
            if isinstance(package.get("transport"), dict)
            else (package.get("transport") or "")
        ).strip().lower(),
        "runtime_hint": str(
            package.get("runtimeHint") or package.get("runtime_hint") or ""
        ).strip(),
        "file_sha256": str(
            package.get("fileSha256") or package.get("file_sha256") or ""
        ).strip(),
    }


def _normalize_server(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None

    inner = entry.get("server") if isinstance(entry.get("server"), dict) else entry

    name = str(inner.get("name") or "").strip()
    if not name:
        return None

    official = {}
    for source in (entry, inner):
        meta = source.get("_meta")
        if isinstance(meta, dict):
            candidate = meta.get("io.modelcontextprotocol.registry/official")
            if isinstance(candidate, dict):
                official = candidate
                break

    remotes = [r for r in (_normalize_remote(r) for r in (inner.get("remotes") or [])) if r]
    packages = [p for p in (_normalize_package(p) for p in (inner.get("packages") or [])) if p]

    return {
        "name": name,
        "title": str(inner.get("title") or "").strip() or name,
        "description": str(inner.get("description") or "").strip(),
        "version": str(inner.get("version") or "").strip(),
        "website": str(inner.get("websiteUrl") or inner.get("website_url") or "").strip(),
        "remotes": remotes,
        "packages": packages,
        "status": str(official.get("status") or "").strip(),
        "published_at": str(official.get("publishedAt") or "").strip(),
        "updated_at": str(official.get("updatedAt") or "").strip(),
        "is_latest": bool(official.get("isLatest", True)),
        "has_remote": bool(remotes),
        "requires_local_execution": bool(packages) and not bool(remotes),
    }


def search(query: str = "", limit: int = 30, cursor: str = "", config: Any = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": max(1, min(int(limit or 30), 100)), "version": "latest"}
    if query:
        params["search"] = query
    if cursor:
        params["cursor"] = cursor

    data = _get("/servers", params, config)
    raw = data.get("servers")
    if not isinstance(raw, list):
        raw = []
    servers = [s for s in (_normalize_server(e) for e in raw) if s]

    metadata = data.get("metadata")
    next_cursor = ""
    if isinstance(metadata, dict):
        next_cursor = str(metadata.get("nextCursor") or metadata.get("next_cursor") or "")

    return {"servers": servers, "next_cursor": next_cursor}


def get_server(name: str, config: Any = None) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    result = search(query=name, limit=100, config=config)
    for server in result["servers"]:
        if server["name"] == name:
            return server
    return None


PRIVATE_URL_REASON = (
    "URL resolves to a private, loopback or link-local address. A server "
    "installed from a browser must not be able to reach this deployment's own "
    "network."
)


def looks_like_a_web_page(url: str) -> bool:
    try:
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "text/html,application/json", "User-Agent": "SAFi"},
            stream=True,
        )
        content_type = (resp.headers.get("Content-Type") or "").lower()
        resp.close()
        return "text/html" in content_type
    except requests.RequestException:
        return False


def validate_remote_url(url: str) -> Tuple[bool, str]:
    if not url or not isinstance(url, str):
        return False, "No URL provided."

    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        return False, "Only https endpoints may be installed. Plain http would send this deployment's data in the clear."
    if not parsed.hostname:
        return False, "URL has no host."
    if parsed.username or parsed.password:
        return False, "Credentials embedded in the URL are not accepted."

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"Host does not resolve: {e}"

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, f"Host resolved to an address that cannot be parsed: {address}"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, PRIVATE_URL_REASON

    return True, ""
