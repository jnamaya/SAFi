import logging
import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, Tuple

# Section labels as they appear on the readings source, mapped to the canonical
# titles the rest of the pipeline expects (must match `allowed_titles` below and
# the keys handled in handle_bible_scholar_commands).
_READING_LABELS = {
    "first reading": "First Reading",
    "reading 1": "First Reading",      # USCCB
    "reading i": "First Reading",       # USCCB (Roman numerals on some days)
    "second reading": "Second Reading",
    "reading 2": "Second Reading",      # USCCB
    "reading ii": "Second Reading",     # USCCB
    "gospel": "Gospel",
    "gospel reading": "Gospel",
    "psalm": "Responsorial Psalm",
    "responsorial psalm": "Responsorial Psalm",
    "responsorial": "Responsorial Psalm",
}

# --- USCCB (primary, authoritative) ---
# USCCB's edge WAF 403s datacenter IPs on every path regardless of headers, so
# the page is unreachable directly from the server. We fetch it through a
# server-side reader proxy that retrieves the page from its own infrastructure
# and returns clean markdown.
_USCCB_URL = "https://bible.usccb.org/daily-bible-reading"
_READER_PROXY = "https://r.jina.ai/"
_USCCB_DATE_RE = re.compile(r"Daily Bible Reading\s*-\s*(.+?)\s*\|", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(")  # first markdown link after a heading = citation

# Matches the trailing " of <Weekday> <date>" the source appends to the first
# reading's citation, e.g. "2 Timothy 1.1-3, 6-12 of Wednesday June 3, 2026".
# Anchored on the weekday so book names containing " of " (e.g. "Song of Songs")
# are left intact.
_DATE_SUFFIX_RE = re.compile(
    r"\s+of\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.*)$",
    re.IGNORECASE,
)

# The source writes chapter/verse with a period ("Mark 12.18-27"); the Bible RAG
# keyword search expects the colon form ("Mark 12:18-27").
_CHAPTER_VERSE_RE = re.compile(r"(\d)\.(\d)")


def _normalize_citation(citation: str) -> str:
    return _CHAPTER_VERSE_RE.sub(r"\1:\2", citation).strip()

async def _fetch_usccb_via_proxy(log: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Primary source: USCCB daily readings, fetched through a reader proxy that
    returns the page as markdown. Each reading heading (e.g. '### Gospel') is
    immediately followed by a markdown link whose text is the citation, e.g.
    '[Mark 12:18-27](...)'. USCCB already uses the colon form.

    Returns the standard readings dict, or None if the fetch/parse yields
    nothing usable (so the caller can fall back).
    """
    url = _READER_PROXY + _USCCB_URL
    headers = {
        "Accept": "text/plain, text/markdown, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()

    md = resp.text
    date_match = _USCCB_DATE_RE.search(md)
    reading_date = date_match.group(1).strip() if date_match else None

    full_passages = []
    current_title = None
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # A heading resets context; only reading headings set a title.
            current_title = _READING_LABELS.get(stripped.lstrip("#").strip().lower())
            continue
        if current_title:
            link = _MD_LINK_RE.search(line)
            if link:
                full_passages.append({
                    "title": current_title,
                    "citation": _normalize_citation(link.group(1)),
                    "text": "",  # RAG supplies the actual verse text
                })
                current_title = None

    if not full_passages:
        log.warning("USCCB proxy fetch returned no recognizable readings (proxy or page format may have changed).")
        return None

    reading_date = reading_date or "today"
    log.info(f"Successfully fetched {len(full_passages)} passages from USCCB for {reading_date}.")
    return {"date": reading_date, "full_passages": full_passages, "url": _USCCB_URL}


async def _fetch_readings_from_source(log: logging.Logger) -> Dict[str, Any]:
    """
    Fetch today's readings. Tries USCCB (authoritative) via the reader proxy
    first, then falls back to the livingwithchrist.ca scrape if USCCB is
    unreachable or unparseable. Returns a dict with 'date'/'full_passages' or
    an 'error'.
    """
    try:
        usccb = await _fetch_usccb_via_proxy(log)
    except Exception as e:
        log.warning(f"USCCB proxy fetch failed ({type(e).__name__}: {e}); falling back to LivingWithChrist.")
        usccb = None

    if usccb and usccb.get("full_passages"):
        return usccb

    log.warning("Falling back to LivingWithChrist readings source.")
    return await _fetch_livingwithchrist(log)


async def _fetch_livingwithchrist(log: logging.Logger) -> Dict[str, Any]:
    """
    Fallback source: scrape livingwithchrist.ca.
    Returns a dictionary with 'date' and 'full_passages' or an 'error'.
    """
    try:
        # beholdvancouver.org now 302-redirects here; we target it directly.
        url = "https://readings.livingwithchrist.ca/"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Layout: a section label heading (e.g. "First reading", "Gospel")
        # precedes its citation. The first reading's citation lives in the
        # <h1 class="title-b"> as "<citation> of <weekday date>"; the remaining
        # readings use an <h3 class="title-c"> citation following their label.
        full_passages = []
        reading_date = None
        current_title = None

        for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            classes = el.get("class", []) or []
            text = el.get_text(" ", strip=True)
            label = _READING_LABELS.get(text.lower().strip())

            if label:
                current_title = label
                continue

            if "title-b" in classes:  # first reading: "<citation> of <date>"
                m = _DATE_SUFFIX_RE.search(text)
                if m and not reading_date:
                    reading_date = m.group(1).strip()
                citation = _normalize_citation(_DATE_SUFFIX_RE.sub("", text))
                if citation:
                    full_passages.append({
                        "title": current_title or "First Reading",
                        "citation": citation,
                        "text": "",  # RAG supplies the actual verse text
                    })
                current_title = None

            elif "title-c" in classes and current_title:
                full_passages.append({
                    "title": current_title,
                    "citation": _normalize_citation(text),
                    "text": "",
                })
                current_title = None

        if not full_passages:
            log.warning("LivingWithChrist scrape returned no recognizable readings (page structure may have changed).")
            return {"error": "I tried to fetch the daily readings, but the page formatting seemed to be empty."}

        reading_date = reading_date or "today"
        log.info(f"Successfully fetched {len(full_passages)} passages from LivingWithChrist for {reading_date}.")
        return {
            "date": reading_date,
            "full_passages": full_passages,
            "url": url
        }

    except httpx.TimeoutException as e:
        log.error(f"Timeout while fetching daily readings: {e}")
        return {"error": "I tried to fetch the readings, but the request timed out. Please try again."}
    except httpx.HTTPError as e:
        log.error(f"HTTP error while fetching daily readings: {e}")
        return {"error": f"I encountered a network error while fetching the readings: {str(e)}"}
    except Exception as e:
        log.exception("Unexpected error fetching daily readings")
        return {"error": f"I tried to fetch the readings, but an unexpected error occurred: {str(e)}"}


async def handle_bible_scholar_commands(
    user_prompt: str, 
    active_profile_name: str, 
    log: logging.Logger
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Checks for 'bible scholar' profile-specific commands.
    If a command is detected, it returns a generic data payload
    for faculties.py to consume.
    
    Returns the ORIGINAL user_prompt and a dictionary of fetched data (or None).
    """
    
    # This plugin only runs for 'the bible scholar'
    # FIX: Orchestrator sanitizes names to use underscores, so we must check for that too.
    if active_profile_name not in ["the bible scholar", "the_bible_scholar"]:
        return user_prompt, None

    original_user_prompt = user_prompt
    prompt_command = user_prompt.strip().lower()

    individual_reading_commands = [
        "first reading",
        "second reading",
        "gospel reading",
        "today's gospel",
        "today's reading",
        "daily reading",
        "mass reading",
        "reading for today",
        "gospel for today",
    ]
    
    data_payload = None

    if any(cmd in prompt_command for cmd in individual_reading_commands):
        log.info(f"Individual reading request detected: '{user_prompt}'")
        
        scraped_data = await _fetch_readings_from_source(log)
        
        if "error" in scraped_data:
            data_payload = {"plugin_error": scraped_data["error"]}
        else:
            # Find the specific reading the user asked for
            requested_reading_key = None
            if "first reading" in prompt_command:
                requested_reading_key = "First Reading"
            elif "second reading" in prompt_command:
                requested_reading_key = "Second Reading"
            elif "gospel" in prompt_command:
                requested_reading_key = "Gospel"

            found_passage = None
            if requested_reading_key:
                for passage in scraped_data.get("full_passages", []):
                    if passage.get("title") == requested_reading_key:
                        found_passage = passage
                        break
            
            if found_passage:
                # *** THIS IS THE KEY CHANGE ***
                # We build a GENERIC payload. We do NOT pass the
                # external 'text' field, forcing the RAG to do the work.
                data_payload = {
                    # Generic key to override the RAG search query
                    "rag_query_override": found_passage.get("citation"),
                    
                    # Generic key for a string to inject into the prompt
                    "preformatted_context_string": f"CONTEXT: The user is asking for the '{found_passage.get('title')}' for {scraped_data.get('date', 'today')}, which is {found_passage.get('citation')}. The RAG system has been provided with this text."
                }
            else:
                error_msg = f"I found the readings for today, but couldn't find a specific '{requested_reading_key}'."
                data_payload = {"plugin_error": error_msg}

    # If no command matched, data_payload is still None
    # Return the original prompt and the data payload (or None)
    return original_user_prompt, data_payload