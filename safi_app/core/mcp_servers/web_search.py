"""
Web Search MCP Server — DuckDuckGo backend.
Uses the `duckduckgo-search` package (pip install duckduckgo-search).
Runs the synchronous DDGS client in a thread to stay async-compatible.
"""
import json
import logging
import asyncio
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger("web_search_mcp")

def _ddg_text(query: str, max_results: int) -> list:
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))

def _ddg_news(query: str, max_results: int) -> list:
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.news(query, max_results=max_results))

_MAX_RESULT_SNIPPET_CHARS = 160
_MAX_RESULTS_PER_CALL = 60


def _bounded_snippet(text: str, limit: int = _MAX_RESULT_SNIPPET_CHARS) -> str:
    """Truncate a result snippet at a whole-word boundary so large result
    batches stay compact. Long snippets are what explode web_search payloads;
    the title carries the profile name and role, and most snippets only add
    context for the first ~150 characters."""
    if not isinstance(text, str) or len(text) <= limit:
        return text or ""
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"

def _format_text_results(raw: list) -> list:
    formatted = [
        {
            "title": r.get("title", ""),
            "snippet": _bounded_snippet(r.get("body", "")),
            "url": r.get("href", ""),
            "source": r.get("source", "")
        }
        for r in raw
    ]
    return _deduplicate_results(formatted)


_TRACKING_PARAMETERS = {"fbclid", "gclid", "msclkid", "ref", "ref_", "source"}


def _canonical_result_url(url: str) -> str:
    """Return a stable identity key without changing the emitted URL."""
    if not isinstance(url, str) or not url.strip():
        return ""

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if not parts.hostname:
        return ""

    host = parts.hostname.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"

    # LinkedIn profile pages are the same result regardless of query parameters
    # or fragments (including tracking parameters added by search providers).
    if host == "linkedin.com" and path.lower().startswith("/in/"):
        query = ""
    else:
        query = urlencode([
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_PARAMETERS and not key.lower().startswith("utm_")
        ])

    return urlunsplit(("https", host, path.lower(), query, ""))


def _deduplicate_results(results: list) -> list:
    """Keep the first result for each canonical URL."""
    seen = set()
    unique = []
    for result in results:
        key = _canonical_result_url(result.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique

def _format_news_results(raw: list) -> list:
    return [
        {
            "title": r.get("title", ""),
            "snippet": _bounded_snippet(r.get("body", "")),
            "url": r.get("url", ""),
            "date": r.get("date", ""),
            "source": r.get("source", "")
        }
        for r in raw
    ]

async def search_web(query: str | list[str], max_results: int = 15) -> str:
    queries = query if isinstance(query, list) else [query]
    queries = [item.strip() for item in queries if isinstance(item, str) and item.strip()]
    logger.info("web_search: %d quer%s", len(queries), "y" if len(queries) == 1 else "ies")
    try:
        raw_results = []
        for item in queries:
            try:
                raw_results.extend(await asyncio.to_thread(_ddg_text, item, max_results))
            except Exception as exc:
                # A single provider/query failure must not discard successful
                # results from the rest of a batch.
                logger.warning("web_search query failed: %s: %s", item, exc)
        results = _deduplicate_results(_format_text_results(raw_results))
        # Bound the payload returned to the caller: after the per-query cap (
        # max_results) and cross-query dedup, cap the total so a huge batch of
        # queries cannot swamp the model context or the audit-evidence budget.
        if len(results) > _MAX_RESULTS_PER_CALL:
            results = results[:_MAX_RESULTS_PER_CALL]
        if not results:
            return json.dumps({"message": "No results found"})
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"web_search failed: {e}")
        return json.dumps({"error": str(e)})

async def get_news(query: str, max_results: int = 8) -> str:
    logger.info(f"web_news: '{query}'")
    try:
        raw = await asyncio.to_thread(_ddg_news, query, max_results)
        results = _format_news_results(raw)
        if not results:
            return json.dumps({"message": f"No news found for: {query}"})
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"web_news failed: {e}")
        return json.dumps({"error": str(e)})
