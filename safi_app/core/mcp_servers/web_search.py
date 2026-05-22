"""
Web Search MCP Server — DuckDuckGo backend.
Uses the `duckduckgo-search` package (pip install duckduckgo-search).
Runs the synchronous DDGS client in a thread to stay async-compatible.
"""
import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger("web_search_mcp")

def _ddg_text(query: str, max_results: int) -> list:
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))

def _ddg_news(query: str, max_results: int) -> list:
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.news(query, max_results=max_results))

def _format_text_results(raw: list) -> list:
    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "url": r.get("href", ""),
            "source": r.get("source", "")
        }
        for r in raw
    ]

def _format_news_results(raw: list) -> list:
    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "url": r.get("url", ""),
            "date": r.get("date", ""),
            "source": r.get("source", "")
        }
        for r in raw
    ]

async def search_web(query: str, max_results: int = 5) -> str:
    logger.info(f"web_search: '{query}'")
    try:
        raw = await asyncio.to_thread(_ddg_text, query, max_results)
        results = _format_text_results(raw)
        if not results:
            return json.dumps({"message": f"No results found for: {query}"})
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
