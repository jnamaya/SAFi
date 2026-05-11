"""
Web Search MCP Server (RSS Fallback)
Exposes internet search capabilities using public health RSS feeds.
"""
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_search_mcp")

# Reliable Health News RSS Feeds
FEEDS = {
    "WHO": "https://www.who.int/rss-feeds/news-english.xml",
    "CDC": "https://tools.cdc.gov/api/v2/resources/media/316408.rss", 
    "NIH": "https://www.nih.gov/news-events/news-releases/rss.xml",
    "FDA": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"
}

def clean_html(raw_html: str) -> str:
    """Removes HTML tags from a string."""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', str(raw_html)).strip()

def fetch_rss(url: str, source_name: str, max_items: int = 5) -> list:
    """Fetches and parses an RSS feed returning a list of dicts."""
    results = []
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            # Find all item tags
            items = root.findall('.//item')
            for item in items[:max_items]:
                title_elem = item.find('title')
                desc_elem = item.find('description')
                link_elem = item.find('link')
                date_elem = item.find('pubDate')
                
                title = title_elem.text if title_elem is not None else "No Title"
                desc = desc_elem.text if desc_elem is not None else ""
                link = link_elem.text if link_elem is not None else ""
                date = date_elem.text if date_elem is not None else "Unknown Date"
                
                results.append({
                    "title": clean_html(title),
                    "snippet": clean_html(desc),
                    "url": link,
                    "date": date,
                    "source": source_name
                })
    except Exception as e:
        logger.error(f"Failed to fetch feed {source_name}: {e}")
        
    return results

async def search_web(query: str, max_results: int = 5) -> str:
    """
    Searches the web for the given query.
    For this RSS-based implementation, we pull from all feeds and filter by query.
    """
    logger.info(f"Web Search MCP: Searching feeds for '{query}'")
    return await get_news(query, max_results)

async def get_news(query: str, max_results: int = 10) -> str:
    """
    Searches specifically for news articles across health RSS feeds.
    """
    logger.info(f"Web Search MCP: Searching news feeds for '{query}'")
    
    all_results = []
    
    for source_name, url in FEEDS.items():
        feed_results = fetch_rss(url, source_name, max_items=10)
        all_results.extend(feed_results)
        
    # If query is very generic, return recent items from all
    query_lower = query.lower()
    filtered_results = []
    
    if query_lower in ["news", "latest", "recent", "health news"]:
        filtered_results = all_results
    else:
        # Simple keyword matching
        keywords = query_lower.split()
        for item in all_results:
            text_to_search = (item['title'] + " " + item['snippet']).lower()
            # If any keyword matches, include it
            if any(kw in text_to_search for kw in keywords if len(kw) > 3 or kw == query_lower):
                filtered_results.append(item)
                
    # If no matches found, just return the latest across all to give the LLM context
    if not filtered_results and all_results:
        logger.info(f"No exact match for '{query}'. Returning generic latest news.")
        filtered_results = all_results
        
    # Limit results
    final_results = filtered_results[:max_results]
    
    if not final_results:
        return json.dumps({"message": "No news found currently available from health sources."})

    return json.dumps(final_results)
