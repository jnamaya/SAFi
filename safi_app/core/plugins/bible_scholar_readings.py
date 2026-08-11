import logging
import re
import ssl
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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
# USCCB's edge WAF 403s datacenter IPs on the HTML pages, but the RSS feed is
# served without that block, so we read the feed directly. Each <item> is one
# day's readings (newest first, ~10 days deep) with the full page HTML escaped
# inside <description>. USCCB publishes on US Eastern time.
_USCCB_RSS_URL = "https://bible.usccb.org/readings.rss"
_USCCB_TZ = ZoneInfo("America/New_York")

# USCCB's WAF fingerprints the TLS handshake and 403s Python's default cipher
# list (curl and browsers pass). Offering a browser-like cipher suite is enough
# to get through; certificate verification stays fully enabled.
_USCCB_SSL_CONTEXT = ssl.create_default_context()
_USCCB_SSL_CONTEXT.set_ciphers(
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "AES128-GCM-SHA256:AES256-GCM-SHA384"
)

# Matches the trailing " of <Weekday> <date>" the source appends to the first
# reading's citation, e.g. "2 Timothy 1.1-3, 6-12 of Wednesday June 3, 2026".
# Anchored on the weekday so book names containing " of " (e.g. "Song of Songs")
# are left intact.
_DATE_SUFFIX_RE = re.compile(
    r"(?:^|\s+)of\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.*)$",
    re.IGNORECASE,
)

# The source writes chapter/verse with a period ("Mark 12.18-27"); the Bible RAG
# keyword search expects the colon form ("Mark 12:18-27").
_CHAPTER_VERSE_RE = re.compile(r"(\d)\.(\d)")


def _normalize_citation(citation: str) -> str:
    return _CHAPTER_VERSE_RE.sub(r"\1:\2", citation).strip()


# --- Request parsing --------------------------------------------------------
#
# Two separate lists, because "does this prompt want readings at all" and "which
# reading does it want" are different questions and conflating them is what broke
# four of the phrases below.
#
# TRIGGERS are deliberately explicit. A bare "psalm" or "gospel" is ordinary
# conversation for this agent ("which psalm is about..."), and triggering on it
# would fetch the day's readings and override the RAG query with today's
# citation — answering a general question with today's liturgy.
_READING_TRIGGERS = [
    "first reading", "second reading", "gospel reading", "responsorial psalm",
    "today's gospel", "todays gospel", "gospel for today",
    "today's psalm", "todays psalm", "psalm for today",
    "today's reading", "todays reading", "today's readings", "todays readings",
    "daily reading", "daily readings", "mass reading", "mass readings",
    "reading for today", "readings for today",
    "all the readings", "all readings", "the readings for",
]

# SELECTORS run only on a prompt that already triggered, so a bare "psalm" or
# "gospel" is safe here. Order matters: the specific forms are checked before the
# looser ones. Selecting nothing is meaningful — it means "all of them".
_READING_SELECTORS = [
    ("first reading", "First Reading"),
    ("reading 1", "First Reading"),
    ("second reading", "Second Reading"),
    ("reading 2", "Second Reading"),
    ("responsorial psalm", "Responsorial Psalm"),
    ("psalm", "Responsorial Psalm"),
    ("gospel", "Gospel"),
]

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _requested_reading(prompt_lower: str) -> Optional[str]:
    """Which single reading the prompt asks for, or None meaning all of them."""
    for phrase, title in _READING_SELECTORS:
        if phrase in prompt_lower:
            return title
    return None


def _requested_date(prompt_lower: str, today=None):
    """
    The day the prompt asks about, or None for today.

    Accepts `tomorrow`, `yesterday`, a weekday name (the next occurrence, or
    today when it is that weekday), and an explicit ISO `YYYY-MM-DD` — which is
    what a scheduled caller uses, since it needs no interpretation. Returns a
    `datetime.date`, or None when the prompt says nothing about a day.
    """
    today = today or datetime.now(_USCCB_TZ).date()

    iso = _ISO_DATE_RE.search(prompt_lower)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            pass  # 2026-13-45 and friends: fall through to the other cues

    if "tomorrow" in prompt_lower:
        return today + timedelta(days=1)
    if "yesterday" in prompt_lower:
        return today - timedelta(days=1)

    for i, name in enumerate(_WEEKDAYS):
        if name in prompt_lower:
            ahead = (i - today.weekday()) % 7
            return today + timedelta(days=ahead)
    return None

def _parse_usccb_item_description(description_html: str) -> list:
    """
    Extract [{'title', 'citation', 'text'}] from one RSS item's description.
    Each reading is an '<h4>Reading 1  <a href=...>Amos 7:10-17</a></h4>'
    heading; the label is the h4 text minus the link, the citation is the
    link text. Non-reading headings (Alleluia, Sequence, ...) aren't in
    _READING_LABELS and are skipped.
    """
    soup = BeautifulSoup(description_html, "html.parser")
    full_passages = []
    for h4 in soup.find_all("h4"):
        link = h4.find("a")
        if not link:
            continue
        citation = link.get_text(" ", strip=True)
        label = h4.get_text(" ", strip=True)
        if citation and label.endswith(citation):
            label = label[: -len(citation)]
        title = _READING_LABELS.get(label.strip().lower())
        if title and citation:
            full_passages.append({
                "title": title,
                "citation": _normalize_citation(citation),
                "text": "",  # RAG supplies the actual verse text
            })
    return full_passages


async def _fetch_usccb_rss(log: logging.Logger, target_date=None) -> Optional[Dict[str, Any]]:
    """
    Primary source: the USCCB daily-readings RSS feed. Picks the item whose
    link date-code (MMDDYY) matches `target_date` (default: today in US Eastern
    time), preferring the plain daily entry over -Vigil/-Day variants on
    solemnities.

    `target_date` is a `datetime.date`. The feed carries roughly ten days, so
    nearby dates resolve and anything outside that window simply finds no item
    and returns None — which is why a caller that asks for a far date gets the
    same "no readings" path as a caller whose fetch failed.

    Returns the standard readings dict, or None if the fetch/parse yields
    nothing usable (so the caller can fall back).
    """
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(timeout=30.0, verify=_USCCB_SSL_CONTEXT) as client:
        resp = await client.get(_USCCB_RSS_URL, headers=headers, follow_redirects=True)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    now = datetime.now(_USCCB_TZ)
    day = target_date or now.date()
    date_code = day.strftime("%m%d%y")

    candidates = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if re.search(rf"/{date_code}(?:\.cfm)?(?:-|$)", link):
            candidates.append(item)
    if not candidates:
        log.warning("USCCB RSS feed had no item for %s (%s).", day.isoformat(), date_code)
        return None

    # Solemnities publish -Vigil/-Day variants alongside the plain entry, and
    # the plain MMDDYY(.cfm) item is then only a stub linking to them. Try the
    # plain entry first, then Mass during the Day, and use the first item that
    # actually contains readings.
    def _rank(item) -> int:
        link = (item.findtext("link") or "").strip()
        if re.search(rf"/{date_code}(?:\.cfm)?$", link):
            return 0
        if link.endswith("-Day"):
            return 1
        return 2

    for item in sorted(candidates, key=_rank):
        full_passages = _parse_usccb_item_description(item.findtext("description") or "")
        if full_passages:
            reading_date = f"{day:%A} {day:%B} {day.day}, {day.year}"
            log.info(f"Successfully fetched {len(full_passages)} passages from USCCB RSS for {reading_date}.")
            return {
                "date": reading_date,
                "full_passages": full_passages,
                "url": item.findtext("link") or _USCCB_RSS_URL,
            }

    log.warning("USCCB RSS items for today had no recognizable readings (feed format may have changed).")
    return None


async def _fetch_readings_from_source(log: logging.Logger, target_date=None) -> Dict[str, Any]:
    """
    Fetch a day's readings. Tries the USCCB RSS feed (authoritative) first,
    then falls back to the livingwithchrist.ca scrape if USCCB is unreachable
    or unparseable. Returns a dict with 'date'/'full_passages' or an 'error'.

    `target_date` (a `datetime.date`) is honoured by USCCB only — the fallback
    scrape publishes one page, always today's. So a dated request that falls
    through to the fallback is refused rather than answered with the wrong day:
    silently returning today's readings under tomorrow's heading is worse than
    saying nothing, since the caller cannot tell the difference.
    """
    try:
        usccb = await _fetch_usccb_rss(log, target_date=target_date)
    except Exception as e:
        log.warning(f"USCCB RSS fetch failed ({type(e).__name__}: {e}); falling back to LivingWithChrist.")
        usccb = None

    if usccb and usccb.get("full_passages"):
        return usccb

    if target_date is not None and target_date != datetime.now(_USCCB_TZ).date():
        log.warning("USCCB had no readings for %s and the fallback source only serves today.",
                    target_date.isoformat())
        return {"error": f"I could not find the readings for {target_date:%A, %B %d, %Y}. "
                         "The authoritative source only publishes about ten days at a time."}

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

    if not any(t in prompt_command for t in _READING_TRIGGERS):
        # Not a readings request. data_payload stays None.
        return original_user_prompt, None

    target_date = _requested_date(prompt_command)
    requested_reading_key = _requested_reading(prompt_command)
    log.info("Readings request detected: '%s' (reading=%s, date=%s)",
             user_prompt, requested_reading_key or "ALL",
             target_date.isoformat() if target_date else "today")

    scraped_data = await _fetch_readings_from_source(log, target_date=target_date)
    if "error" in scraped_data:
        return original_user_prompt, {"plugin_error": scraped_data["error"]}

    passages = [p for p in scraped_data.get("full_passages", []) if p.get("citation")]
    day_label = scraped_data.get("date", "today")

    if not passages:
        return original_user_prompt, {
            "plugin_error": f"I reached the readings source for {day_label} but it listed no readings."
        }

    # --- One specific reading -------------------------------------------------
    if requested_reading_key:
        found = next((p for p in passages if p.get("title") == requested_reading_key), None)
        if found is None:
            # A real liturgical answer, not a lookup failure: weekdays have no
            # Second Reading. Say which readings the day DOES have so the agent
            # can offer them instead of reporting a malfunction.
            available = ", ".join(p["title"] for p in passages)
            return original_user_prompt, {
                "plugin_error": (
                    f"{day_label} has no {requested_reading_key}. The readings for that day are: "
                    f"{available}. Tell the user which readings the day actually has."
                )
            }
        return original_user_prompt, {
            "rag_query_override": found["citation"],
            "preformatted_context_string": (
                f"CONTEXT: The user is asking for the '{found['title']}' for {day_label}, "
                f"which is {found['citation']}. The RAG system has been provided with this text."
            ),
        }

    # --- Every reading the day actually has -----------------------------------
    # This is the branch that used to be unreachable: 'today's reading', 'daily
    # reading', 'mass reading' and 'reading for today' all matched the trigger
    # list, selected nothing, and produced "couldn't find a specific 'None'".
    #
    # Driving the digest off what the source lists — rather than off the weekday —
    # is also what makes a weekday solemnity correct: the Second Reading appears
    # because the day has one, not because it is a Sunday.
    manifest = "; ".join(f"{p['title']} — {p['citation']}" for p in passages)
    return original_user_prompt, {
        # A list: the Intellect runs one retrieval per citation and merges the
        # results, so every reading's verse text reaches the model.
        "rag_query_override": [p["citation"] for p in passages],
        "preformatted_context_string": (
            f"CONTEXT: The user is asking for ALL of the readings for {day_label}. "
            f"The day has {len(passages)}: {manifest}. The RAG system has been provided with "
            "the text of each one. Present every reading, in this order, each under its own "
            "heading with its citation. Do not omit any, and do not add readings the day "
            "does not have."
        ),
    }